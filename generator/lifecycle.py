"""Tailnet state machine (SPEC 4.2) and the planted mechanisms (SPEC 4.3).

The transition table is data: TRANSITIONS lists every allowed edge with its trigger and the
config keys that set its rate, and tests check every logged transition against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from generator.clock import PHASE_LIFECYCLE, daily_probability


class State(IntEnum):
    PERSONAL_FREE = 0
    PERSONAL_PLUS = 1
    BUSINESS_TRIAL = 2
    STARTER = 3
    STANDARD = 4
    PREMIUM = 5
    ENTERPRISE = 6
    PAST_DUE = 7
    CHURNED = 8


SIGNUP = -1  # pseudo-state: the tailnet doesn't exist yet
NOT_CREATED = -1

SELF_SERVE = frozenset({State.STARTER, State.STANDARD, State.PREMIUM})
PAID = SELF_SERVE | {State.PERSONAL_PLUS, State.ENTERPRISE}
LIVE_BUSINESS = SELF_SERVE | {State.BUSINESS_TRIAL, State.ENTERPRISE, State.PAST_DUE}


class Trigger(IntEnum):
    SIGNUP_PERSONAL = 1
    SIGNUP_BUSINESS = 2
    SIGNUP_INTERNAL = 3
    SIGNUP_ENTERPRISE_TAILNET = 4
    PLUS_UPGRADE = 5
    PLUS_DOWNGRADE = 6
    PLUS_RETIREMENT = 7
    TRIAL_CONVERT = 8
    TRIAL_FALLBACK = 9
    UPGRADE_STANDARD_PREMIUM = 10
    UPGRADE_STARTER_PREMIUM = 11
    DOWNGRADE_PREMIUM = 12
    MIGRATION_VOLUNTARY = 13
    MIGRATION_FORCED = 14
    PAYMENT_FAILED = 15
    PAYMENT_RECOVERED = 16
    DUNNING_EXPIRED = 17
    CHURN_VOLUNTARY = 18
    REACTIVATION = 19
    ENTERPRISE_CLOSE = 20
    ENTERPRISE_RENEWAL = 21
    ENTERPRISE_NONRENEWAL = 22
    ENTERPRISE_EXPANSION = 23


@dataclass(frozen=True)
class Edge:
    trigger: Trigger
    sources: frozenset[int]
    targets: frozenset[int]
    change_source: str | None  # raw_app.plan_changes.change_source when the plan changes
    keys: tuple[str, ...]


def _s(*states) -> frozenset[int]:
    return frozenset(int(s) for s in states)


_PAYABLE = (*SELF_SERVE, State.PERSONAL_PLUS)
TRANSITIONS: tuple[Edge, ...] = (
    Edge(Trigger.SIGNUP_PERSONAL, _s(SIGNUP), _s(State.PERSONAL_FREE), None,
         ("population.personal_tailnets", "population.signup_growth_monthly")),
    Edge(Trigger.SIGNUP_BUSINESS, _s(SIGNUP), _s(State.BUSINESS_TRIAL), None,
         ("population.business_tailnets", "population.signup_growth_monthly", "trial.length_days")),
    Edge(Trigger.SIGNUP_INTERNAL, _s(SIGNUP), _s(*SELF_SERVE), None,
         ("population.internal_tailnets",)),
    Edge(Trigger.SIGNUP_ENTERPRISE_TAILNET, _s(SIGNUP), _s(State.ENTERPRISE), None,
         ("enterprise.multi_tailnet_share",)),
    Edge(Trigger.PLUS_UPGRADE, _s(State.PERSONAL_FREE), _s(State.PERSONAL_PLUS), "self_serve",
         ("personal.plus_upgrade_monthly",)),
    Edge(Trigger.PLUS_DOWNGRADE, _s(State.PERSONAL_PLUS), _s(State.PERSONAL_FREE), "self_serve",
         ("personal.plus_downgrade_monthly",)),
    Edge(Trigger.PLUS_RETIREMENT, _s(State.PERSONAL_PLUS), _s(State.PERSONAL_FREE), "self_serve",
         ("personal.plus_retirement_downgrade_share", "personal.plus_retirement_window_days")),
    Edge(Trigger.TRIAL_CONVERT, _s(State.BUSINESS_TRIAL),
         _s(State.STARTER, State.STANDARD, State.PREMIUM), "trial_end",
         ("trial.base_conversion", "trial.bring_to_work_multiplier",
          "trial.premium_share_at_conversion")),
    Edge(Trigger.TRIAL_FALLBACK, _s(State.BUSINESS_TRIAL), _s(State.PERSONAL_FREE), "trial_end",
         ("trial.base_conversion",)),
    Edge(Trigger.UPGRADE_STANDARD_PREMIUM, _s(State.STANDARD), _s(State.PREMIUM), "self_serve",
         ("upgrades.standard_to_premium_monthly", "upgrades.gated_feature_multiplier")),
    Edge(Trigger.UPGRADE_STARTER_PREMIUM, _s(State.STARTER), _s(State.PREMIUM), "self_serve",
         ("upgrades.starter_to_premium_monthly", "upgrades.gated_feature_multiplier")),
    Edge(Trigger.DOWNGRADE_PREMIUM, _s(State.PREMIUM), _s(State.STANDARD, State.STARTER),
         "self_serve", ("upgrades.premium_to_standard_monthly",)),
    Edge(Trigger.MIGRATION_VOLUNTARY, _s(State.STARTER, State.PREMIUM),
         _s(State.STANDARD, State.PREMIUM), "migration_voluntary",
         ("migration.voluntary_monthly_hazard", "migration.high_uplift_voluntary_multiplier",
          "migration.high_uplift_threshold")),
    Edge(Trigger.MIGRATION_FORCED, _s(State.STARTER, State.PREMIUM),
         _s(State.STANDARD, State.PREMIUM), "migration_forced",
         ("legacy_forced_migration_date",)),
    Edge(Trigger.PAYMENT_FAILED, _s(*_PAYABLE), _s(State.PAST_DUE), None,
         ("churn.payment_failure_rate",)),
    Edge(Trigger.PAYMENT_RECOVERED, _s(State.PAST_DUE), _s(*_PAYABLE), None,
         ("churn.dunning_recovery_rate", "churn.dunning_days")),
    Edge(Trigger.DUNNING_EXPIRED, _s(State.PAST_DUE), _s(State.CHURNED), "dunning",
         ("churn.dunning_recovery_rate", "churn.dunning_days")),
    Edge(Trigger.CHURN_VOLUNTARY, _s(*SELF_SERVE), _s(State.CHURNED), "self_serve",
         ("churn.voluntary_monthly", "seats.low_utilization_hazard_multiplier",
          "migration.high_uplift_churn_multiplier")),
    Edge(Trigger.REACTIVATION, _s(State.CHURNED), _s(*_PAYABLE), "self_serve",
         ("churn.reactivation_monthly",)),
    Edge(Trigger.ENTERPRISE_CLOSE, _s(*SELF_SERVE), _s(State.ENTERPRISE), "sales",
         ("enterprise.lead_seat_threshold", "enterprise.lead_to_close",
          "enterprise.lead_to_close_lag_days", "enterprise.term_months",
          "enterprise.marketplace_share")),
    Edge(Trigger.ENTERPRISE_RENEWAL, _s(State.ENTERPRISE), _s(State.ENTERPRISE), "sales",
         ("enterprise.renewal_rate", "enterprise.renewal_uplift_mean")),
    Edge(Trigger.ENTERPRISE_NONRENEWAL, _s(State.ENTERPRISE), _s(State.CHURNED), "sales",
         ("enterprise.renewal_rate",)),
    Edge(Trigger.ENTERPRISE_EXPANSION, _s(State.ENTERPRISE), _s(State.ENTERPRISE), None,
         ("enterprise.expansion_monthly", "enterprise.expansion_seat_pct_mean")),
)  # fmt: skip

ALLOWED = frozenset((e.trigger, s, t) for e in TRANSITIONS for s in e.sources for t in e.targets)
CHANGE_SOURCE = {e.trigger: e.change_source for e in TRANSITIONS}
# Transitions that start a plan term; none may start a v3 plan on or after v4_effective_date.
PLAN_STARTS = frozenset({
    Trigger.SIGNUP_INTERNAL, Trigger.SIGNUP_ENTERPRISE_TAILNET, Trigger.PLUS_UPGRADE,
    Trigger.TRIAL_CONVERT, Trigger.UPGRADE_STANDARD_PREMIUM, Trigger.UPGRADE_STARTER_PREMIUM,
    Trigger.DOWNGRADE_PREMIUM, Trigger.MIGRATION_VOLUNTARY, Trigger.MIGRATION_FORCED,
    Trigger.REACTIVATION, Trigger.ENTERPRISE_CLOSE, Trigger.ENTERPRISE_RENEWAL,
})  # fmt: skip

PLAN_STATES = (
    State.PERSONAL_FREE,
    State.PERSONAL_PLUS,
    State.STARTER,
    State.STANDARD,
    State.PREMIUM,
    State.ENTERPRISE,
)


def plan_codes(book) -> tuple[str, ...]:
    """Resolve state-to-plan labels from the committed price book."""
    free = {price.plan_code for price in book if price.billing_basis == "free"}
    if len(free) != 1:
        raise ValueError(f"expected one free plan in price book, found {sorted(free)}")
    codes = (next(iter(free)), *(state.name.lower() for state in PLAN_STATES[1:]))
    present = {price.plan_code for price in book}
    if missing := set(codes) - present:
        raise ValueError(f"state plans missing from price book: {sorted(missing)}")
    return codes


_PLAN_OF_STATE = {
    State.PERSONAL_FREE: 0, State.PERSONAL_PLUS: 1, State.BUSINESS_TRIAL: 4, State.STARTER: 2,
    State.STANDARD: 3, State.PREMIUM: 4, State.ENTERPRISE: 5, State.CHURNED: 0,
}  # fmt: skip
PLAN_OF_STATE = np.array([_PLAN_OF_STATE.get(State(s), -1) for s in range(len(State))], np.int8)
CHANNELS = ("direct", "aws_marketplace", "azure_marketplace")


def plan_state(state: np.ndarray, prev_state: np.ndarray) -> np.ndarray:
    """The plan a tailnet is on: past-due tailnets keep the plan they failed to pay for."""
    return np.where(state == State.PAST_DUE, prev_state, state)


def plan_code_index(state: np.ndarray, prev_state: np.ndarray) -> np.ndarray:
    return PLAN_OF_STATE[plan_state(state, prev_state)]


def seat_based(state: np.ndarray, prev_state: np.ndarray, version: np.ndarray) -> np.ndarray:
    """Plans billed per seat: v4 Standard and Premium, and Enterprise contracts."""
    plan = plan_state(state, prev_state)
    return (
        (plan == State.STANDARD)
        | (plan == State.ENTERPRISE)
        | ((plan == State.PREMIUM) & (version == 4))
    )


def lifecycle_step(sim, t: int, rng: np.random.Generator) -> None:
    """Phase-D transitions for business tailnets on day t; at most one per tailnet per day."""
    cfg, b = sim.config, sim.b
    n = b.n
    done = np.zeros(n, bool)
    sec = rng.integers(*PHASE_LIFECYCLE, size=n)
    version_now = sim.version_on(t)
    first_of_month = t == sim.cal.month_start[sim.cal.month_of[t]]
    v4_era = t >= sim.v4_day
    internal = b.kind == 1

    # Trial end (SPEC 2.4): convert or fall back to Personal.
    ending = np.flatnonzero((b.state == State.BUSINESS_TRIAL) & (b.trial_end_day == t))
    if ending.size:
        u = rng.random((2, ending.size))
        mult = np.where(b.personal_first[ending], cfg.trial.bring_to_work_multiplier, 1.0)
        converts = u[0] < cfg.trial.base_conversion * mult
        premium = u[1] < cfg.trial.premium_share_at_conversion
        base_tier = State.STANDARD if version_now == 4 else State.STARTER
        target = np.where(premium, State.PREMIUM, base_tier)
        win, lose = ending[converts], ending[~converts]
        sim.transition(win, t, sec[win], Trigger.TRIAL_CONVERT, target[converts],
                       version_now)  # fmt: skip
        sim.ensure_seats(win, t, sec[win], "admin")
        sim.transition(lose, t, sec[lose], Trigger.TRIAL_FALLBACK, State.PERSONAL_FREE,
                       version_now)  # fmt: skip
        sim.go_dormant(lose, t, sec[lose])
        done[ending] = True

    # Dunning resolves (SPEC 4.2): recovery or involuntary churn.
    resolving = np.flatnonzero((b.state == State.PAST_DUE) & (b.dunning_day == t) & ~done)
    if resolving.size:
        ok = b.dunning_recovers[resolving]
        back = resolving[ok]
        sim.transition(back, t, sec[back], Trigger.PAYMENT_RECOVERED, b.prev_state[back],
                       b.version[back])  # fmt: skip
        lost = resolving[~ok]
        sim.transition(lost, t, sec[lost], Trigger.DUNNING_EXPIRED, State.CHURNED, version_now)
        sim.go_dormant(lost, t, sec[lost])
        done[resolving] = True

    self_serve = np.isin(b.state, list(SELF_SERVE)) & ~internal
    legacy = self_serve & (b.version == 3)
    if v4_era and (first_of_month or t == sim.v4_day):
        sim.update_uplift(np.flatnonzero(legacy))

    if first_of_month:
        # Payment failure on the 1st-of-month invoice, when it is above zero.
        seat = seat_based(b.state, b.prev_state, b.version)
        billable = np.where(seat, b.held > 0, b.prev_month_mau > 3)
        at_risk = np.flatnonzero(self_serve & billable & ~done)
        u = rng.random((2, at_risk.size))
        fail = at_risk[u[0] < cfg.churn.payment_failure_rate]
        recovers = u[1][u[0] < cfg.churn.payment_failure_rate] < cfg.churn.dunning_recovery_rate
        days = cfg.churn.dunning_days
        b.dunning_recovers[fail] = recovers
        b.dunning_day[fail] = t + np.where(
            recovers, rng.integers(1, days + 1, size=fail.size), days
        )
        sim.transition(fail, t, sec[fail], Trigger.PAYMENT_FAILED, State.PAST_DUE, b.version[fail])
        done[fail] = True

        # Voluntary migration to v4, effective on the 1st (SPEC 2.5).
        if v4_era:
            movers = np.flatnonzero(legacy & ~done)
            mult = np.where(
                b.high_uplift[movers], cfg.migration.high_uplift_voluntary_multiplier, 1
            )
            go = movers[rng.random(movers.size) < cfg.migration.voluntary_monthly_hazard * mult]
            target = np.where(b.state[go] == State.PREMIUM, State.PREMIUM, State.STANDARD)
            sim.transition(go, t, sec[go], Trigger.MIGRATION_VOLUNTARY, target, 4)
            sim.ensure_seats(go, t, sec[go], "admin")
            done[go] = True

    _enterprise(sim, t, rng, sec, done, version_now)
    _self_serve_hazards(sim, t, rng, sec, done, version_now)

    # Reactivation: back to the same tier on the current price version (SPEC 2.5).
    churned = np.flatnonzero(
        (b.state == State.CHURNED) & np.isin(b.prev_state, list(SELF_SERVE)) & ~internal & ~done
    )
    back = churned[rng.random(churned.size) < daily_probability(cfg.churn.reactivation_monthly)]
    prev = b.prev_state[back]
    target = np.where(prev == State.PREMIUM, State.PREMIUM,
                      State.STANDARD if version_now == 4 else State.STARTER)  # fmt: skip
    sim.transition(back, t, sec[back], Trigger.REACTIVATION, target, version_now)
    sim.ensure_seats(back, t, sec[back], "admin", reset=True)


def _enterprise(sim, t, rng, sec, done, version_now):
    cfg, b = sim.config, sim.b
    e = cfg.enterprise
    internal = b.kind == 1
    self_serve = np.isin(b.state, list(SELF_SERVE)) & ~internal

    # Leads close into contracts after a lag (SPEC 2.6).
    closing = np.flatnonzero((b.close_day == t) & self_serve & ~done)
    if closing.size:
        terms = sim.draw_terms(rng, closing.size)
        channel = rng.choice(
            3, size=closing.size,
            p=[1 - sum(e.marketplace_share.values()),
               e.marketplace_share.get("aws", 0.0), e.marketplace_share.get("azure", 0.0)],
        )  # fmt: skip
        sim.transition(closing, t, sec[closing], Trigger.ENTERPRISE_CLOSE, State.ENTERPRISE,
                       version_now)  # fmt: skip
        b.term_months[closing] = terms
        b.term_end_day[closing] = [sim.term_end(t, m) for m in terms]
        b.channel[closing] = channel
        sim.ensure_seats(closing, t, sec[closing], "system", always_record=True)
        done[closing] = True
        spawn = closing[rng.random(closing.size) < e.multi_tailnet_share]
        for parent in spawn.tolist():
            sim.request_spawn(parent, int(sec[parent]) + 1)

    # Seat count reaching the threshold makes a lead; some close after a lag.
    size = np.maximum(b.held, b.occupied + b.pending)
    new_leads = np.flatnonzero(self_serve & ~b.lead & (size >= e.lead_seat_threshold))
    b.lead[new_leads] = True
    closes = new_leads[rng.random(new_leads.size) < e.lead_to_close]
    lo, hi = e.lead_to_close_lag_days
    b.close_day[closes] = t + rng.integers(lo, hi + 1, size=closes.size)

    # Term end: renew (legacy terms move to v4) or churn; extra tailnets follow their parent.
    ending = np.flatnonzero((b.state == State.ENTERPRISE) & (b.term_end_day == t) & ~done)
    if ending.size:
        renew = rng.random(ending.size) < e.renewal_rate
        parent = b.parent[ending]
        decided = dict(zip(ending.tolist(), renew.tolist(), strict=True))
        renew = np.array([decided.get(p, r) for p, r in zip(parent.tolist(), renew, strict=True)])
        kept, lost = ending[renew], ending[~renew]
        sim.transition(kept, t, sec[kept], Trigger.ENTERPRISE_RENEWAL, State.ENTERPRISE,
                       version_now)  # fmt: skip
        terms = sim.draw_terms(rng, kept.size)
        b.term_months[kept] = terms
        b.term_end_day[kept] = [sim.term_end(t, m) for m in terms]
        sim.transition(lost, t, sec[lost], Trigger.ENTERPRISE_NONRENEWAL, State.CHURNED,
                       version_now)  # fmt: skip
        sim.go_dormant(lost, t, sec[lost])
        done[ending] = True

    # Mid-term expansion adds contracted seats.
    active = np.flatnonzero((b.state == State.ENTERPRISE) & ~done)
    grow = active[rng.random(active.size) < daily_probability(e.expansion_monthly)]
    if grow.size:
        extra = np.maximum(1, np.rint(b.held[grow] * rng.exponential(e.expansion_seat_pct_mean,
                                                                     size=grow.size)))  # fmt: skip
        sim.transition(grow, t, sec[grow], Trigger.ENTERPRISE_EXPANSION, State.ENTERPRISE,
                       b.version[grow])  # fmt: skip
        sim.set_seats(grow, b.held[grow] + extra.astype(np.int32), t, sec[grow], "system")
        done[grow] = True


def _self_serve_hazards(sim, t, rng, sec, done, version_now):
    cfg, b = sim.config, sim.b
    internal = b.kind == 1
    at_risk = np.flatnonzero(np.isin(b.state, list(SELF_SERVE)) & ~internal & ~done)
    if not at_risk.size:
        return
    state = b.state[at_risk]
    low = b.low_days[at_risk] >= cfg.seats.low_utilization_days
    uplift = (b.version[at_risk] == 3) & b.high_uplift[at_risk] & (t >= sim.v4_day)
    gated = (t - b.last_gated_day[at_risk]) <= 30

    churn_mult = np.where(low, cfg.seats.low_utilization_hazard_multiplier, 1.0) * np.where(
        uplift, cfg.migration.high_uplift_churn_multiplier, 1.0
    )
    p_churn = daily_probability(cfg.churn.voluntary_monthly, churn_mult)
    gate_mult = np.where(gated, cfg.upgrades.gated_feature_multiplier, 1.0)
    p_move = np.select(
        [state == State.STANDARD, state == State.STARTER, state == State.PREMIUM],
        [
            daily_probability(cfg.upgrades.standard_to_premium_monthly, gate_mult),
            daily_probability(cfg.upgrades.starter_to_premium_monthly, gate_mult),
            daily_probability(cfg.upgrades.premium_to_standard_monthly),
        ],
    )
    u = rng.random((2, at_risk.size))
    churn = u[0] < p_churn
    move = (u[1] < p_move) & ~churn

    sim.stats.churn_exposure(low, uplift, churn)
    sim.stats.upgrade_exposure(state, gated, move)

    gone = at_risk[churn]
    sim.transition(gone, t, sec[gone], Trigger.CHURN_VOLUNTARY, State.CHURNED, version_now)
    sim.go_dormant(gone, t, sec[gone])

    movers, from_state = at_risk[move], state[move]
    up = movers[from_state != State.PREMIUM]
    trigger = np.where(b.state[up] == State.STANDARD, Trigger.UPGRADE_STANDARD_PREMIUM,
                       Trigger.UPGRADE_STARTER_PREMIUM)  # fmt: skip
    for trig in (Trigger.UPGRADE_STANDARD_PREMIUM, Trigger.UPGRADE_STARTER_PREMIUM):
        idx = up[trigger == trig]
        sim.transition(idx, t, sec[idx], trig, State.PREMIUM, b.version[idx])
    down = movers[from_state == State.PREMIUM]
    sim.transition(down, t, sec[down], Trigger.DOWNGRADE_PREMIUM,
                   np.where(b.version[down] == 4, State.STANDARD, State.STARTER),
                   b.version[down])  # fmt: skip
    sim.ensure_seats(movers, t, sec[movers], "admin")
    done[at_risk[churn | move]] = True


# Personal tailnets (monthly) ----------------------------------------------------------------


def simulate_personal(sim) -> None:
    """Monthly loop over personal tailnets: Personal Plus upgrades, downgrades, the v4
    retirement, payment failures, and reactivation (SPEC 2.5, 4.2)."""
    from generator.rng import Stream, period_rng

    cfg, cal, p = sim.config, sim.cal, sim.pop.personal
    n = p.created_day.size
    state = np.full(n, NOT_CREATED, np.int8)
    version = np.zeros(n, np.int8)
    v4_day = sim.v4_day
    day_p = {
        "up": cfg.personal.plus_upgrade_monthly,
        "down": cfg.personal.plus_downgrade_monthly,
        "react": cfg.churn.reactivation_monthly,
    }
    lo, hi = PHASE_LIFECYCLE
    for m in range(len(cal.months)):
        rng = period_rng(cfg.seed, Stream.PERSONAL_MONTH, m)
        start, end = int(cal.month_start[m]), int(cal.month_end[m])

        new = np.flatnonzero((p.created_day >= start) & (p.created_day <= end))
        state[new] = State.PERSONAL_FREE
        version[new] = np.where(p.created_day[new] >= v4_day, 4, 3)
        sim.log_personal(new, p.created_day[new], p.created_sec[new], Trigger.SIGNUP_PERSONAL,
                         SIGNUP, 0, State.PERSONAL_FREE, version[new])  # fmt: skip

        # 1st-of-month invoice for Personal Plus: failure, then recovery or churn in dunning.
        plus = np.flatnonzero((state == State.PERSONAL_PLUS) & (p.created_day < start))
        u = rng.random((3, plus.size))
        fail = plus[u[0] < cfg.churn.payment_failure_rate]
        recovers = u[1][u[0] < cfg.churn.payment_failure_rate] < cfg.churn.dunning_recovery_rate
        sec = rng.integers(lo, hi, size=(2, fail.size))
        resolve = start + np.where(
            recovers, rng.integers(1, cfg.churn.dunning_days + 1, size=fail.size),
            cfg.churn.dunning_days,
        )  # fmt: skip
        sim.log_personal(fail, start, sec[0], Trigger.PAYMENT_FAILED, State.PERSONAL_PLUS, 3,
                         State.PAST_DUE, 3)  # fmt: skip
        ok, bad = fail[recovers], fail[~recovers]
        sim.log_personal(ok, resolve[recovers], sec[1][recovers], Trigger.PAYMENT_RECOVERED,
                         State.PAST_DUE, 3, State.PERSONAL_PLUS, 3)  # fmt: skip
        churn_version = np.where(resolve[~recovers] >= v4_day, 4, 3)
        sim.log_personal(bad, resolve[~recovers], sec[1][~recovers], Trigger.DUNNING_EXPIRED,
                         State.PAST_DUE, 3, State.CHURNED, churn_version)  # fmt: skip
        state[bad] = State.CHURNED
        version[bad] = churn_version
        failed_now = np.zeros(n, bool)
        failed_now[fail] = True

        # Other monthly events: at most one per tailnet, on a day inside the month.
        u = rng.random((3, n))
        candidates = []
        if start < v4_day:  # Personal Plus is sold only before v4
            free = (state == State.PERSONAL_FREE) & (p.created_day < end)
            first = np.maximum(start, p.created_day + 1)
            last = min(end, v4_day - 1)
            ok = free & (first <= last) & (u[0] < day_p["up"])
            day = first + (u[2] * (last - first + 1)).astype(np.int64)
            candidates.append((ok, day, Trigger.PLUS_UPGRADE, State.PERSONAL_PLUS))
            react = (state == State.CHURNED) & (u[0] < day_p["react"])
            day = start + (u[2] * (min(end, v4_day - 1) - start + 1)).astype(np.int64)
            candidates.append((react, day, Trigger.REACTIVATION, State.PERSONAL_PLUS))
        active_plus = (state == State.PERSONAL_PLUS) & ~failed_now
        retire_day = v4_day + p.plus_retire_offset
        retire = active_plus & p.plus_retire & (retire_day >= start) & (retire_day <= end)
        retire &= retire_day >= v4_day
        candidates.append((retire, retire_day, Trigger.PLUS_RETIREMENT, State.PERSONAL_FREE))
        down = active_plus & ~retire & (u[1] < day_p["down"])
        day = start + (u[2] * (end - start + 1)).astype(np.int64)
        candidates.append((down, day, Trigger.PLUS_DOWNGRADE, State.PERSONAL_FREE))

        for mask, day, trigger, target in candidates:
            idx = np.flatnonzero(mask)
            d = np.broadcast_to(day, (n,))[idx]
            from_state = state[idx].copy()
            new_version = np.where(d >= v4_day, 4, 3) if target == State.PERSONAL_FREE else 3
            sim.log_personal(idx, d, rng.integers(lo, hi, size=idx.size), trigger, from_state,
                             version[idx], target, new_version)  # fmt: skip
            state[idx] = target
            version[idx] = new_version

        sim.stats.personal_month_end(m, state)
    sim.personal_state = state
    sim.personal_version = version

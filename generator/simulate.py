"""Simulation driver: business tailnets day by day, personal tailnets month by month.

Business state lives in numpy arrays ordered by business ordinal (creation order). Each day
advances every tailnet at once with vectorized draws from one generator per (stream, day),
in a fixed order of phases (ADR-023): activation, departures, admin seat actions, logins,
activity, then lifecycle transitions. Same-day events get time-of-day windows in that same
order, so seat ledgers read consistently.
"""

from __future__ import annotations

import numpy as np

from generator import activity, enterprise, seats
from generator.clock import Calendar, add_months
from generator.config import SimulationConfig
from generator.lifecycle import (
    LIVE_BUSINESS,
    NOT_CREATED,
    SELF_SERVE,
    SIGNUP,
    State,
    Trigger,
    lifecycle_step,
    plan_code_index,
    plan_codes,
    seat_based,
    simulate_personal,
)
from generator.population import (
    CURRENCIES,
    KIND_CHILD,
    KIND_DIRECT,
    KIND_INTERNAL,
    KIND_TRIAL,
    Population,
)
from generator.reference import FEATURES, Seeds
from generator.rng import Stream, period_rng
from generator.world import Columns, Log

BUSINESS_FIELDS = {
    "created_day": (np.int32, -1), "created_sec": (np.int32, 0), "kind": (np.int8, 0),
    "parent": (np.int32, -1), "company": (np.int32, -1), "currency": (np.int8, 0),
    "nonprofit": (bool, False), "personal_first": (bool, False), "origin_personal": (np.int32, -1),
    "shared_machine": (bool, False), "growth_mult": (np.float64, 1.0),
    "approval_required": (bool, False), "advanced_interest": (bool, False),
    "premium_interest": (bool, False), "tagged_resources": (np.int32, 0),
    "ephemeral": (bool, False), "initial_users": (np.int32, 1), "company_size": (np.int32, 1),
    "creator": (np.int32, -1),
    "creator_user": (np.int32, -1),
    "state": (np.int8, NOT_CREATED), "version": (np.int8, 0), "prev_state": (np.int8, -1),
    "trial_end_day": (np.int32, -1), "trial_version": (np.int8, 0),
    "held": (np.int32, 0), "occupied": (np.int32, 0), "pending": (np.int32, 0),
    "low_days": (np.int32, 0), "last_gated_day": (np.int32, -(10**6)),
    "high_uplift": (bool, False), "uplift": (np.float64, np.nan),
    "dunning_day": (np.int32, -1), "dunning_recovers": (bool, False),
    "lead": (bool, False), "lead_day": (np.int32, -1), "lead_source": (np.int8, 0),
    "close_day": (np.int32, -1), "enterprise_source": (np.int8, 0),
    "term_end_day": (np.int32, -1),
    "term_months": (np.int16, 0), "channel": (np.int8, -1),
    "month_mau": (np.int32, 0), "prev_month_mau": (np.int32, 0),
}  # fmt: skip
FROM_POPULATION = (
    "created_day", "created_sec", "kind", "company", "currency", "nonprofit", "personal_first",
    "origin_personal", "shared_machine", "growth_mult", "approval_required", "advanced_interest",
    "premium_interest", "tagged_resources", "ephemeral", "initial_users", "company_size", "creator",
    "lead_day", "close_day", "lead_source",
)  # fmt: skip


class Stats:
    """Exposure and event counters for the calibration report (SPEC 4.3)."""

    def __init__(self, n_months: int):
        self.churn_exposure_days = np.zeros((2, 2), np.int64)  # [low][high uplift]
        self.churn_event_count = np.zeros((2, 2), np.int64)
        self.removal_exposure_days = np.zeros((2, 2), np.int64)  # [seat-based][low]
        self.removal_event_count = np.zeros((2, 2), np.int64)
        self.upgrade_exposure_days = {s: np.zeros(2, np.int64) for s in ("standard", "starter")}
        self.upgrade_event_count = {s: np.zeros(2, np.int64) for s in ("standard", "starter")}
        self.paying_month_end = np.zeros(n_months, np.int64)
        self.personal_plus_month_end = np.zeros(n_months, np.int64)
        self.utilization_seat: list[np.ndarray] = []
        self.utilization_mau: list[np.ndarray] = []
        self.seat_tailnet_days = 0
        self.live_tailnet_days = 0
        self.auto_seat_tailnet_days = 0
        self.min_seat_slack = None

    def churn_exposure(self, low, uplift, churn):
        np.add.at(self.churn_exposure_days, (low.astype(int), uplift.astype(int)), 1)
        np.add.at(self.churn_event_count, (low[churn].astype(int), uplift[churn].astype(int)), 1)

    def removal_exposure(self, seat: bool, low, hit):
        np.add.at(self.removal_exposure_days[int(seat)], low.astype(int), 1)
        np.add.at(self.removal_event_count[int(seat)], low[hit].astype(int), 1)

    def upgrade_exposure(self, state, gated, move):
        for name, s in (("standard", State.STANDARD), ("starter", State.STARTER)):
            mask = state == s
            np.add.at(self.upgrade_exposure_days[name], gated[mask].astype(int), 1)
            np.add.at(self.upgrade_event_count[name], gated[mask & move].astype(int), 1)

    def personal_month_end(self, month: int, state):
        self.personal_plus_month_end[month] = int(np.sum(state == State.PERSONAL_PLUS))


class Simulation:
    def __init__(self, config: SimulationConfig, seeds: Seeds, pop: Population, cal: Calendar):
        self.config, self.seeds, self.pop, self.cal = config, seeds, pop, cal
        self.v4_day = cal.day(config.v4_effective_date)
        self.plan_codes = plan_codes(seeds.price_book)
        n0 = int(np.sum(pop.business.kind != KIND_DIRECT))
        self.direct_population_start = n0
        self.b = Columns(BUSINESS_FIELDS, capacity=max(16, 2 * pop.business.created_day.size))
        self.b.append(n0)
        for field in FROM_POPULATION:
            getattr(self.b, field)[:] = getattr(pop.business, field)[:n0]
        self.contract_events: list[enterprise.ContractEvent] = []
        self.latest_contract: dict[int, enterprise.ContractEvent] = {}
        self.users = Columns(seats.USER_FIELDS, capacity=max(1024, 16 * n0))
        self.transitions = Log({
            "domain": np.int8, "tailnet": np.int32, "day": np.int32, "sec": np.int32,
            "trigger": np.int8, "from_state": np.int8, "from_version": np.int8,
            "to_state": np.int8, "to_version": np.int8, "from_plan": np.int8, "to_plan": np.int8,
        })  # fmt: skip
        self.seat_events = Log({
            "tailnet": np.int32, "user": np.int32, "event_type": np.int8, "held": np.int32,
            "occupied": np.int32, "actor": np.int8, "day": np.int32, "sec": np.int32,
        })  # fmt: skip
        self.activity = Log({
            "tailnet": np.int32, "day": np.int32, "active_users": np.int32,
            "user_devices": np.int32, "tagged_resources": np.int32, "ephemeral_minutes": np.int32,
        })  # fmt: skip
        self.features = Log({
            "tailnet": np.int32, "day": np.int32, "feature": np.int8, "attempts": np.int32,
            "blocked": bool,
        })  # fmt: skip
        self.mau = Log({"user": np.int32, "day": np.int32})
        self.stats = Stats(len(cal.months))
        self.entitlements = _entitlement_matrix(seeds)
        self._next_signup = 0
        self._spawn_requests: list[tuple[int, int]] = []
        self.rng: np.random.Generator | None = None  # the current day's lifecycle stream

    # --- helpers used by lifecycle, seats, and activity --------------------------------

    def version_on(self, day: int) -> int:
        return 4 if day >= self.v4_day else 3

    def seat_mask(self) -> np.ndarray:
        b = self.b
        return seat_based(b.state, b.prev_state, b.version)

    def live_mask(self, t: int, *, created_before: bool = True) -> np.ndarray:
        b = self.b
        created = (b.created_day >= 0) & (
            (b.created_day < t) if created_before else (b.created_day <= t)
        )
        return np.isin(b.state, list(LIVE_BUSINESS)) & created

    def transition(self, idx, t, sec, trigger, to_state, to_version):
        idx = np.asarray(idx, np.int64)
        if idx.size == 0:
            return
        b = self.b
        to_state = np.broadcast_to(np.asarray(to_state, np.int8), idx.shape).copy()
        to_version = np.broadcast_to(np.asarray(to_version, np.int8), idx.shape).copy()
        from_state = b.state[idx].copy()
        from_version = b.version[idx].copy()
        from_plan = np.where(
            from_state == SIGNUP, -1, plan_code_index(from_state, b.prev_state[idx])
        )
        into_past_due = to_state == State.PAST_DUE
        b.prev_state[idx[into_past_due]] = from_state[into_past_due]
        into_churn = to_state == State.CHURNED
        b.prev_state[idx[into_churn]] = np.where(
            from_state[into_churn] == State.PAST_DUE, b.prev_state[idx[into_churn]],
            from_state[into_churn],
        )  # fmt: skip
        b.state[idx] = to_state
        b.version[idx] = to_version
        self.transitions.add(
            domain=1, tailnet=idx, day=t, sec=sec, trigger=int(trigger), from_state=from_state,
            from_version=from_version, to_state=to_state, to_version=to_version,
            from_plan=from_plan, to_plan=plan_code_index(to_state, b.prev_state[idx]),
        )  # fmt: skip

    def log_personal(self, idx, day, sec, trigger, from_state, from_version, to_state, to_version):
        idx = np.asarray(idx, np.int64)
        if idx.size == 0:
            return
        plan = {int(State.PERSONAL_FREE): 0, int(State.PERSONAL_PLUS): 1, int(State.PAST_DUE): 1,
                int(State.CHURNED): 0, SIGNUP: -1}  # fmt: skip
        from_state = np.broadcast_to(np.asarray(from_state, np.int8), idx.shape)
        to_state = np.broadcast_to(np.asarray(to_state, np.int8), idx.shape)
        self.transitions.add(
            domain=0, tailnet=idx, day=day, sec=sec, trigger=int(trigger), from_state=from_state,
            from_version=from_version, to_state=to_state, to_version=to_version,
            from_plan=[plan[int(s)] for s in from_state], to_plan=[plan[int(s)] for s in to_state],
        )  # fmt: skip

    def set_seats(self, idx, held, t, sec, actor: str):
        idx = np.asarray(idx, np.int64)
        if idx.size == 0:
            return
        b = self.b
        b.held[idx] = held
        seats.log_seat_events(
            self, idx, -1, "seats_set", b.held[idx], b.occupied[idx], actor, t, sec
        )

    def ensure_seats(self, idx, t, sec, actor, *, reset=False, always_record=False):
        """Give tailnets that are now seat-based a seat count covering their users plus headroom."""
        idx = np.asarray(idx, np.int64)
        if idx.size == 0:
            return
        b = self.b
        sec = np.broadcast_to(sec, idx.shape)
        on_seats = self.seat_mask()[idx]
        users = b.occupied[idx] + b.pending[idx]
        needs = on_seats & (reset | (b.held[idx] < users) | (b.held[idx] == 0))
        if needs.any():
            headroom = self.rng.poisson(
                self.config.seats.headroom_seats_mean, size=int(needs.sum())
            )
            self.set_seats(idx[needs], users[needs] + headroom, t, sec[needs], actor)
        record = on_seats & ~needs & always_record
        if record.any():
            self.set_seats(idx[record], b.held[idx[record]], t, sec[record], actor)

    def go_dormant(self, idx, t, sec):
        """Stop seat and activity simulation; revoke invites not yet accepted."""
        idx = np.asarray(idx, np.int64)
        if idx.size == 0:
            return
        u, b = self.users, self.b
        sec_of = np.zeros(b.n, np.int32)
        sec_of[idx] = sec
        revoke = np.flatnonzero(np.isin(u.tailnet, idx) & ~u.alive & (u.removed_day < 0))
        u.removed_day[revoke] = t
        u.removed_sec[revoke] = sec_of[u.tailnet[revoke]]
        b.pending[idx] = 0
        b.low_days[idx] = 0

    def update_uplift(self, idx):
        """Projected v4 bill vs current v3 bill for legacy tailnets (SPEC 4.3, 8.5)."""
        if idx.size == 0:
            return
        b, book = self.b, self.seeds.price_book
        ccy = [CURRENCIES[c] for c in b.currency[idx]]
        premium = b.state[idx] == State.PREMIUM
        v3_codes = np.where(premium, State.PREMIUM.name.lower(), State.STARTER.name.lower())
        v4_codes = np.where(premium, State.PREMIUM.name.lower(), State.STANDARD.name.lower())
        old = [book.plan_version_price(code, "v3") for code in v3_codes]
        new = [book.plan_version_price(code, "v4") for code in v4_codes]
        v3_price = np.array(
            [float(price.unit_amount(c)) for price, c in zip(old, ccy, strict=True)]
        )
        v4_price = np.array(
            [float(price.unit_amount(c)) for price, c in zip(new, ccy, strict=True)]
        )
        free = np.array([price.free_units or 0 for price in old])
        v3_bill = np.maximum(0, b.prev_month_mau[idx] - free) * v3_price
        v4_bill = (b.occupied[idx] + b.pending[idx]) * v4_price
        with np.errstate(divide="ignore", invalid="ignore"):
            uplift = np.where(v3_bill > 0, v4_bill / v3_bill - 1, np.inf)
        b.uplift[idx] = uplift
        b.high_uplift[idx] = uplift > self.config.migration.high_uplift_threshold

    def draw_terms(self, rng, n: int) -> np.ndarray:
        terms = self.config.enterprise.term_months
        keys = sorted(terms)
        return np.array(keys)[rng.choice(len(keys), size=n, p=[terms[k] for k in keys])]

    def term_end(self, t: int, months: int) -> int:
        return self.cal.day(add_months(self.cal.dates[t], int(months)))

    def request_spawn(self, parent: int, sec: int) -> None:
        self._spawn_requests.append((parent, sec))

    # --- the loop --------------------------------------------------------------------------

    def run_business(self, order: np.ndarray | None = None, *, add_month_end: bool = False) -> None:
        seed = self.config.seed
        if order is None:
            order = np.argsort(self.b.created_day, kind="stable")
        self._next_signup = 0
        for t in range(self.cal.n_days):
            if t == self.cal.month_start[self.cal.month_of[t]]:
                self.b.prev_month_mau[:] = self.b.month_mau
                self.b.month_mau[:] = 0
            self._activate(t, period_rng(seed, Stream.BUSINESS_ACTIVATE, t), order)
            rng_seats = period_rng(seed, Stream.SEATS, t)
            seats.departures(self, t, rng_seats)
            seats.admin(self, t, rng_seats)
            seats.logins(self, t, rng_seats)
            seats.utilization(self, t)
            activity.daily(
                self, t, period_rng(seed, Stream.ACTIVITY, t), period_rng(seed, Stream.FEATURES, t)
            )
            self.rng = period_rng(seed, Stream.LIFECYCLE, t)
            lifecycle_step(self, t, self.rng)
            self._spawn(t)
            if t == self.cal.month_end[self.cal.month_of[t]]:
                b = self.b
                paying = np.isin(b.state, [*SELF_SERVE, State.ENTERPRISE, State.PAST_DUE])
                count = int(np.sum(paying & (b.kind != KIND_INTERNAL)))
                if add_month_end:
                    self.stats.paying_month_end[self.cal.month_of[t]] += count
                else:
                    self.stats.paying_month_end[self.cal.month_of[t]] = count

    def run_direct_sales(self) -> None:
        """Replay direct deals after PLG with a separate cohort, preserving PLG RNG ordering."""
        source = self.pop.business
        count = source.created_day.size - self.direct_population_start
        if count == 0:
            return
        prior = self.b.n
        saved_state = self.b.state.copy()
        saved_mau = self.b.month_mau.copy()
        saved_previous_mau = self.b.prev_month_mau.copy()
        self.b.state[:prior] = NOT_CREATED
        idx = self.b.append(count)
        for field in FROM_POPULATION:
            getattr(self.b, field)[idx] = getattr(source, field)[self.direct_population_start :]
        self.b.lead[idx] = True
        self.b.enterprise_source[idx] = 1
        order = idx[np.argsort(self.b.created_day[idx], kind="stable")]
        self.run_business(order, add_month_end=True)
        self.b.state[:prior] = saved_state
        self.b.month_mau[:prior] = saved_mau
        self.b.prev_month_mau[:prior] = saved_previous_mau

    def run_personal(self) -> None:
        simulate_personal(self)

    def _activate(self, t, rng, order):
        b = self.b
        start = self._next_signup
        while self._next_signup < order.size and b.created_day[order[self._next_signup]] == t:
            self._next_signup += 1
        idx = order[start : self._next_signup]
        if idx.size == 0:
            return
        version = self.version_on(t)
        trials = idx[b.kind[idx] == KIND_TRIAL]
        internal = idx[b.kind[idx] == KIND_INTERNAL]
        direct = idx[b.kind[idx] == KIND_DIRECT]
        b.trial_version[trials] = version
        b.trial_end_day[trials] = t + self.config.trial.length_days
        self.transition(trials, t, b.created_sec[trials], Trigger.SIGNUP_BUSINESS,
                        State.BUSINESS_TRIAL, version)  # fmt: skip
        self.transition(internal, t, b.created_sec[internal], Trigger.SIGNUP_INTERNAL,
                        State.PREMIUM, version)  # fmt: skip
        self.transition(direct, t, b.created_sec[direct], Trigger.SIGNUP_DIRECT_ENTERPRISE,
                        State.ENTERPRISE, version)  # fmt: skip
        if direct.size:
            terms = self.draw_terms(rng, direct.size)
            e = self.config.enterprise
            channel = rng.choice(
                3,
                size=direct.size,
                p=[
                    1 - sum(e.marketplace_share.values()),
                    e.marketplace_share.get("aws", 0.0),
                    e.marketplace_share.get("azure", 0.0),
                ],
            )
            b.term_months[direct] = terms
            b.term_end_day[direct] = [self.term_end(t, m) for m in terms]
            b.channel[direct] = channel
        self._initial_users(idx, t, rng)
        self.rng = rng
        self.ensure_seats(internal, t, b.created_sec[internal], "system")
        if direct.size:
            contracted = np.maximum(
                self.config.enterprise.lead_seat_threshold, b.company_size[direct]
            )
            self.set_seats(direct, contracted, t, b.created_sec[direct], "system")
            enterprise.record(self, direct, t, b.created_sec[direct], "close", rng)
            spawn = direct[rng.random(direct.size) < self.config.enterprise.multi_tailnet_share]
            for parent in spawn.tolist():
                self.request_spawn(parent, int(b.created_sec[parent]) + 1)

    def _initial_users(self, idx, t, rng):
        b = self.b
        creators = seats.add_users(self, idx, t, b.created_sec[idx], rng, creator=True,
                                   person=b.creator[idx])  # fmt: skip
        b.creator_user[idx] = creators
        n_invites = b.initial_users[idx] - 1
        invited = np.repeat(idx, n_invites)
        seats.add_users(self, invited, t, b.created_sec[invited], rng, earliest_offset=1)

    def _spawn(self, t):
        """Extra tailnets for multi-tailnet enterprise contracts (SPEC 2.6)."""
        if not self._spawn_requests:
            return
        b, cfg, rng = self.b, self.config, self.rng
        for parent, sec in self._spawn_requests:
            child = int(self.b.append(1)[0])
            for field in ("company", "currency", "nonprofit", "advanced_interest",
                          "premium_interest", "version", "term_end_day", "term_months",
                          "channel", "enterprise_source", "lead_source"):  # fmt: skip
                getattr(b, field)[child] = getattr(b, field)[parent]
            b.kind[child], b.parent[child] = KIND_CHILD, parent
            b.created_day[child], b.created_sec[child] = t, sec
            shape = cfg.seats.growth_gamma_shape
            b.growth_mult[child] = rng.gamma(shape, 1.0 / shape)
            b.tagged_resources[child] = rng.poisson(cfg.activity.tagged_resources_mean)
            b.ephemeral[child] = rng.random() < cfg.activity.ephemeral_share
            lognormal = cfg.seats.initial_users_lognormal
            b.initial_users[child] = max(1, round(rng.lognormal(lognormal.mean, lognormal.sigma)))
            b.company_size[child] = b.company_size[parent]
            self.transition([child], t, sec, Trigger.SIGNUP_ENTERPRISE_TAILNET, State.ENTERPRISE,
                            b.version[parent])  # fmt: skip
            self._initial_users(np.array([child]), t, rng)
            self.ensure_seats([child], t, sec, "system")
            enterprise.record(self, [child], t, sec, "child", rng)
        self._spawn_requests.clear()


def _entitlement_matrix(seeds: Seeds) -> np.ndarray:
    """[plan state, price version, feature] -> entitled."""
    codes = {
        state.name.lower(): state
        for state in (State.STARTER, State.STANDARD, State.PREMIUM, State.ENTERPRISE)
    }
    matrix = np.zeros((len(State), 5, len(FEATURES)), bool)
    for plan_code, version in seeds.entitlements.plans:
        if plan_code in codes:
            for f, feature in enumerate(FEATURES):
                matrix[codes[plan_code], int(version[1]), f] = seeds.entitlements.is_entitled(
                    plan_code, version, feature
                )
    return matrix

"""Users, approvals, logins, and the seat ledger with auto seats (SPEC §2).

Seat mechanics, per business tailnet and day:
- Users depart at `seats.user_departure_monthly`, vacating seats; seats held don't change.
- Admins trim (`seats.removal_monthly`, x3 under low utilization): seat-based plans drop seats
  held to occupied plus pending invites; v3 per-active-user plans remove users inactive for
  30 days, since they have no seats to trim.
- Invites arrive at (net growth + departures) per user per month, scaled by the tailnet's
  growth multiplier and by the room left below the company's headcount (logistic growth).
  A self-serve seat plan short of seats buys enough plus headroom first.
- An accepted invite occupies a seat at first login; logging in to a full tailnet adds an
  auto seat. Separately, a full seat-based tailnet gets an unplanned login (an auto-provisioned
  user) with `seats.auto_seat_daily_prob_when_full`.
Utilization is occupied / held on seat plans, and users active in the last 30 days / logged-in
users on v3 plans (the legacy proxy).
"""

from __future__ import annotations

import numpy as np

from generator.clock import DAYS_PER_MONTH, PHASE_DEPARTURES, daily_probability
from generator.lifecycle import SELF_SERVE, State
from generator.population import FIRST_NAMES, KIND_INTERNAL, LAST_NAMES
from generator.world import ranks_within

ROLES = ("owner", "admin", "billing_admin", "member")
SEAT_EVENT_TYPES = ("seats_set", "seat_occupied", "seat_vacated", "auto_seat_added")
ACTORS = ("admin", "system", "scim")
WINDOW_TRIM = (21_600, 27_000)
WINDOW_INVITE = (27_000, 32_400)
WINDOW_LOGIN = (32_400, 60_000)
WINDOW_UNPLANNED = (60_000, 64_800)
INACTIVE_DAYS = 30
USER_FIELDS = {
    "tailnet": (np.int32, -1), "person": (np.int32, -1), "is_creator": (bool, False),
    "role": (np.int8, 3), "first": (np.int16, 0), "last": (np.int16, 0), "fmt": (np.int8, 0),
    "invited_day": (np.int32, -1), "invited_sec": (np.int32, 0),
    "approved_day": (np.int32, -1), "approved_sec": (np.int32, 0),
    "login_day": (np.int32, -1), "login_sec": (np.int32, 0), "alive": (bool, False),
    "logged_in": (bool, False),
    "removed_day": (np.int32, -1), "removed_sec": (np.int32, 0), "expire_day": (np.int32, -1),
    "devices": (np.int8, 1), "propensity": (np.float32, 1.0),
    "last_active_day": (np.int32, -(10**6)), "active_month": (np.int16, -1),
    "relogged": (bool, False),
    "auto_seat": (bool, False), "unplanned": (bool, False),
}  # fmt: skip


def add_users(sim, tailnets, day, sec, rng, *, creator=False, person=None, earliest_offset=0,
              unplanned=False) -> np.ndarray:  # fmt: skip
    """Create users on `tailnets` invited at (day, sec). Creators and unplanned users log in
    at once; other invitees get an approval (if required) and a scheduled first login."""
    tailnets = np.asarray(tailnets, np.int64)
    n = tailnets.size
    if n == 0:
        return np.zeros(0, np.int64)
    cfg, b = sim.config, sim.b
    s, a = cfg.seats, cfg.activity
    idx = sim.users.append(n)
    u = sim.users
    draws = rng.random((8, n))
    u.tailnet[idx] = tailnets
    u.first[idx] = FIRST_NAMES.pick(draws[0])
    u.last[idx] = LAST_NAMES.pick(draws[1])
    u.fmt[idx] = (draws[2] * 4).astype(np.int8)
    roles = np.cumsum([s.role_shares[r] for r in ROLES[1:]])
    u.role[idx] = 0 if creator else 1 + np.minimum(np.searchsorted(roles, draws[3], "right"), 2)
    dormant = draws[4] < a.dormant_user_share
    u.propensity[idx] = np.where(
        dormant, a.dormant_user_propensity, rng.beta(*a.user_propensity_beta, size=n)
    )
    u.devices[idx] = np.minimum(1 + rng.poisson(a.devices_per_user_mean - 1, size=n), 20)
    u.invited_day[idx] = day
    u.invited_sec[idx] = sec
    if person is not None:
        u.person[idx] = person

    if creator or unplanned:
        u.is_creator[idx] = creator
        u.unplanned[idx] = unplanned
        u.login_day[idx], u.login_sec[idx] = day, sec
        u.alive[idx] = True
        u.logged_in[idx] = True
        u.last_active_day[idx] = day
        np.add.at(b.occupied, tailnets, 1)
        return idx

    earliest = day + earliest_offset
    needs_approval = b.approval_required[tailnets]
    lo, hi = s.approval_lag_days
    approved = earliest + rng.integers(lo, hi + 1, size=n)
    u.approved_day[idx] = np.where(needs_approval, approved, -1)
    u.approved_sec[idx] = rng.integers(*WINDOW_INVITE, size=n)
    never = draws[5] < s.never_login_share
    lo, hi = s.login_lag_days
    login = np.maximum(earliest, np.where(needs_approval, approved, earliest)) + rng.integers(
        lo, hi + 1, size=n
    )
    u.login_day[idx] = np.where(never, -1, login)
    u.login_sec[idx] = rng.integers(*WINDOW_LOGIN, size=n)
    u.expire_day[idx] = np.where(never, day + s.invite_expiry_days, -1)
    np.add.at(b.pending, tailnets, 1)
    return idx


def log_seat_events(sim, tailnets, users, event_type, held, occupied, actor, day, sec):
    tailnets = np.asarray(tailnets)
    if tailnets.size == 0:
        return
    sim.seat_events.add(
        tailnet=tailnets, user=users, event_type=SEAT_EVENT_TYPES.index(event_type)
        if isinstance(event_type, str) else event_type,
        held=held, occupied=occupied, actor=ACTORS.index(actor), day=day, sec=sec,
    )  # fmt: skip


def departures(sim, t, rng):
    """Phase A: invites expire and logged-in users leave, vacating seats."""
    b, u, cfg = sim.b, sim.users, sim.config
    live = sim.live_mask(t)

    expiring = np.flatnonzero((u.expire_day == t) & (u.removed_day < 0) & ~u.alive)
    u.removed_day[expiring] = t
    u.removed_sec[expiring] = rng.integers(*PHASE_DEPARTURES, size=expiring.size)
    np.subtract.at(b.pending, u.tailnet[expiring], live[u.tailnet[expiring]].astype(np.int32))

    candidates = np.flatnonzero(u.alive & ~u.is_creator & live[u.tailnet])
    p = daily_probability(cfg.seats.user_departure_monthly)
    leaving = candidates[rng.random(candidates.size) < p]
    secs = rng.integers(*PHASE_DEPARTURES, size=leaving.size)
    order = np.lexsort((secs, u.tailnet[leaving]))
    leaving, secs = leaving[order], secs[order]
    tn = u.tailnet[leaving]
    rank = ranks_within(tn)
    seat = sim.seat_mask()[tn]
    log_seat_events(sim, tn[seat], leaving[seat], "seat_vacated", b.held[tn[seat]],
                    b.occupied[tn[seat]] - rank[seat] - 1, "admin", t, secs[seat])  # fmt: skip
    u.alive[leaving] = False
    u.removed_day[leaving] = t
    u.removed_sec[leaving] = secs
    np.subtract.at(b.occupied, tn, 1)


def admin(sim, t, rng):
    """Phase B: seat trims and inactive-user cleanup, then invites with seat pre-buys."""
    b, u, cfg = sim.b, sim.users, sim.config
    s = cfg.seats
    seat = sim.seat_mask()
    self_serve = np.isin(b.state, list(SELF_SERVE)) & (b.kind != KIND_INTERNAL)
    self_serve &= (b.created_day >= 0) & (b.created_day < t)
    low = b.low_days >= s.low_utilization_days
    mult = np.where(low, s.low_utilization_hazard_multiplier, 1.0)
    p_remove = daily_probability(s.removal_monthly, mult)

    trim_risk = np.flatnonzero(self_serve & seat & (b.held > b.occupied + b.pending))
    inactive = u.alive & ~u.is_creator & (u.last_active_day < t - INACTIVE_DAYS)
    inactive_count = np.bincount(u.tailnet[inactive], minlength=b.n)
    cleanup_risk = np.flatnonzero(self_serve & ~seat & (inactive_count > 0))

    trim = rng.random(trim_risk.size) < p_remove[trim_risk]
    sim.stats.removal_exposure(True, low[trim_risk], trim)
    trimmed = trim_risk[trim]
    sim.set_seats(trimmed, b.occupied[trimmed] + b.pending[trimmed], t,
                  rng.integers(*WINDOW_TRIM, size=trimmed.size), "admin")  # fmt: skip

    clean = rng.random(cleanup_risk.size) < p_remove[cleanup_risk]
    sim.stats.removal_exposure(False, low[cleanup_risk], clean)
    hit = np.zeros(b.n, bool)
    hit[cleanup_risk[clean]] = True
    removed = np.flatnonzero(inactive & hit[u.tailnet])
    u.alive[removed] = False
    u.removed_day[removed] = t
    u.removed_sec[removed] = rng.integers(*WINDOW_TRIM, size=removed.size)
    np.subtract.at(b.occupied, u.tailnet[removed], 1)

    live = np.flatnonzero(sim.live_mask(t))
    gross = (s.monthly_user_growth + s.user_departure_monthly) / DAYS_PER_MONTH
    users = b.occupied[live] + b.pending[live]
    room = np.clip(1 - users / b.company_size[live], 0, 1)  # logistic: growth stops at headcount
    rate = users * gross * b.growth_mult[live] * room
    rate *= np.where(b.personal_first[live], s.bring_to_work_growth_multiplier, 1.0)
    count = np.minimum(rng.poisson(rate), np.maximum(0, b.company_size[live] - users))
    invite_sec = rng.integers(*WINDOW_INVITE, size=live.size)
    inviting = np.repeat(live, count)
    add_users(sim, inviting, t, np.repeat(invite_sec, count), rng)

    short = live[(self_serve & seat)[live] & (b.held[live] < b.occupied[live] + b.pending[live])]
    if short.size:
        sec_of = dict(zip(live.tolist(), invite_sec.tolist(), strict=True))
        headroom = rng.poisson(s.headroom_seats_mean, size=short.size)
        sim.set_seats(short, b.occupied[short] + b.pending[short] + headroom, t,
                      np.array([sec_of[i] for i in short.tolist()]), "admin")  # fmt: skip


def logins(sim, t, rng):
    """Phase C: scheduled first logins occupy seats or add auto seats; unplanned logins."""
    b, u, cfg = sim.b, sim.users, sim.config
    live = sim.live_mask(t)
    seat = sim.seat_mask()

    due = np.flatnonzero((u.login_day == t) & (u.removed_day < 0) & ~u.alive)
    due = due[live[u.tailnet[due]]]
    due = due[np.lexsort((u.login_sec[due], u.tailnet[due]))]
    tn = u.tailnet[due]
    rank = ranks_within(tn)
    on_seats = seat[tn]
    vacant = b.held[tn] - b.occupied[tn]
    auto = on_seats & (rank >= vacant)
    held_after = b.held[tn] + np.maximum(0, rank - vacant + 1)
    occupied_after = b.occupied[tn] + rank + 1
    log_seat_events(
        sim, tn[on_seats], due[on_seats],
        np.where(auto, SEAT_EVENT_TYPES.index("auto_seat_added"),
                 SEAT_EVENT_TYPES.index("seat_occupied"))[on_seats],
        held_after[on_seats], occupied_after[on_seats], "system", t, u.login_sec[due[on_seats]],
    )  # fmt: skip
    u.alive[due] = True
    u.logged_in[due] = True
    u.auto_seat[due[auto]] = True
    u.last_active_day[due] = t
    np.add.at(b.occupied, tn, 1)
    np.subtract.at(b.pending, tn, 1)
    np.add.at(b.held, tn[auto], 1)
    auto_today = np.zeros(b.n, bool)
    auto_today[tn[auto]] = True

    full = np.flatnonzero(live & seat & (b.held > 0) & (b.occupied >= b.held))
    hit = full[rng.random(full.size) < cfg.seats.auto_seat_daily_prob_when_full]
    secs = rng.integers(*WINDOW_UNPLANNED, size=hit.size)
    new = add_users(sim, hit, t, secs, rng, unplanned=True)
    u = sim.users
    u.auto_seat[new] = True
    b.held[hit] += 1
    log_seat_events(sim, hit, new, "auto_seat_added", b.held[hit], b.occupied[hit], "scim", t, secs)
    auto_today[hit] = True

    stats = sim.stats
    stats.live_tailnet_days += int(live.sum())
    stats.seat_tailnet_days += int((live & seat).sum())
    stats.auto_seat_tailnet_days += int(auto_today.sum())


def utilization(sim, t):
    """Daily utilization, the low-utilization counter, and the seats-held invariant."""
    b, u, cfg = sim.b, sim.users, sim.config
    live = sim.live_mask(t)
    seat = sim.seat_mask()
    on_seats = live & seat
    short = on_seats & (b.held < b.occupied)
    if short.any():
        i = int(np.flatnonzero(short)[0])
        raise AssertionError(
            f"day {t}: tailnet {i} holds {b.held[i]} seats with {b.occupied[i]} occupied"
        )
    recent = u.alive & (u.last_active_day >= t - INACTIVE_DAYS + 1)
    active30 = np.bincount(u.tailnet[recent], minlength=b.n)
    with np.errstate(divide="ignore", invalid="ignore"):
        util = np.where(
            seat,
            b.occupied / np.maximum(b.held, 1),
            np.where(b.occupied > 0, active30 / np.maximum(b.occupied, 1), 1.0),
        )
    paid = np.isin(b.state, [*SELF_SERVE, State.ENTERPRISE]) & live & (b.kind != KIND_INTERNAL)
    below = util < cfg.seats.low_utilization_threshold
    past_due = b.state == State.PAST_DUE
    b.low_days[:] = np.where(paid, np.where(below, b.low_days + 1, 0),
                             np.where(past_due, b.low_days, 0))  # fmt: skip
    sim.stats.utilization_seat.append(util[paid & seat].astype(np.float32))
    sim.stats.utilization_mau.append(util[paid & ~seat].astype(np.float32))

"""Activity, feature usage with gated attempts, and device registrations.

Business tailnets get daily rows while live; personal tailnets get monthly rollups only.
A gated attempt is using a feature the tailnet's current plan doesn't include
(seeds/plan_entitlements.csv); trials use Premium's entitlements for their trial version.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from generator.clock import SECONDS_PER_DAY
from generator.lifecycle import State, plan_state
from generator.reference import FEATURES
from generator.rng import Stream, period_rng, table_rng

ADVANCED_FEATURES = ("scim", "mdm_config", "posture_integration")
PREMIUM_FEATURES = ("flow_logs", "log_streaming", "jit_access")
DEVICE_OS = ("macos", "windows", "linux", "ios", "android")
EXTRA_DEVICE_LAG_DAYS = 14
TAGGED_REGISTRATION_DAYS = 30


def daily(sim, t, rng_act, rng_feat):
    b, u, cfg = sim.b, sim.users, sim.config
    a = cfg.activity
    live = sim.live_mask(t, created_before=False)

    present = np.flatnonzero(u.alive & live[u.tailnet])
    base = a.user_active_weekday if sim.cal.weekday[t] < 5 else a.user_active_weekend
    active = rng_act.random(present.size) < base * u.propensity[present]
    active |= u.last_active_day[present] == t  # first login counts as activity
    active_users = present[active]
    u.last_active_day[active_users] = t
    month = sim.cal.month_of[t]
    first_this_month = active_users[u.active_month[active_users] != month]
    u.active_month[first_this_month] = month
    np.add.at(b.month_mau, u.tailnet[first_this_month], 1)
    sim.mau.add(user=first_this_month, day=t)

    tn = np.flatnonzero(live)
    owner = u.tailnet[active_users]
    count = np.bincount(owner, minlength=b.n)[tn]
    devices = np.bincount(owner, weights=u.devices[active_users], minlength=b.n)[tn]
    ephemeral = np.where(
        b.ephemeral[tn] & (count > 0), rng_act.poisson(a.ephemeral_minutes_mean, size=tn.size), 0
    )
    sim.activity.add(
        tailnet=tn,
        day=t,
        active_users=count,
        user_devices=devices.astype(np.int32),
        tagged_resources=b.tagged_resources[tn],
        ephemeral_minutes=ephemeral,
    )

    trial = b.state[tn] == State.BUSINESS_TRIAL
    plan = np.where(trial, State.PREMIUM, plan_state(b.state[tn], b.prev_state[tn]))
    version = np.where(trial, b.trial_version[tn], b.version[tn])
    entitled = sim.entitlements[plan, version]  # (tailnets, features)
    interest = np.ones((tn.size, len(FEATURES)), bool)
    for f, feature in enumerate(FEATURES):
        if feature in ADVANCED_FEATURES:
            interest[:, f] = b.advanced_interest[tn]
        elif feature in PREMIUM_FEATURES:
            interest[:, f] = b.premium_interest[tn]
    prob = np.array([a.feature_daily_prob[f] for f in FEATURES])[None, :] * interest
    prob *= (count > 0)[:, None]
    rows, cols = np.nonzero(rng_feat.random(prob.shape) < prob)
    attempts = 1 + rng_feat.poisson(a.feature_attempts_mean - 1, size=rows.size)
    blocked = ~entitled[rows, cols]
    sim.features.add(tailnet=tn[rows], day=t, feature=cols, attempts=attempts, blocked=blocked)
    b.last_gated_day[tn[rows[blocked]]] = t


@dataclass
class PersonalActivity:
    tailnet: np.ndarray
    month: np.ndarray
    active_users: np.ndarray
    user_devices: np.ndarray
    user_devices_per_user: np.ndarray  # devices of each personal user, by user index


def personal_monthly(sim) -> PersonalActivity:
    """Monthly rollups for every personal tailnet from its creation month on."""
    cfg, cal, p = sim.config, sim.cal, sim.pop.personal
    n_users = p.user_tailnet.size
    rng = table_rng(cfg.seed, Stream.DEVICES, "personal_users")
    devices = np.minimum(1 + rng.poisson(cfg.activity.devices_per_user_mean - 1, n_users), 20)
    parts = {k: [] for k in ("tailnet", "month", "active_users", "user_devices")}
    n_tailnets = p.created_day.size
    for m in range(len(cal.months)):
        end = cal.month_end[m]
        joined = p.user_join_day <= end
        active = joined & (
            period_rng(cfg.seed, Stream.PERSONAL_MONTH, 10_000 + m).random(n_users)
            < cfg.personal.monthly_active_share
        )
        tn = np.flatnonzero(p.created_day <= end)
        parts["tailnet"].append(tn)
        parts["month"].append(np.full(tn.size, m, np.int32))
        parts["active_users"].append(
            np.bincount(p.user_tailnet[active], minlength=n_tailnets)[tn].astype(np.int32)
        )
        parts["user_devices"].append(
            np.bincount(p.user_tailnet[active], weights=devices[active], minlength=n_tailnets)[
                tn
            ].astype(np.int32)
        )
    out = {k: np.concatenate(v) for k, v in parts.items()}
    return PersonalActivity(**out, user_devices_per_user=devices)


@dataclass
class Devices:
    """Device registrations. `domain` 0 = personal tailnet, 1 = business."""

    domain: np.ndarray
    tailnet: np.ndarray
    user: np.ndarray  # user index within the domain; -1 for tagged resources
    machine: np.ndarray
    os: np.ndarray
    is_tagged: np.ndarray
    registered_us: np.ndarray
    removed_us: np.ndarray  # -1 when never removed


def device_registrations(sim, personal: PersonalActivity) -> Devices:
    """User devices from first login (or join) on, plus tagged resources on business tailnets.

    Machines get globally unique ordinals, except that a bring-to-work creator with a shared
    machine registers their personal tailnet's first machine to the business tailnet too.
    """
    cfg, cal, p, b, u = sim.config, sim.cal, sim.pop.personal, sim.b, sim.users
    rng = table_rng(cfg.seed, Stream.DEVICES, "device_registrations")
    os_p = np.array([cfg.activity.device_os_shares.get(o, 0.0) for o in DEVICE_OS])
    end_us = int(cal.epoch_us(cal.n_days - 1, SECONDS_PER_DAY - 1))

    def expand(count, start_us, removed_us):
        owner = np.repeat(np.arange(count.size), count)
        k = np.arange(owner.size) - np.repeat(np.cumsum(count) - count, count)
        lag = rng.integers(0, EXTRA_DEVICE_LAG_DAYS * SECONDS_PER_DAY, size=owner.size)
        registered = start_us[owner] + np.where(k == 0, 0, lag) * 1_000_000
        removed = removed_us[owner]
        keep = (registered <= end_us) & ((removed < 0) | (registered <= removed))
        return owner[keep], k[keep], registered[keep], removed[keep]

    # Personal users register at their join time.
    join_us = cal.epoch_us(p.user_join_day, p.user_join_sec)
    po, pk, preg, prem = expand(personal.user_devices_per_user, join_us, np.full(join_us.size, -1))
    # Business users register at first login and lose devices on removal.
    login_us = np.where(u.logged_in, cal.epoch_us(np.maximum(u.login_day, 0), u.login_sec), -1)
    removed_us = np.where(
        u.removed_day >= 0, cal.epoch_us(np.maximum(u.removed_day, 0), u.removed_sec), -1
    )
    count = np.where(u.logged_in, u.devices, 0)
    bo, bk, breg, brem = expand(count.astype(np.int64), login_us, removed_us)

    n_personal, n_business = po.size, bo.size
    machine = np.arange(n_personal + n_business, dtype=np.int64)
    # Shared machines: the business creator's first device is their personal first device.
    creator_first_device = {}
    personal_creator_user = np.flatnonzero(p.user_is_creator)
    first_dev_of_user = np.full(p.user_tailnet.size, -1, np.int64)
    first_dev_of_user[po[pk == 0]] = np.flatnonzero(pk == 0)
    for i in np.flatnonzero(b.shared_machine & b.personal_first).tolist():
        creator = int(b.creator_user[i])
        personal_user = int(personal_creator_user[b.origin_personal[i]])
        creator_first_device[creator] = first_dev_of_user[personal_user]
    is_first = bk == 0
    for j in np.flatnonzero(is_first).tolist():
        source = creator_first_device.get(int(bo[j]))
        if source is not None and source >= 0:
            machine[n_personal + j] = machine[source]

    # Tagged resources (servers, containers) on business tailnets that ever went live.
    created = np.flatnonzero(b.created_day >= 0)
    tags = b.tagged_resources[created]
    t_owner = np.repeat(created, tags)
    t_reg = (
        cal.epoch_us(b.created_day[t_owner], b.created_sec[t_owner])
        + rng.integers(0, TAGGED_REGISTRATION_DAYS * SECONDS_PER_DAY, size=t_owner.size) * 1_000_000
    )
    t_keep = t_reg <= end_us
    t_owner, t_reg = t_owner[t_keep], t_reg[t_keep]
    t_machine = n_personal + n_business + np.arange(t_owner.size)

    os_draw = rng.choice(len(DEVICE_OS), size=n_personal + n_business, p=os_p / os_p.sum())
    return Devices(
        domain=np.r_[np.zeros(n_personal, np.int8), np.ones(n_business + t_owner.size, np.int8)],
        tailnet=np.r_[p.user_tailnet[po], u.tailnet[bo], t_owner].astype(np.int32),
        user=np.r_[po, bo, np.full(t_owner.size, -1)].astype(np.int64),
        machine=np.r_[machine, t_machine],
        os=np.r_[os_draw, np.full(t_owner.size, DEVICE_OS.index("linux"))].astype(np.int8),
        is_tagged=np.r_[np.zeros(n_personal + n_business, bool), np.ones(t_owner.size, bool)],
        registered_us=np.r_[preg, breg, t_reg],
        removed_us=np.r_[prem, brem, np.full(t_owner.size, -1)],
    )

"""Render the simulation into raw_app tables, the product database as Fivetran lands it.

`tailnets` and `users` are version logs in Fivetran history mode (ADR-008); everything else is
append-only. Load timestamps are the business timestamp plus a sync lag from config.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from generator.activity import DEVICE_OS, Devices, PersonalActivity
from generator.clock import US_PER_DAY, US_PER_SECOND
from generator.ids import machine_key_hash, make_ids
from generator.lifecycle import CHANGE_SOURCE, SIGNUP, Trigger
from generator.population import (
    CURRENCIES,
    FIRST_NAMES,
    KIND_CHILD,
    KIND_TRIAL,
    LAST_NAMES,
    WORK_LOCAL_FORMATS,
    local_part,
)
from generator.reference import FEATURES
from generator.rng import Stream, table_rng
from generator.seats import ACTORS, ROLES, SEAT_EVENT_TYPES

MAX_TS = (dt.date(9999, 12, 31) - dt.date(1970, 1, 1)).days * US_PER_DAY + 86_399_999_000
ONE_MS = 1_000


def _masked(values: np.ndarray, present: np.ndarray) -> np.ma.MaskedArray:
    return np.ma.MaskedArray(values, mask=~present)


def _lag_us(sim, table: str, n: int) -> np.ndarray:
    lo, hi = sim.config.sync.fivetran_lag_minutes
    rng = table_rng(sim.config.seed, Stream.SYNC_LAG, table)
    return rng.integers(lo * 60, hi * 60 + 1, size=n) * US_PER_SECOND


def _fivetran(sim, table: str, event_us: np.ndarray) -> dict[str, np.ndarray]:
    return {
        "_fivetran_synced": event_us + _lag_us(sim, table, event_us.size),
        "_fivetran_deleted": np.zeros(event_us.size, bool),
    }


def _history(sim, table: str, key: np.ndarray, event_us: np.ndarray) -> dict[str, np.ndarray]:
    """History-mode columns for rows already sorted by (key, event time)."""
    start = event_us + _lag_us(sim, table, event_us.size)
    same_key = np.r_[False, key[1:] == key[:-1]]
    while True:  # each version lands strictly after the previous one for its key
        prev = np.r_[np.iinfo(np.int64).min, start[:-1]]
        late = same_key & (start <= prev)
        if not late.any():
            break
        start[late] = prev[late] + 1
    last = np.r_[key[1:] != key[:-1], True]
    end = np.where(last, MAX_TS, np.r_[start[1:], 0] - ONE_MS)
    return {
        "_fivetran_synced": start,
        "_fivetran_deleted": np.zeros(key.size, bool),
        "_fivetran_start": start,
        "_fivetran_end": end,
        "_fivetran_active": last,
    }


class Ids:
    def __init__(self, sim):
        seed, pop, b = sim.config.seed, sim.pop, sim.b
        n_personal = pop.personal.created_day.size
        self.personal_tailnet = np.array(
            make_ids(seed, "tailnet", (f"p{i}" for i in range(n_personal)), "tn_", 12), object
        )
        self.business_tailnet = np.array(
            make_ids(seed, "tailnet", (f"b{i}" for i in range(b.n)), "tn_", 12), object
        )
        n_pu = pop.personal.user_tailnet.size
        self.personal_user = np.array(
            make_ids(seed, "user", (f"p{i}" for i in range(n_pu)), "u_", 12), object
        )
        self.business_user = np.array(
            make_ids(seed, "user", (f"b{i}" for i in range(sim.users.n)), "u_", 12), object
        )

    def tailnet(self, domain, idx):
        return np.where(
            domain == 0,
            self.personal_tailnet[np.where(domain == 0, idx, 0)],
            self.business_tailnet[np.where(domain == 1, idx, 0)],
        )


def _business_emails(sim) -> np.ndarray:
    """Work emails: creators keep their person's address; others are unique per company."""
    pop, b, u = sim.pop, sim.b, sim.users
    taken = {e for e in pop.people.work_email if e} | set(pop.personal.user_email)
    emails = np.empty(u.n, object)
    for i in range(u.n):
        person = int(u.person[i])
        if person >= 0:
            emails[i] = pop.people.work_email[person]
            continue
        domain = pop.company_domain[int(b.company[u.tailnet[i]])]
        local = local_part(
            WORK_LOCAL_FORMATS[int(u.fmt[i])],
            FIRST_NAMES.names[u.first[i]],
            LAST_NAMES.names[u.last[i]],
            0,
        )
        candidate, k = f"{local}@{domain}", 2
        while candidate in taken:
            candidate, k = f"{local}{k}@{domain}", k + 1
        taken.add(candidate)
        emails[i] = candidate
    return emails


def render(sim, personal: PersonalActivity, devices: Devices) -> dict[str, dict[str, object]]:
    ids = Ids(sim)
    return {
        "tailnets": _tailnets(sim, ids),
        "users": _users(sim, ids),
        "seat_events": _seat_events(sim, ids),
        "plan_changes": _plan_changes(sim, ids),
        "device_registrations": _devices(sim, ids, devices),
        "tailnet_activity_daily": _activity_daily(sim, ids),
        "tailnet_activity_monthly": _activity_monthly(sim, ids, personal),
        "feature_usage_daily": _features(sim, ids),
    }


def _plan_changing(tr) -> np.ndarray:
    trial_end = np.isin(tr["trigger"], [Trigger.TRIAL_CONVERT, Trigger.TRIAL_FALLBACK])
    changed = (tr["from_plan"] != tr["to_plan"]) | (tr["from_version"] != tr["to_version"])
    return (tr["from_state"] != SIGNUP) & (changed | trial_end)


def _tailnets(sim, ids):
    cal, pop, b, tr = sim.cal, sim.pop, sim.b, sim.transitions.arrays()
    p = pop.personal
    keep = (tr["from_state"] == SIGNUP) | _plan_changing(tr)
    domain, tn = tr["domain"][keep], tr["tailnet"][keep].astype(np.int64)
    ts = cal.epoch_us(tr["day"][keep], tr["sec"][keep])
    order = np.lexsort((ts, tn, domain))
    domain, tn, ts = domain[order], tn[order], ts[order]
    plan = tr["to_plan"][keep][order]
    version = tr["to_version"][keep][order]
    personal, business = domain == 0, domain == 1
    pi, bi = np.where(personal, tn, 0), np.where(business, tn, 0)

    personal_email = np.array(pop.people.personal_email, object)[p.creator]
    creator_user_personal = ids.personal_user[np.flatnonzero(p.user_is_creator)]
    company = b.company[bi]
    company_name = np.array(sim.pop.company_name, object)[company]
    name = np.where(b.kind[bi] == KIND_CHILD, company_name + " (2)", company_name)
    p_created = cal.epoch_us(p.created_day, p.created_sec)
    b_created = cal.epoch_us(b.created_day, b.created_sec)
    trial = business & (b.kind[bi] == KIND_TRIAL)
    trial_end = cal.epoch_us(b.trial_end_day[bi], b.created_sec[bi])
    key = np.where(personal, "p", "b").astype(object) + tn.astype(str).astype(object)
    return {
        "id": ids.tailnet(domain, tn),
        "name": np.where(personal, personal_email[pi], name),
        "created_at": np.where(personal, p_created[pi], b_created[bi]),
        "creator_user_id": np.where(
            personal, creator_user_personal[pi], ids.business_user[b.creator_user[bi]]
        ),
        "signup_domain": np.where(
            personal,
            np.array([e.split("@")[1] for e in personal_email], object)[pi],
            np.array(pop.company_domain, object)[company],
        ),
        "plan_code": np.array(sim.plan_codes, object)[plan],
        "price_version": np.where(version == 4, "v4", "v3").astype(object),
        "trial_started_at": _masked(b_created[bi], trial),
        "trial_ended_at": _masked(trial_end, trial & (ts >= trial_end)),
        "currency": np.array(CURRENCIES, object)[
            np.where(personal, p.currency[pi], b.currency[bi])
        ],
        "is_nonprofit": business & b.nonprofit[bi],
        "deleted_at": _masked(np.zeros(ts.size, np.int64), np.zeros(ts.size, bool)),
        **_history(sim, "tailnets", key, ts),
    }


def _users(sim, ids):
    cal, p, u = sim.cal, sim.pop.personal, sim.users
    end_us = int(cal.epoch_us(cal.n_days, 0))
    # Business users: a version at each of invite, approval, first login, and removal.
    invited = cal.epoch_us(u.invited_day, u.invited_sec)
    removed = np.where(
        u.removed_day >= 0, cal.epoch_us(np.maximum(u.removed_day, 0), u.removed_sec), -1
    )
    login = np.where(u.logged_in, cal.epoch_us(np.maximum(u.login_day, 0), u.login_sec), -1)
    approved = cal.epoch_us(np.maximum(u.approved_day, 0), u.approved_sec)
    approved_ok = (
        (u.approved_day >= 0) & (approved < end_us) & ((removed < 0) | (approved < removed))
    )
    approved = np.where(approved_ok, approved, -1)
    n = u.n
    events_user = np.r_[np.arange(n), np.arange(n), np.arange(n), np.arange(n)]
    events_ts = np.r_[invited, approved, login, removed]
    real = events_ts >= 0
    pairs = np.unique(np.c_[events_user[real], events_ts[real]], axis=0)
    user, ts = pairs[:, 0], pairs[:, 1]

    emails = _business_emails(sim)
    business = {
        "id": ids.business_user[user],
        "tailnet_id": ids.business_tailnet[u.tailnet[user]],
        "email": emails[user],
        "role": np.array(ROLES, object)[u.role[user]],
        "invited_at": invited[user],
        "approved_at": _masked(approved[user], (approved[user] >= 0) & (approved[user] <= ts)),
        "first_login_at": _masked(login[user], (login[user] >= 0) & (login[user] <= ts)),
        "removed_at": _masked(removed[user], (removed[user] >= 0) & (removed[user] <= ts)),
    }
    # Personal users join and log in at once, and are never removed.
    joined = cal.epoch_us(p.user_join_day, p.user_join_sec)
    n_p = joined.size
    personal = {
        "id": ids.personal_user,
        "tailnet_id": ids.personal_tailnet[p.user_tailnet],
        "email": np.array(p.user_email, object),
        "role": np.where(p.user_is_creator, "owner", "member").astype(object),
        "invited_at": joined,
        "approved_at": _masked(np.zeros(n_p, np.int64), np.zeros(n_p, bool)),
        "first_login_at": _masked(joined, np.ones(n_p, bool)),
        "removed_at": _masked(np.zeros(n_p, np.int64), np.zeros(n_p, bool)),
    }
    out = {
        k: np.ma.concatenate([business[k], personal[k]])
        if isinstance(business[k], np.ma.MaskedArray)
        else np.concatenate([business[k], personal[k]])
        for k in business
    }
    event_us = np.concatenate([ts, joined])
    order = np.lexsort((event_us, out["id"].astype(str)))
    out = {k: v[order] for k, v in out.items()}
    return {**out, **_history(sim, "users", out["id"], event_us[order])}


def _seat_events(sim, ids):
    cal, e = sim.cal, sim.seat_events.arrays()
    ts = cal.epoch_us(e["day"], e["sec"])
    order = np.lexsort((np.arange(ts.size), e["tailnet"], ts))
    e = {k: v[order] for k, v in e.items()}
    ts = ts[order]
    has_user = e["user"] >= 0
    return {
        "id": np.array(make_ids(sim.config.seed, "seat_event", range(ts.size), "se_"), object),
        "tailnet_id": ids.business_tailnet[e["tailnet"]],
        "user_id": np.ma.MaskedArray(
            ids.business_user[np.where(has_user, e["user"], 0)], ~has_user
        ),
        "event_type": np.array(SEAT_EVENT_TYPES, object)[e["event_type"]],
        "seats_held_after": e["held"],
        "seats_occupied_after": e["occupied"],
        "actor": np.array(ACTORS, object)[e["actor"]],
        "occurred_at": ts,
        **_fivetran(sim, "seat_events", ts),
    }


def _plan_changes(sim, ids):
    cal, tr = sim.cal, sim.transitions.arrays()
    keep = _plan_changing(tr)
    tr = {k: v[keep] for k, v in tr.items()}
    ts = cal.epoch_us(tr["day"], tr["sec"])
    order = np.lexsort((tr["tailnet"], tr["domain"], ts))
    tr = {k: v[order] for k, v in tr.items()}
    ts = ts[order]
    plans = np.array(sim.plan_codes, object)
    return {
        "id": np.array(make_ids(sim.config.seed, "plan_change", range(ts.size), "pc_"), object),
        "tailnet_id": ids.tailnet(tr["domain"], tr["tailnet"]),
        "changed_at": ts,
        "from_plan_code": plans[tr["from_plan"]],
        "to_plan_code": plans[tr["to_plan"]],
        "from_price_version": np.where(tr["from_version"] == 4, "v4", "v3").astype(object),
        "to_price_version": np.where(tr["to_version"] == 4, "v4", "v3").astype(object),
        "change_source": np.array([CHANGE_SOURCE[Trigger(t)] for t in tr["trigger"]], object),
        **_fivetran(sim, "plan_changes", ts),
    }


def _devices(sim, ids, d: Devices):
    order = np.lexsort((d.machine, d.user, d.tailnet, d.domain, d.registered_us))
    d = Devices(**{k: getattr(d, k)[order] for k in d.__dataclass_fields__})
    personal = d.domain == 0
    user = np.where(
        personal,
        ids.personal_user[np.where(personal, d.user, 0)],
        ids.business_user[np.where(~personal & (d.user >= 0), d.user, 0)],
    )
    seed = sim.config.seed
    hashes = {m: machine_key_hash(seed, m) for m in np.unique(d.machine).tolist()}
    return {
        "id": np.array(make_ids(seed, "device", range(d.machine.size), "dev_"), object),
        "tailnet_id": ids.tailnet(d.domain, d.tailnet),
        "user_id": np.ma.MaskedArray(user, d.is_tagged),
        "machine_key_hash": np.array([hashes[m] for m in d.machine.tolist()], object),
        "os": np.array(DEVICE_OS, object)[d.os],
        "is_tagged": d.is_tagged,
        "registered_at": d.registered_us,
        "removed_at": _masked(d.removed_us, d.removed_us >= 0),
        **_fivetran(sim, "device_registrations", np.maximum(d.registered_us, d.removed_us)),
    }


def _activity_daily(sim, ids):
    cal, a = sim.cal, sim.activity.arrays()
    return {
        "tailnet_id": ids.business_tailnet[a["tailnet"]],
        "activity_date": cal.epoch_days(a["day"]),
        "active_users": a["active_users"],
        "user_devices": a["user_devices"],
        "tagged_resources": a["tagged_resources"],
        "ephemeral_minutes": a["ephemeral_minutes"],
        **_fivetran(sim, "tailnet_activity_daily", cal.epoch_us(a["day"] + 1, 0)),
    }


def _activity_monthly(sim, ids, p: PersonalActivity):
    cal = sim.cal
    return {
        "tailnet_id": ids.personal_tailnet[p.tailnet],
        "activity_month": cal.epoch_days(cal.month_start[p.month]),
        "active_users": p.active_users,
        "user_devices": p.user_devices,
        **_fivetran(sim, "tailnet_activity_monthly", cal.epoch_us(cal.month_end[p.month] + 1, 0)),
    }


def _features(sim, ids):
    cal, f = sim.cal, sim.features.arrays()
    return {
        "tailnet_id": ids.business_tailnet[f["tailnet"]],
        "activity_date": cal.epoch_days(f["day"]),
        "feature": np.array(FEATURES, object)[f["feature"]],
        "attempts": f["attempts"],
        "gated_blocked": f["blocked"],
        **_fivetran(sim, "feature_usage_daily", cal.epoch_us(f["day"] + 1, 0)),
    }

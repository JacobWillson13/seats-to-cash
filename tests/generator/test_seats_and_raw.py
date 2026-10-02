"""PLAN 1.4: seat occupancy, entitlements, and product-source contracts."""

from bisect import bisect_left
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from generator.clock import Calendar
from generator.config import load_config
from generator.lifecycle import SIGNUP, State
from generator.pipeline import run
from generator.population import build_population
from generator.reference import FEATURES, Seeds
from generator.seats import SEAT_EVENT_TYPES, add_users, departures, logins
from generator.simulate import Simulation
from generator.tables import APP_TABLES

from .conftest import ROOT, SEEDS


@pytest.fixture(scope="module")
def ci_result(tmp_path_factory):
    config = load_config(ROOT / "config" / "ci.yml")
    out = tmp_path_factory.mktemp("ci-seats")
    return run(config, Seeds.load(SEEDS), out, report=False), out


def test_seat_events_replay_exactly_and_counts_never_go_negative(ci_result):
    result, _ = ci_result
    sim = result.sim
    e = sim.seat_events.arrays()
    order = np.lexsort((np.arange(e["day"].size), e["sec"], e["day"], e["tailnet"]))
    previous = {}
    auto = vacated = occupied = 0
    for i in order:
        tailnet = int(e["tailnet"][i])
        event = SEAT_EVENT_TYPES[e["event_type"][i]]
        held, used = int(e["held"][i]), int(e["occupied"][i])
        assert 0 <= used <= held
        if event != "seats_set":
            before_held, before_used = previous[tailnet]
            assert used == before_used + (1 if event != "seat_vacated" else -1)
            assert held == before_held + (1 if event == "auto_seat_added" else 0)
        previous[tailnet] = held, used
        auto += event == "auto_seat_added"
        vacated += event == "seat_vacated"
        occupied += event == "seat_occupied"
    assert auto > 0 and vacated > 0 and occupied > 0
    for tailnet, state in previous.items():
        assert state == (int(sim.b.held[tailnet]), int(sim.b.occupied[tailnet]))
    assert np.all(sim.b.held >= 0)
    assert np.all(sim.b.occupied >= 0)
    assert np.all(sim.b.pending >= 0)
    assert np.all(sim.b.held[sim.seat_mask()] >= sim.b.occupied[sim.seat_mask()])
    assert np.concatenate(sim.stats.utilization_seat).min() < 0.60
    assert np.mean(np.concatenate(sim.stats.utilization_seat) < 0.60) > 0.05


def test_invites_approval_and_first_login_drive_occupancy(ci_result):
    sim = ci_result[0].sim
    u, b = sim.users, sim.b
    invited = np.flatnonzero(~u.is_creator & ~u.unplanned)
    assert invited.size > 0
    approval = invited[b.approval_required[u.tailnet[invited]]]
    assert approval.size > 0
    assert np.all(u.approved_day[approval] >= u.invited_day[approval])
    accepted = invited[u.logged_in[invited]]
    assert accepted.size > 0
    assert np.all(u.login_day[accepted] >= u.invited_day[accepted])
    assert np.all(u.login_day[accepted] >= u.approved_day[accepted])
    never = invited[u.login_day[invited] < 0]
    assert never.size > 0
    assert not np.any(u.logged_in[never])
    events = sim.seat_events.arrays()
    users = events["user"][np.isin(events["event_type"], [1, 3])]
    assert np.all(u.logged_in[users])
    assert np.all(u.login_day[users] == events["day"][np.isin(events["event_type"], [1, 3])])
    assert np.any(u.removed_day >= 0)


def test_daily_activity_and_gating_follow_entitlements(ci_result):
    sim = ci_result[0].sim
    activity = sim.activity.arrays()
    assert np.all(activity["active_users"] >= 0)
    assert np.all(activity["user_devices"] >= activity["active_users"])
    assert np.all(activity["tagged_resources"] >= 0)
    features = sim.features.arrays()
    transitions = sim.transitions.arrays()
    by_tailnet = defaultdict(list)
    for i in range(transitions["day"].size):
        if transitions["domain"][i] == 1:
            by_tailnet[int(transitions["tailnet"][i])].append(i)
    checked = 0
    for tailnet, day, feature, blocked in zip(
        features["tailnet"], features["day"], features["feature"], features["blocked"], strict=True
    ):
        history = by_tailnet[int(tailnet)]
        history.sort(key=lambda i: (transitions["day"][i], transitions["sec"][i]))
        before = bisect_left([transitions["day"][i] for i in history], day) - 1
        if before < 0:
            # A same-day signup is activated before activity; subsequent changes are after it.
            before = 0
            assert transitions["from_state"][history[0]] == SIGNUP
        i = history[before]
        state = int(transitions["to_state"][i])
        version = int(transitions["to_version"][i])
        if state == State.BUSINESS_TRIAL:
            state = State.PREMIUM
            version = int(sim.b.trial_version[tailnet])
        elif state == State.PAST_DUE:
            state = int(transitions["from_state"][i])
        assert bool(blocked) == (not sim.entitlements[state, version, feature]), (
            tailnet,
            day,
            FEATURES[feature],
        )
        checked += 1
    assert checked > 0
    assert np.any(features["blocked"])


def test_eight_raw_tables_have_declared_schema_sort_and_references(ci_result):
    _, out = ci_result
    tables = {name: pq.read_table(out / "raw" / "app" / f"{name}.parquet") for name in APP_TABLES}
    assert len(tables) == 8
    for name, definition in APP_TABLES.items():
        data = tables[name]
        assert data.schema == definition.schema
        assert data.equals(
            data.take(pc.sort_indices(data, [(key, "ascending") for key in definition.sort_key]))
        )
        assert (
            data.select(list(definition.primary_key))
            .group_by(list(definition.primary_key))
            .aggregate([])
            .num_rows
            == data.num_rows
        )
        for column in ("_fivetran_synced",):
            assert pc.max(data[column]).as_py().date() <= ci_result[0].sim.config.extract_date
    tailnets = set(tables["tailnets"]["id"].to_pylist())
    users = set(tables["users"]["id"].to_pylist())
    assert set(tables["tailnets"]["creator_user_id"].to_pylist()) <= users
    for name in APP_TABLES.keys() - {"tailnets"}:
        assert set(tables[name]["tailnet_id"].to_pylist()) <= tailnets
    for name in ("seat_events", "device_registrations"):
        assert set(tables[name]["user_id"].drop_null().to_pylist()) <= users


def test_version_logs_reconstruct_past_without_future_user_or_plan_state(ci_result):
    _, out = ci_result
    for name in ("tailnets", "users"):
        table = pq.read_table(out / "raw" / "app" / f"{name}.parquet").to_pandas()
        for _, versions in table.groupby("id", sort=False):
            starts = versions["_fivetran_start"].to_list()
            assert starts == sorted(set(starts))
            assert versions["_fivetran_synced"].to_list() == starts
            assert versions["_fivetran_active"].sum() == 1
            assert versions["_fivetran_active"].iloc[-1]
            if len(versions) > 1:
                ends = versions["_fivetran_end"].iloc[:-1]
                assert all(
                    end + np.timedelta64(1, "ms") == following
                    for end, following in zip(ends, starts[1:], strict=True)
                )
        if name == "users":
            changed = table.groupby("id").filter(
                lambda rows: (
                    rows["first_login_at"].isna().any() and rows["first_login_at"].notna().any()
                )
            )
            assert not changed.empty
            history = next(iter(changed.groupby("id")))[1]
            before = history.iloc[0]
            after = history[history["first_login_at"].notna()].iloc[0]
            assert before["_fivetran_start"] < after["_fivetran_start"]
            before_snapshot = history[history["_fivetran_start"] <= before["_fivetran_start"]].iloc[
                -1
            ]
            assert pd.isna(before_snapshot["first_login_at"])
            assert (
                history[history["_fivetran_start"] <= after["_fivetran_start"]].iloc[-1][
                    "first_login_at"
                ]
                == after["first_login_at"]
            )
        else:
            changed = table.groupby("id").filter(lambda rows: rows["plan_code"].nunique() > 1)
            assert not changed.empty
            history = next(iter(changed.groupby("id")))[1]
            first = history.iloc[0]
            later = history[history["plan_code"] != first["plan_code"]].iloc[0]
            before = history[history["_fivetran_start"] <= first["_fivetran_start"]].iloc[-1]
            after = history[history["_fivetran_start"] <= later["_fivetran_start"]].iloc[-1]
            assert before["plan_code"] == first["plan_code"]
            assert after["plan_code"] == later["plan_code"]
            assert before["plan_code"] != after["plan_code"]


def test_full_seat_auto_adds_and_departure_reuses_vacancy():
    config = load_config(ROOT / "config" / "simulation.yml")
    config = config.model_copy(
        update={
            "population": config.population.model_copy(
                update={
                    "personal_tailnets": 0,
                    "business_tailnets": 1,
                    "internal_tailnets": 0,
                }
            ),
            "seats": config.seats.model_copy(
                update={
                    "approval_lag_days": (0, 0),
                    "login_lag_days": (0, 0),
                    "never_login_share": 0,
                    "user_departure_monthly": 1,
                    "auto_seat_daily_prob_when_full": 0,
                }
            ),
        }
    )
    cal = Calendar(config.sim_start_date, config.end_date)
    sim = Simulation(config, Seeds.load(SEEDS), build_population(config, cal, internal=False), cal)
    t = cal.day(config.v4_effective_date) + 2
    b = sim.b
    b.created_day[0] = t - 1
    b.state[0], b.version[0] = State.STANDARD, 4
    b.approval_required[0] = True
    b.held[0], b.occupied[0] = 1, 1
    rng = np.random.default_rng(7)
    invited = add_users(sim, [0], t, 28_000, rng)
    assert b.occupied[0] == 1 and b.pending[0] == 1
    assert sim.users.approved_day[invited[0]] == t
    logins(sim, t, rng)
    assert b.held[0] == b.occupied[0] == 2
    assert sim.users.auto_seat[invited[0]]
    assert sim.seat_events.arrays()["event_type"][-1] == SEAT_EVENT_TYPES.index("auto_seat_added")
    departures(sim, t + 1, rng)
    assert b.held[0] == 2 and b.occupied[0] == 1
    config = config.model_copy(
        update={"seats": config.seats.model_copy(update={"user_departure_monthly": 0})}
    )
    sim.config = config
    reused = add_users(sim, [0], t + 1, 28_000, rng)
    logins(sim, t + 1, rng)
    assert b.held[0] == b.occupied[0] == 2
    assert not sim.users.auto_seat[reused[0]]

"""Population totals, transition rules, and pricing boundaries."""

import datetime as dt

import numpy as np
import pytest

from generator.clock import Calendar
from generator.config import load_config
from generator.lifecycle import ALLOWED, TRANSITIONS, State, Trigger, lifecycle_step
from generator.pipeline import run
from generator.population import build_population, monthly_counts
from generator.reference import Seeds
from generator.simulate import Simulation

from .conftest import CONFIG, ROOT, SEEDS


@pytest.fixture(scope="module")
def ci_result(tmp_path_factory):
    config = load_config(ROOT / "config" / "ci.yml")
    return run(config, Seeds.load(SEEDS), tmp_path_factory.mktemp("ci-lifecycle"), report=False)


def test_population_totals_cover_burn_in_and_last_month(ci_result):
    sim = ci_result.sim
    cfg, cal = sim.config, sim.cal
    p, b = sim.pop.personal, sim.pop.business
    assert p.created_day.size == cfg.population.personal_tailnets
    assert np.sum(b.kind == 0) == cfg.population.business_tailnets
    assert np.sum(b.kind == 1) == cfg.population.internal_tailnets
    for starts, total in (
        (p.created_day, cfg.population.personal_tailnets),
        (b.created_day[b.kind == 0], cfg.population.business_tailnets),
    ):
        by_month = np.bincount(cal.month_of[starts], minlength=len(cal.months))
        assert np.array_equal(
            by_month, monthly_counts(total, len(cal.months), cfg.population.signup_growth_monthly)
        )
        assert by_month[:12].sum() > 0  # 2023 burn-in is part of the configured total
        assert by_month[-1] > 0
    assert all(d.endswith(".example") for d in sim.pop.company_domain)
    assert all("@" in e for e in sim.pop.personal.user_email)


def test_logged_transitions_follow_data_edges_and_keep_legacy_terms(ci_result):
    sim = ci_result.sim
    tr = sim.transitions.arrays()
    for trigger, source, target in zip(
        tr["trigger"], tr["from_state"], tr["to_state"], strict=True
    ):
        assert (Trigger(trigger), int(source), int(target)) in ALLOWED
    cfg = sim.config.model_dump()
    for edge in TRANSITIONS:
        for dotted in edge.keys:
            value = cfg
            for part in dotted.split("."):
                value = value[part]
    boundary = sim.v4_day
    conversion = tr["trigger"] == Trigger.TRIAL_CONVERT
    assert np.all(tr["to_version"][conversion & (tr["day"] >= boundary)] == 4)
    assert np.all(tr["to_version"][conversion & (tr["day"] < boundary)] == 3)
    personal = tr["domain"] == 0
    assert set(tr["trigger"][personal].tolist()) == {Trigger.SIGNUP_PERSONAL}  # free, never billed
    migrating = tr["trigger"] == Trigger.MIGRATION_VOLUNTARY
    assert np.all(tr["from_version"][migrating] == 3)
    assert np.all(tr["to_version"][migrating] == 4)
    assert np.all([sim.cal.dates[d].day == 1 for d in tr["day"][migrating]])
    legacy_tier_change = (
        (tr["day"] >= boundary)
        & (tr["from_version"] == 3)
        & np.isin(tr["trigger"], [Trigger.UPGRADE_STARTER_PREMIUM, Trigger.DOWNGRADE_PREMIUM])
    )
    assert np.all(tr["to_version"][legacy_tier_change] == 3)
    assert (
        np.sum(tr["trigger"] == Trigger.SIGNUP_BUSINESS) == sim.config.population.business_tailnets
    )
    assert (
        np.sum(tr["trigger"] == Trigger.SIGNUP_PERSONAL) == sim.config.population.personal_tailnets
    )
    assert np.sum(conversion) + np.sum(tr["trigger"] == Trigger.TRIAL_FALLBACK) > 0
    assert np.any(tr["trigger"] == Trigger.CHURN_VOLUNTARY)
    assert np.any(tr["trigger"] == Trigger.REACTIVATION)


def test_dunning_is_recorded_once_per_episode(ci_result):
    sim = ci_result.sim
    tr = sim.transitions.arrays()
    order = np.lexsort((tr["sec"], tr["day"], tr["tailnet"], tr["domain"]))
    episodes = {}
    for i in order:
        key = (int(tr["domain"][i]), int(tr["tailnet"][i]))
        trigger = Trigger(tr["trigger"][i])
        if trigger == Trigger.PAYMENT_FAILED:
            assert key not in episodes
            episodes[key] = int(tr["day"][i])
        elif trigger in (Trigger.PAYMENT_RECOVERED, Trigger.DUNNING_EXPIRED):
            assert key in episodes
            assert 1 <= int(tr["day"][i]) - episodes.pop(key) <= sim.config.churn.dunning_days


def test_trial_crossing_v4_boundary_converts_on_current_terms():
    cfg = load_config(CONFIG)
    cfg = cfg.model_copy(
        update={
            "population": cfg.population.model_copy(
                update={
                    "personal_tailnets": 0,
                    "business_tailnets": 1,
                    "internal_tailnets": 0,
                }
            ),
            "trial": cfg.trial.model_copy(update={"base_conversion": 1.0}),
        }
    )
    cal = Calendar(cfg.sim_start_date, cfg.end_date)
    sim = Simulation(cfg, Seeds.load(SEEDS), build_population(cfg, cal, internal=False), cal)
    b = sim.b
    t = sim.v4_day
    b.created_day[0] = t - cfg.trial.length_days
    b.state[0] = State.BUSINESS_TRIAL
    b.version[0] = 3
    b.trial_version[0] = 3
    b.trial_end_day[0] = t
    b.occupied[0] = 1
    b.created_sec[0] = 70_000
    rng = np.random.default_rng(17)
    sim.rng = rng
    lifecycle_step(sim, t, rng)
    tr = sim.transitions.arrays()
    assert tr["trigger"][0] == Trigger.TRIAL_CONVERT
    assert tr["to_version"][0] == 4
    assert tr["to_state"][0] in (State.STANDARD, State.PREMIUM)
    assert tr["sec"][0] != b.created_sec[0]  # conversion time is drawn on conversion day
    assert b.held[0] >= b.occupied[0]


def test_existing_price_remains_available_after_sale_window():
    book = Seeds.load(SEEDS).price_book
    old = book.plan_version_price(State.STARTER.name.lower(), "v3")
    assert old.valid_to == dt.date(2026, 4, 7)
    assert old.price_id == book.price(old.price_id).price_id
    assert book.plan_version_price(State.STANDARD.name.lower(), "v4").valid_from == dt.date(
        2026, 4, 8
    )

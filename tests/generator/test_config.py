import datetime as dt
import shutil

import pytest

from generator.config import ConfigError, cross_check, load_config
from generator.reference import Seeds

from .conftest import CONFIG, DELETE, ROOT, SEEDS


def test_default_config_is_valid_and_agrees_with_seeds():
    config = load_config(CONFIG)
    cross_check(config, Seeds.load(SEEDS))
    assert config.seed == 42
    assert config.sim_start_date == dt.date(2023, 1, 1)
    assert config.forced_migration_effective_date == dt.date(2027, 5, 1)


def test_ci_config_is_a_ten_percent_overlay():
    base = load_config(CONFIG)
    ci = load_config(ROOT / "config" / "ci.yml")
    assert ci.population.personal_tailnets == base.population.personal_tailnets // 10
    assert ci.population.business_tailnets == base.population.business_tailnets // 10
    assert ci.population.internal_tailnets == base.population.internal_tailnets // 10
    assert ci.population.currencies == base.population.currencies  # merged, not replaced
    assert ci.enterprise.direct_sales_accounts == 3
    ci_common = ci.model_dump(exclude={"population", "enterprise"})
    base_common = base.model_dump(exclude={"population", "enterprise"})
    assert ci_common == base_common
    ci_enterprise = ci.enterprise.model_dump(exclude={"direct_sales_accounts"})
    base_enterprise = base.enterprise.model_dump(exclude={"direct_sales_accounts"})
    assert ci_enterprise == base_enterprise


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"trial.base_conversion": 1.4},
            "trial.base_conversion: Input should be less than or equal to 1",
        ),
        ({"trial.lenght_days": 14}, "trial.lenght_days: unknown key"),
        ({"churn.dunning_days": DELETE}, "churn.dunning_days: missing required key"),
        ({"population.currencies": {"USD": 0.9, "EUR": 0.2}}, "currencies must sum to 1"),
        ({"population.currencies": {"USD": 0.9, "JPY": 0.1}}, "population.currencies.JPY.[key]"),
        ({"enterprise.discount_range": [0.35, 0.10]}, "discount_range must be [low, high]"),
        ({"enterprise.term_months": {12: 0.5, 18: 0.5}}, "multiples of 12"),
        ({"end_date": dt.date(2027, 1, 1)}, "end_date must be on or before extract_date"),
        ({"reporting_tz": "America/Los_Angles"}, "unknown time zone 'America/Los_Angles'"),
        ({"trial.bring_to_work_multiplier": 4.0}, "bring_to_work_multiplier = 1.12"),
        ({"crm.account_seat_threshold": 30}, "must not exceed enterprise.lead_seat_threshold"),
        ({"legacy_forced_migration_date": dt.date(2026, 1, 1)}, "must be after v4_effective_date"),
    ],
)
def test_invalid_config_names_the_problem(write_config, changes, expected):
    path = write_config(changes)
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert str(path) in str(exc.value)
    assert expected in str(exc.value)


def test_unreadable_configs_fail_clearly(tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "nope.yml")
    (tmp_path / "bad.yml").write_text("seed: [unclosed")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(tmp_path / "bad.yml")
    (tmp_path / "a.yml").write_text("extends: b.yml\n")
    (tmp_path / "b.yml").write_text("extends: a.yml\n")
    with pytest.raises(ConfigError, match="`extends` cycle"):
        load_config(tmp_path / "a.yml")


def _seeds_with(tmp_path, filename, edit):
    seeds_dir = tmp_path / "seeds"
    shutil.copytree(SEEDS, seeds_dir)
    path = seeds_dir / filename
    path.write_text(edit(path.read_text()))
    return Seeds.load(seeds_dir)


def test_cross_check_catches_price_book_drift(tmp_path):
    seeds = _seeds_with(
        tmp_path,
        "price_book.csv",
        lambda s: s.replace("2026-04-08,,self_serve", "2026-04-09,,self_serve"),
    )
    with pytest.raises(ConfigError, match="v4_standard valid_from 2026-04-09 != v4_effective_date"):
        cross_check(load_config(CONFIG), seeds)


def test_cross_check_catches_short_close_calendar(tmp_path):
    seeds = _seeds_with(
        tmp_path, "close_calendar.csv", lambda s: s.replace("2026-09,2026-10-07\n", "")
    )
    with pytest.raises(ConfigError, match="close_calendar.csv is missing periods 2026-09"):
        cross_check(load_config(CONFIG), seeds)


def test_cross_check_requires_room_for_late_rows(write_config):
    config = load_config(write_config({"extract_date": dt.date(2026, 10, 20)}))
    with pytest.raises(ConfigError, match="extract_date 2026-10-20 is too early"):
        cross_check(config, Seeds.load(SEEDS))

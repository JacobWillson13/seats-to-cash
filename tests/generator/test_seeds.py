import datetime as dt
import subprocess
import sys

import pytest

from generator.clock import months_between
from generator.config import load_config
from generator.reference import FEATURES, Seeds

from .conftest import CONFIG, ROOT, SEEDS


@pytest.fixture(scope="module")
def seeds():
    return Seeds.load(SEEDS)


@pytest.fixture(scope="module")
def config():
    return load_config(CONFIG)


def test_entitlements_grid(seeds):
    e = seeds.entitlements
    base = {"ssh", "funnel", "exit_node", "subnet_router"}
    premium_only = {"flow_logs", "log_streaming", "jit_access"}

    def features(plan, version):
        return {f for f in FEATURES if e.is_entitled(plan, version, f)}

    assert len(e.plans) == 9
    for plan in e.plans:
        assert base <= features(*plan)
    assert features("starter", "v3") == base
    assert features("premium", "v3") == base | {"mdm_config", "posture_integration"}
    assert features("standard", "v4") == base | {"scim", "mdm_config", "posture_integration"}
    assert features("premium", "v4") == features("standard", "v4") | premium_only
    assert features("enterprise", "v3") == set(FEATURES)
    assert features("enterprise", "v4") == set(FEATURES)


def test_public_email_domains(seeds):
    domains = seeds.public_email_domains
    assert {"gmail.com", "outlook.com", "yahoo.com"} <= domains
    assert not any(d.endswith(".example") for d in domains)
    assert "wirefern.example" not in domains


def test_close_calendar_is_fifth_weekday_of_next_month(seeds, config):
    calendar = seeds.close_calendar.close_dates
    assert list(calendar) == months_between(config.sim_start_date, config.end_date)
    for period, close in calendar.items():
        year, month = map(int, period.split("-"))
        next_month = dt.date(year + month // 12, month % 12 + 1, 1)
        weekdays = [
            next_month + dt.timedelta(days=i)
            for i in range(10)
            if (next_month + dt.timedelta(days=i)).weekday() < 5
        ]
        assert close == weekdays[4], period
    assert calendar["2026-09"] == dt.date(2026, 10, 7)


def test_fx_covers_every_day_of_the_simulation(seeds, config):
    day = config.sim_start_date
    while day <= config.extract_date:
        for currency in ("EUR", "GBP"):
            assert seeds.fx.usd_per_unit(currency, day) > 0
        day += dt.timedelta(days=1)
    assert seeds.fx.usd_per_unit("USD", day) == 1


def _run(script, *args):
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args], check=True, capture_output=True
    )


def test_close_calendar_script_reproduces_the_committed_seed(tmp_path):
    _run("build_close_calendar.py", "--config", str(CONFIG), "--out", str(tmp_path / "cc.csv"))
    assert (tmp_path / "cc.csv").read_bytes() == (SEEDS / "close_calendar.csv").read_bytes()


def test_free_email_script_reproduces_the_committed_seed(tmp_path):
    _run("build_free_email_domains.py", "--out", str(tmp_path / "fe.csv"))
    assert (tmp_path / "fe.csv").read_bytes() == (SEEDS / "free_email_domains.csv").read_bytes()


def test_fx_fallback_is_seeded_and_labeled(tmp_path):
    outputs = []
    for name in ("a.csv", "b.csv"):
        _run("fetch_fx.py", "--offline", "--config", str(CONFIG), "--out", str(tmp_path / name))
        outputs.append((tmp_path / name).read_text())
    assert outputs[0] == outputs[1]
    rows = outputs[0].splitlines()[1:]
    assert {row.rsplit(",", 1)[1] for row in rows} == {"simulated"}
    assert rows[0].startswith("2023-01-01,EUR,") and rows[-1].startswith("2026-10-31,GBP,")

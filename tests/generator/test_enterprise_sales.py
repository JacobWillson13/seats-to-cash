"""Direct sales enters CRM before the product, and contract facts remain recorded."""

import datetime as dt

import numpy as np
import pyarrow.parquet as pq
import pytest

from generator.config import load_config
from generator.lifecycle import Trigger
from generator.pipeline import run
from generator.population import KIND_DIRECT
from generator.reference import Seeds
from generator.tables import SF_TABLES, TRUTH_TABLES

from .conftest import CONFIG, SEEDS


@pytest.fixture(scope="module")
def enterprise_result(tmp_path_factory):
    out = tmp_path_factory.mktemp("enterprise")
    result = run(load_config(CONFIG), Seeds.load(SEEDS), out, report=False)
    return result, out


def test_two_sources_and_future_pipeline(enterprise_result):
    result, out = enterprise_result
    sim = result.sim
    b = sim.b
    direct = np.flatnonzero(b.kind == KIND_DIRECT)
    assert direct.size == sim.config.enterprise.direct_sales_accounts == 32
    assert np.all(b.created_day[direct] == b.close_day[direct])
    assert np.all(b.lead_day[direct] < b.created_day[direct])
    tr = sim.transitions.arrays()
    plg = int(np.sum(tr["trigger"] == Trigger.ENTERPRISE_CLOSE))
    signed_direct = int(np.sum(tr["trigger"] == Trigger.SIGNUP_DIRECT_ENTERPRISE))
    assert (plg, signed_direct) == (28, 30)
    opportunities = pq.read_table(out / "raw/salesforce/opportunity.parquet").to_pylist()
    latest = {}
    for row in opportunities:
        latest[row["id"]] = row
    open_future = [r for r in latest.values() if r["close_date"] > sim.config.end_date]
    assert open_future
    assert all(not r["is_closed"] and not r["is_won"] for r in open_future)
    assert {r["lead_source"] for r in latest.values()} == {
        "Product Qualified Lead",
        "Inbound",
        "Outbound",
    }
    leads = pq.read_table(out / "raw/salesforce/lead.parquet")
    assert leads.num_rows == 32
    assert min(leads["created_date"].to_pylist()).date() < min(
        sim.cal.dates[int(b.created_day[i])] for i in direct if b.created_day[i] < sim.cal.n_days
    )


def test_contract_truth_and_salesforce_contracts(enterprise_result):
    result, out = enterprise_result
    truth = pq.read_table(out / "answer_key/truth/truth_enterprise_contracts.parquet")
    assert truth.num_rows == len(result.sim.contract_events)
    assert set(truth["enterprise_source"].to_pylist()) == {"plg", "direct"}
    assert set(truth["event_kind"].to_pylist()) >= {"close", "child"}
    for table in (*SF_TABLES.values(), *TRUTH_TABLES.values()):
        root = "answer_key" if table.source == "truth" else "raw"
        data = pq.read_table(out / root / table.source / f"{table.name}.parquet")
        assert data.schema == table.schema
    opportunities = pq.read_table(out / "raw/salesforce/opportunity.parquet").to_pylist()
    won = [row for row in opportunities if row["is_won"]]
    assert len(won) == 58
    assert all(row["close_date"] <= dt.date(2026, 9, 30) for row in won)

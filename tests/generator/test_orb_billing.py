"""Documented invoice histories and complete Orb source invariants."""

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from generator.billing_orb import Builder, Term, allocate_daily, money
from generator.clock import Calendar
from generator.config import load_config
from generator.lifecycle import State, Trigger
from generator.pipeline import run
from generator.reference import Seeds
from generator.tables import ORB_TABLES

from .conftest import ROOT, SEEDS


@pytest.fixture(scope="module")
def ci_orb(tmp_path_factory):
    out = tmp_path_factory.mktemp("ci-orb")
    result = run(load_config(ROOT / "config/ci.yml"), Seeds.load(SEEDS), out, report=False)
    tables = {name: pq.read_table(out / "raw/orb" / f"{name}.parquet") for name in ORB_TABLES}
    return result, tables


def _fixture_builder(terms, seat_events, mau_counts):
    """Exercise the production monthly invoice renderer on a fixed, compact history."""
    cal = Calendar(dt.date(2026, 3, 1), dt.date(2026, 8, 31))
    book = Seeds.load(SEEDS).price_book
    builder = Builder.__new__(Builder)
    builder.cal = cal
    builder.book = book
    builder.sim = SimpleNamespace(
        config=SimpleNamespace(extract_date=dt.date(2026, 10, 31)),
        b=SimpleNamespace(kind=np.zeros(1, np.int8), tagged_resources=np.zeros(1, np.int32)),
    )
    builder.rows = {name: [] for name in ORB_TABLES}
    builder.terms = terms
    builder.by_key = defaultdict(list)
    builder.by_key[1, 0] = terms
    builder.term_by_id = {t.id: t for t in terms}
    builder.seats = defaultdict(list)
    builder.seats[0] = [(cal.day(day), 30_000, held, "admin") for day, held in seat_events]
    builder.mau = defaultdict(set)
    for month, count in mau_counts.items():
        builder.mau[0, month] = set(range(count))
    builder.personal_devices = {}
    builder.business_devices = {}
    builder.mullvad = defaultdict(bool)
    builder.discount_price = {
        "nonprofit": next(p for p in book if p.price_id == "disc_nonprofit"),
        "internal": next(p for p in book if p.price_id == "disc_internal"),
    }
    builder.lines_of = defaultdict(list)
    builder.invoice_latest = {}
    builder.invoice_seq = builder.line_seq = 0
    builder.failures = set()
    return builder


def _term(cal, name, state, version, start, end, *, discount="0"):
    code = state.name.lower()
    price = Seeds.load(SEEDS).price_book.plan_version_price(code, f"v{version}")
    return Term(
        name,
        1,
        0,
        state,
        version,
        cal.day(start),
        30_000,
        cal.day(end) if end else None,
        30_000 if end else None,
        "migrated" if end else None,
        price.price_id,
        "oc_1_0",
        "USD",
        "stripe",
        Decimal(discount),
    )


def _actual(builder):
    builder.self_serve_invoices()
    by_invoice = defaultdict(list)
    for line in builder.rows["invoice_line_items"]:
        by_invoice[line["invoice_id"]].append(line)
    return [
        (
            row["invoice_date"],
            row["service_period_start"],
            row["subtotal"],
            [
                (
                    line["line_type"],
                    line["price_id"],
                    line["start_date"],
                    line["end_date"],
                    line["quantity"],
                    line["unit_amount"],
                    line["amount"],
                )
                for line in by_invoice[row["id"]]
            ],
        )
        for row in builder.invoice_latest.values()
    ]


def test_design_example_standard_adds_seat_on_june_16():
    cal = Calendar(dt.date(2026, 3, 1), dt.date(2026, 8, 31))
    term = _term(cal, "standard", State.STANDARD, 4, dt.date(2026, 6, 1), None)
    b = _fixture_builder([term], [(dt.date(2026, 6, 1), 4), (dt.date(2026, 6, 16), 5)], {})
    actual = _actual(b)
    assert [(d, total) for d, _, total, _ in actual] == [
        (dt.date(2026, 6, 1), "32.00"),
        (dt.date(2026, 7, 1), "44.00"),
        (dt.date(2026, 8, 1), "40.00"),
    ]
    assert [lines for _, _, _, lines in actual] == [
        [
            (
                "fixed",
                "op_v4_standard_usd",
                dt.date(2026, 6, 1),
                dt.date(2026, 6, 30),
                4,
                "8.00",
                "32.00",
            )
        ],
        [
            (
                "fixed",
                "op_v4_standard_usd",
                dt.date(2026, 7, 1),
                dt.date(2026, 7, 31),
                5,
                "8.00",
                "40.00",
            ),
            (
                "proration",
                "op_v4_standard_usd",
                dt.date(2026, 6, 16),
                dt.date(2026, 6, 30),
                1,
                "8.00",
                "4.00",
            ),
        ],
        [
            (
                "fixed",
                "op_v4_standard_usd",
                dt.date(2026, 8, 1),
                dt.date(2026, 8, 31),
                5,
                "8.00",
                "40.00",
            )
        ],
    ]


def test_design_example_starter_migration_has_two_may_invoices():
    cal = Calendar(dt.date(2026, 3, 1), dt.date(2026, 8, 31))
    terms = [
        _term(
            cal,
            "starter",
            State.STARTER,
            3,
            dt.date(2026, 3, 1),
            dt.date(2026, 4, 30),
            discount="0.5",
        ),
        _term(
            cal,
            "standard",
            State.STANDARD,
            4,
            dt.date(2026, 5, 1),
            dt.date(2026, 6, 30),
            discount="0.5",
        ),
    ]
    b = _fixture_builder(terms, [(dt.date(2026, 5, 1), 8)], {0: 7, 1: 8})
    actual = _actual(b)
    assert [(d, total) for d, _, total, _ in actual] == [
        (dt.date(2026, 4, 1), "12.00"),
        (dt.date(2026, 5, 1), "15.00"),
        (dt.date(2026, 5, 1), "32.00"),
        (dt.date(2026, 6, 1), "32.00"),
    ]
    assert [
        [(line[0], line[1], line[4], line[5], line[6]) for line in lines]
        for _, _, _, lines in actual
    ] == [
        [
            ("usage", "op_v3_starter_usd", 4, "6.00", "24.00"),
            ("discount", "op_disc_nonprofit_usd", 1, "-12.00", "-12.00"),
        ],
        [
            ("usage", "op_v3_starter_usd", 5, "6.00", "30.00"),
            ("discount", "op_disc_nonprofit_usd", 1, "-15.00", "-15.00"),
        ],
        [
            ("fixed", "op_v4_standard_usd", 8, "8.00", "64.00"),
            ("discount", "op_disc_nonprofit_usd", 1, "-32.00", "-32.00"),
        ],
        [
            ("fixed", "op_v4_standard_usd", 8, "8.00", "64.00"),
            ("discount", "op_disc_nonprofit_usd", 1, "-32.00", "-32.00"),
        ],
    ]
    assert [line[2:4] for _, _, _, lines in actual for line in lines] == [
        (dt.date(2026, 3, 1), dt.date(2026, 3, 31))
    ] * 2 + [(dt.date(2026, 4, 1), dt.date(2026, 4, 30))] * 2 + [
        (dt.date(2026, 5, 1), dt.date(2026, 5, 31))
    ] * 2 + [(dt.date(2026, 6, 1), dt.date(2026, 6, 30))] * 2


def test_design_example_premium_keeps_legacy_price():
    cal = Calendar(dt.date(2026, 3, 1), dt.date(2026, 8, 31))
    term = _term(cal, "premium", State.PREMIUM, 3, dt.date(2026, 3, 1), dt.date(2026, 6, 30))
    b = _fixture_builder([term], [], {0: 9, 1: 10, 2: 8, 3: 8})
    actual = _actual(b)
    assert [(d, total) for d, _, total, _ in actual] == [
        (dt.date(2026, 4, 1), "108.00"),
        (dt.date(2026, 5, 1), "126.00"),
        (dt.date(2026, 6, 1), "90.00"),
        (dt.date(2026, 7, 1), "90.00"),
    ]
    assert [lines for _, _, _, lines in actual] == [
        [
            (
                "usage",
                "op_v3_premium_usd",
                dt.date(2026, m, 1),
                dt.date(2026, m + 1, 1) - dt.timedelta(days=1),
                qty,
                "18.00",
                amount,
            )
        ]
        for m, qty, amount in ((3, 6, "108.00"), (4, 7, "126.00"), (5, 5, "90.00"), (6, 5, "90.00"))
    ]


def test_rounding_and_daily_last_day_residual():
    amount = Decimal("1.00")
    days = list(allocate_daily(amount, dt.date(2026, 6, 1), dt.date(2026, 6, 3)))
    assert days == [
        (dt.date(2026, 6, 1), Decimal("0.33")),
        (dt.date(2026, 6, 2), Decimal("0.33")),
        (dt.date(2026, 6, 3), Decimal("0.34")),
    ]
    assert money(Decimal("0.005")) == Decimal("0.01")


def test_all_orb_contracts_references_and_amounts(ci_orb):
    result, tables = ci_orb
    for name, definition in ORB_TABLES.items():
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
        assert max(data["_exported_at"].to_pylist()).date() <= result.sim.config.extract_date
    invoices = {r["id"]: r for r in tables["invoices"].to_pylist()}
    lines = tables["invoice_line_items"].to_pylist()
    totals = defaultdict(Decimal)
    line_ids = {r["id"] for r in lines}
    for row in lines:
        totals[row["invoice_id"]] += Decimal(row["amount"])
        assert row["invoice_id"] in invoices
        if row["line_type"] == "discount":
            assert row["applies_to_line_id"] in line_ids
    for iid, row in invoices.items():
        assert totals[iid] == Decimal(row["subtotal"])
        assert Decimal(row["tax"]) == 0
        assert Decimal(row["total"]) == Decimal(row["subtotal"]) + Decimal(row["tax"])
        if Decimal(row["total"]) == 0:
            assert row["external_sync_id"] is None
    daily = defaultdict(Decimal)
    for row in tables["daily_line_item_revenue"].to_pylist():
        daily[row["invoice_line_item_id"]] += Decimal(row["recognized_amount"])
    assert {r["id"]: Decimal(r["amount"]) for r in lines} == daily
    assert all(
        r["external_sync_id"] is None for r in invoices.values() if r["status"] == "external"
    )
    credits = tables["credit_notes"].to_pylist()
    assert {r["reason"] for r in credits} <= {"uncollectible"}
    transitions = result.sim.transitions.arrays()
    assert len(credits) == int(np.sum(transitions["trigger"] == Trigger.DUNNING_EXPIRED))
    assert all(r["type"] == "adjustment" for r in credits)


def test_lifecycle_cadence_and_no_trial_invoices(ci_orb):
    result, tables = ci_orb
    sim = result.sim
    tr = sim.transitions.arrays()
    starts = set()
    for domain, tn, day, trig in zip(
        tr["domain"], tr["tailnet"], tr["day"], tr["trigger"], strict=True
    ):
        if trig in (Trigger.SIGNUP_BUSINESS, Trigger.SIGNUP_PERSONAL):
            starts.add((int(domain), int(tn), int(day)))
    subscriptions = {r["id"]: r for r in tables["subscriptions"].to_pylist()}
    latest = {r["id"]: r for r in tables["invoices"].to_pylist()}
    fixed = defaultdict(set)
    usage = defaultdict(set)
    for line in tables["invoice_line_items"].to_pylist():
        inv = latest[line["invoice_id"]]
        if line["line_type"] == "fixed":
            fixed[inv["customer_id"], line["start_date"]].add(inv["id"])
        if line["line_type"] == "usage":
            usage[inv["customer_id"], line["start_date"]].add(inv["id"])
            assert inv["invoice_date"] == (line["end_date"] + dt.timedelta(days=1))
    assert all(len(ids) == 1 for ids in fixed.values())
    assert all(len(ids) == 1 for ids in usage.values())
    assert not any(r["plan_id"].startswith("plan_personal_v") for r in subscriptions.values())


def test_orb_catalog_and_version_history_have_no_future_state(ci_orb):
    result, tables = ci_orb
    cfg = result.sim.config
    prices = tables["prices"].to_pylist()
    plans = tables["plans"].to_pylist()
    subscriptions = tables["subscriptions"].to_pylist()
    customers = tables["customers"].to_pylist()
    price_ids = {row["id"] for row in prices}
    plan_ids = {row["id"] for row in plans}
    customer_ids = {row["id"] for row in customers}
    subscription_ids = {row["id"] for row in subscriptions}
    assert all(row["plan_id"] in plan_ids for row in prices)
    assert all(
        row["plan_id"] in plan_ids and row["customer_id"] in customer_ids for row in subscriptions
    )
    lines = tables["invoice_line_items"].to_pylist()
    assert all(
        row["price_id"] in price_ids and row["subscription_id"] in subscription_ids for row in lines
    )
    assert all(
        row["subscription_id"] in subscription_ids
        for row in tables["subscription_quantity_changes"].to_pylist()
    )
    assert all(row["customer_id"] in customer_ids for row in tables["invoices"].to_pylist())
    boundary = cfg.v4_effective_date
    assert all(
        row["_exported_at"].date() >= boundary for row in plans if row["price_version"] == "v4"
    )
    for table_name in ("customers", "subscriptions", "invoices"):
        versions = defaultdict(list)
        for row in tables[table_name].to_pylist():
            versions[row["id"]].append(row)
        for history in versions.values():
            timestamps = [row["_exported_at"] for row in history]
            assert timestamps == sorted(set(timestamps))
        changed = next((history for history in versions.values() if len(history) > 1), None)
        if table_name == "customers" and changed is None:
            continue  # no customer changes while marketplace is disabled
        assert changed is not None
        first = changed[0]
        cutoff = first["_exported_at"]
        visible = [r for r in changed if r["_exported_at"] <= cutoff]
        assert visible == [first]
    for row in tables["customers"].to_pylist():
        if row["payment_provider"] is None:
            assert row["payment_provider_id"] is None


def test_every_active_v3_and_v4_month_has_its_required_invoice(ci_orb):
    result, tables = ci_orb
    sim = result.sim
    terms = Builder(sim, result.personal_activity).terms
    term_by_id = {term.id: term for term in terms}
    cal = sim.cal
    expected_v3 = set()
    expected_v4 = set()
    for term in terms:
        if term.domain != 1 or term.state not in (State.STARTER, State.STANDARD, State.PREMIUM):
            continue
        for month in range(len(cal.months)):
            first, last = int(cal.month_start[month]), int(cal.month_end[month])
            if term.start > last or (term.end is not None and term.end < first):
                continue
            if term.version == 3:
                expected_v3.add((term.customer_id, cal.dates[first]))
            else:
                expected_v4.add(
                    (term.customer_id, cal.dates[max(first, term.start)].replace(day=1))
                )
    invoice_by_id = {row["id"]: row for row in tables["invoices"].to_pylist()}
    actual_v3 = defaultdict(set)
    actual_v4 = defaultdict(set)
    for line in tables["invoice_line_items"].to_pylist():
        invoice = invoice_by_id[line["invoice_id"]]
        month = line["start_date"].replace(day=1)
        key = (invoice["customer_id"], month)
        if line["line_type"] == "usage":
            actual_v3[key].add(invoice["id"])
            assert invoice["invoice_date"] == line["end_date"] + dt.timedelta(days=1)
        if (
            line["line_type"] == "fixed"
            and term_by_id[line["subscription_id"]].state in (State.STANDARD, State.PREMIUM)
            and term_by_id[line["subscription_id"]].version == 4
        ):
            actual_v4[key].add(invoice["id"])
    assert set(actual_v3) == expected_v3
    assert set(actual_v4) == expected_v4
    assert all(len(ids) == 1 for ids in actual_v3.values())
    assert all(len(ids) == 1 for ids in actual_v4.values())
    tr = sim.transitions.arrays()
    migration = np.flatnonzero(tr["trigger"] == Trigger.MIGRATION_VOLUNTARY)
    assert migration.size > 0
    for j in migration:
        customer = f"oc_1_{int(tr['tailnet'][j])}"
        day = cal.dates[int(tr["day"][j])]
        same_day = [
            row
            for row in invoice_by_id.values()
            if row["customer_id"] == customer and row["invoice_date"] == day
        ]
        assert len(same_day) == 2
        assert {row["service_period_start"].month for row in same_day} == {
            day.month,
            (day - dt.timedelta(days=1)).month,
        }


@pytest.fixture(scope="module")
def default_orb(tmp_path_factory):
    out = tmp_path_factory.mktemp("default-orb")
    result = run(load_config(ROOT / "config/simulation.yml"), Seeds.load(SEEDS), out, report=False)
    return result, {name: pq.read_table(out / "raw/orb" / f"{name}.parquet") for name in ORB_TABLES}


def test_default_enterprise_annual_cadence_and_runtime(default_orb):
    result, tables = default_orb
    assert result.timings["render Orb billing"] < 60
    sim = result.sim
    invoices = {row["id"]: row for row in tables["invoices"].to_pylist()}
    lines = tables["invoice_line_items"].to_pylist()
    subscription = {row["id"]: row for row in tables["subscriptions"].to_pylist()}
    enterprise_invoices = defaultdict(list)
    for inv in invoices.values():
        if "plan_enterprise_" in subscription[inv["subscription_id"]]["plan_id"]:
            enterprise_invoices[inv["customer_id"]].append(inv)
    checked = 0
    for event in sim.contract_events:
        if event.kind not in ("close", "child", "renewal") or event.term_months < 24:
            continue
        start = sim.cal.dates[event.day]
        anniversary = start.replace(year=start.year + 1)
        if anniversary > sim.config.end_date:
            continue
        earlier_expansions = [
            e
            for e in sim.contract_events
            if e.tailnet == event.tailnet
            and e.kind == "expansion"
            and event.day < e.day < sim.cal.day(anniversary)
        ]
        if earlier_expansions:
            continue
        candidates = [
            inv
            for inv in enterprise_invoices[f"oc_1_{event.tailnet}"]
            if inv["invoice_date"] == anniversary and inv["service_period_start"] == anniversary
        ]
        assert len(candidates) == 1
        invoice = candidates[0]
        fixed = [
            line
            for line in lines
            if line["invoice_id"] == invoice["id"] and line["line_type"] == "fixed"
        ]
        assert len(fixed) == 1
        assert fixed[0]["amount"] == f"{event.recurring_acv:.2f}"
        assert fixed[0]["quantity"] == 1
        assert fixed[0]["end_date"] == anniversary.replace(
            year=anniversary.year + 1
        ) - dt.timedelta(days=1)
        checked += 1
    assert checked > 0
    # Marketplace, multi-currency, and add-ons are disabled in config.
    assert all(inv["status"] in ("issued", "paid") for inv in invoices.values())
    assert all(inv["currency"] == "USD" for inv in invoices.values())
    assert {line["line_type"] for line in lines} <= {"usage", "fixed", "proration", "discount"}


def test_first_day_addition_after_invoice_is_prorated_next_month():
    cal = Calendar(dt.date(2026, 3, 1), dt.date(2026, 8, 31))
    term = _term(cal, "standard", State.STANDARD, 4, dt.date(2026, 6, 1), dt.date(2026, 7, 31))
    b = _fixture_builder([term], [], {})
    day = cal.day(dt.date(2026, 6, 1))
    b.seats[0] = [(day, 30_000, 4, "admin"), (day, 60_000, 5, "admin")]
    actual = _actual(b)
    assert [(d, amount) for d, _, amount, _ in actual] == [
        (dt.date(2026, 6, 1), "32.00"),
        (dt.date(2026, 7, 1), "48.00"),
    ]
    assert [(line[0], line[6]) for line in actual[1][3]] == [
        ("fixed", "40.00"),
        ("proration", "8.00"),
    ]

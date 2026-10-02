"""Stripe collection, the answer key, defect injection, and the DuckDB load (CI config)."""

import json
from decimal import Decimal

import duckdb
import pyarrow.parquet as pq
import pytest

from generator.config import load_config
from generator.load import load
from generator.pipeline import run
from generator.reference import Seeds
from generator.tables import STRIPE_TABLES, TRUTH_TABLES

from .conftest import ROOT, SEEDS

SIX = {"D01", "D03", "D05", "D06", "D09", "D13"}


@pytest.fixture(scope="module")
def ci(tmp_path_factory):
    out = tmp_path_factory.mktemp("ci-full")
    result = run(load_config(ROOT / "config/ci.yml"), Seeds.load(SEEDS), out, report=False)
    con = duckdb.connect()
    for path in sorted((out / "raw").glob("*/*.parquet")) + sorted(
        (out / "answer_key").glob("*/*.parquet")
    ):
        con.execute(
            f"create view {path.parent.name}_{path.stem} as select * from read_parquet('{path}')"
        )
    return result, out, con


def q(con, sql):
    return con.execute(sql).fetchall()


def test_stripe_contracts(ci):
    _, out, _ = ci
    for table in STRIPE_TABLES.values():
        assert pq.read_table(out / "raw/stripe" / f"{table.name}.parquet").schema == table.schema
    for table in TRUTH_TABLES.values():
        path = out / "answer_key/truth" / f"{table.name}.parquet"
        assert pq.read_table(path).schema == table.schema


def test_clean_stripe_invoices_mirror_orb(ci):
    _, _, con = ci
    # Every Orb invoice with a positive total is synced once (ignoring injected D06 copies).
    rows = q(
        con,
        """
        with s as (
            select distinct id, total, json_extract_string(metadata, '$.orb_invoice_id') orb_id,
                   json_extract_string(metadata, '$.payment_source') src
            from stripe_invoice where livemode
              and id not in (select record_key from truth_defect_manifest)
        ), o as (
            select id, max(external_sync_id) sync_id, max(total) total
            from orb_invoices group by id having max(external_sync_id) is not null
        )
        select count(*), count(s.id), sum(case when s.total = cast(o.total as decimal(18,2)) * 100
                                            then 1 else 0 end),
               count(distinct s.src)
        from o left join s on s.orb_id = o.id and s.id = o.sync_id
    """,
    )[0]
    assert rows[0] == rows[1] == rows[2] > 0
    assert rows[3] == 2  # card and ach


def test_every_paid_orb_invoice_has_one_successful_charge(ci):
    _, _, con = ci
    paid, charged = q(
        con,
        """
        with paid as (select distinct external_sync_id id from orb_invoices
                      where status = 'paid' and external_sync_id is not null),
             ok as (select invoice_id, count(distinct id) n from stripe_charge
                    where status = 'succeeded' and not _fivetran_deleted and livemode
                    group by 1)
        select count(*), count(*) filter (where ok.n = 1)
        from paid left join ok on ok.invoice_id = paid.id
    """,
    )[0]
    assert paid == charged > 0
    # Uncollectible Orb credit notes leave their Stripe invoice uncollectible.
    bad = q(
        con,
        """
        select count(*) from orb_credit_notes c join orb_invoices o on o.id = c.invoice_id
        where o.external_sync_id not in (
            select id from stripe_invoice where status = 'uncollectible')
    """,
    )[0][0]
    assert bad == 0


def test_balance_transactions_tie_to_charges_refunds_and_fees(ci):
    _, _, con = ci
    charges, refunds, fees, net = q(
        con,
        """
        with c as (select id, amount, balance_transaction_id from stripe_charge
                   where status = 'succeeded' and not _fivetran_deleted and livemode
                   qualify row_number() over (partition by id order by _fivetran_synced desc) = 1)
        select (select sum(amount) from c),
               (select sum(amount) from stripe_refund where livemode),
               (select sum(fee) from stripe_balance_transaction where livemode),
               (select sum(net) from stripe_balance_transaction where livemode)
    """,
    )[0]
    assert refunds > 0 and fees > 0
    assert charges - refunds - fees == net


def test_manifest_has_only_the_planted_codes_and_each_record_exists(ci):
    _, _, con = ci
    codes = {r[0] for r in q(con, "select distinct defect_code from truth_defect_manifest")}
    assert codes <= SIX
    assert codes >= {"D01", "D03", "D06", "D09", "D13"}
    for table, view in [
        ("stripe.customer", "stripe_customer"), ("stripe.invoice", "stripe_invoice"),
        ("stripe.charge", "stripe_charge"), ("stripe.balance_transaction",
                                             "stripe_balance_transaction"),
        ("salesforce.opportunity", "salesforce_opportunity"), ("app.tailnets", "app_tailnets"),
    ]:  # fmt: skip
        missing = q(
            con,
            f"""
            select count(*) from truth_defect_manifest m
            where source_table = '{table}' and record_key not in (select id from {view})
        """,
        )[0][0]
        assert missing == 0, table
    assert q(
        con,
        """select bool_and(not livemode) from stripe_charge where id in (
        select record_key from truth_defect_manifest where defect_code = 'D13')""",
    )[0][0]
    assert q(
        con,
        """select bool_and(_fivetran_deleted) from stripe_charge where id in (
        select record_key from truth_defect_manifest where defect_code = 'D09')""",
    )[0][0]
    assert q(
        con,
        """select coalesce(bool_and(is_deleted), true) from salesforce_opportunity where id in (
        select record_key from truth_defect_manifest where defect_code = 'D09')""",
    )[0][0]
    # D06 copies carry the original's Orb invoice ID; D01 copies share an email, not metadata.
    assert (
        q(
            con,
            """
        select count(*) from stripe_invoice d join stripe_invoice o
          on json_extract_string(o.metadata, '$.orb_invoice_id')
           = json_extract_string(d.metadata, '$.orb_invoice_id') and o.id <> d.id
        where d.id in (select record_key from truth_defect_manifest where defect_code = 'D06')
    """,
        )[0][0]
        > 0
    )
    assert q(
        con,
        """
        select count(*) = count(o.id) from stripe_customer d
        left join stripe_customer o on o.email = d.email and o.id <> d.id and o.metadata <> '{}'
        where d.id in (select record_key from truth_defect_manifest where defect_code = 'D01')
    """,
    )[0][0]
    internal = q(con, "select count(*) from app_tailnets where signup_domain = 'wirefern.example'"
                 " and _fivetran_active")[0][0]  # fmt: skip
    assert (
        q(con, "select count(*) from truth_defect_manifest where defect_code = 'D03'")[0][0]
        == internal
    )


def test_truth_mrr_matches_independently_rebuilt_source_facts(ci):
    _, _, con = ci
    # v4: seats held at the end of the month's last local day, from raw_app seat events.
    mismatched_seats = q(
        con,
        """
        with t as (select * from truth_truth_mrr_monthly where billing_basis = 'seat'),
        held as (
            select t.tailnet_id, t.month,
                   arg_max(e.seats_held_after, e.occurred_at) seats
            from t join app_seat_events e on e.tailnet_id = t.tailnet_id
             and cast(timezone('America/Los_Angeles', e.occurred_at::timestamptz) as date)
                 < t.month + interval 1 month
            group by all)
        select count(*) from t left join held using (tailnet_id, month)
        where coalesce(held.seats, 0) <> t.quantity
    """,
    )[0][0]
    assert mismatched_seats == 0
    # v3: the Orb usage line and its discount for the service month.
    mismatched_mau = q(
        con,
        """
        with t as (select * from truth_truth_mrr_monthly where billing_basis = 'mau'),
        lines as (
            select c.external_customer_id tailnet_id, u.start_date as month, u.quantity,
                   cast(u.amount as decimal(18,2))
                   + coalesce(sum(cast(d.amount as decimal(18,2))), 0) mrr
            from orb_invoice_line_items u
            join (select distinct id, customer_id from orb_invoices) i on i.id = u.invoice_id
            join (select distinct id, external_customer_id from orb_customers) c
              on c.id = i.customer_id
            left join orb_invoice_line_items d on d.applies_to_line_id = u.id
            where u.line_type = 'usage'
            group by c.external_customer_id, u.start_date, u.quantity, u.amount, u.id)
        select count(*) from t left join lines using (tailnet_id, month)
        where lines.quantity is distinct from t.quantity
           or lines.mrr is distinct from t.mrr_runrate_usd
    """,
    )[0][0]
    assert mismatched_mau == 0
    # Enterprise: the latest won opportunity's recurring ARR / 12.
    mismatched_contracts = q(
        con,
        """
        with t as (select * from truth_truth_mrr_monthly where billing_basis = 'contract'),
        opp as (
            select a.tailnet_id__c tailnet_id, o.close_date, o.recurring_arr__c arr
            from salesforce_opportunity o
            join (select distinct id, tailnet_id__c from salesforce_account
                  where tailnet_id__c is not null) a on a.id = o.account_id
            where o.is_won and not o.is_deleted)
        select count(*) from t
        where t.mrr_runrate_usd <> (
            select round(arg_max(arr, close_date) / 12, 2) from opp
            where opp.tailnet_id = t.tailnet_id and opp.close_date < t.month + interval 1 month)
    """,
    )[0][0]
    assert mismatched_contracts == 0
    assert q(con, "select count(*) filter (where is_internal and mrr_runrate_usd <> 0) "
                  "from truth_truth_mrr_monthly")[0][0] == 0  # fmt: skip


def test_truth_revenue_and_identity(ci):
    result, _, con = ci
    end = result.sim.config.end_date
    recognized = q(
        con,
        f"""
        select sum(cast(recognized_amount as decimal(18,2))) from orb_daily_line_item_revenue
        where revenue_date <= date '{end}' and customer_id like 'oc_1_%'
    """,
    )[0][0]
    truth = q(con, "select sum(recognized_usd), sum(refunds_usd) from truth_truth_revenue_monthly")[
        0
    ]
    assert truth[0] == recognized and truth[1] > 0
    refunds = q(
        con,
        f"""select sum(amount) / 100 from stripe_refund where livemode and
        cast(timezone('America/Los_Angeles', created::timestamptz) as date) <= date '{end}'""",
    )
    assert Decimal(str(refunds[0][0])) == truth[1]
    identity = q(
        con,
        """
        select count(*), count(stripe_customer_id),
               count(*) filter (where stripe_customer_id is not null and stripe_customer_id not in
                                (select id from stripe_customer where metadata <> '{}'))
        from truth_truth_identity""",
    )[0]
    assert identity[0] == q(con, "select count(distinct id) from orb_customers")[0][0]
    assert identity[1] > 0 and identity[2] == 0


def test_loader_creates_raw_schemas(ci, tmp_path):
    _, out, _ = ci
    counts = load(out, tmp_path / "w.duckdb")
    assert {name.split(".")[0] for name in counts} == {
        "raw_app", "raw_orb", "raw_stripe", "raw_salesforce", "raw_truth"
    }  # fmt: skip
    for name, rows in counts.items():
        schema, table = name.split(".")
        root = "answer_key/truth" if schema == "raw_truth" else f"raw/{schema[4:]}"
        assert rows == pq.read_metadata(out / root / f"{table}.parquet").num_rows
    assert json.loads(json.dumps(counts))  # serializable for the CLI report

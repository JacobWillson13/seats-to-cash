"""Defect injection into clean source rows, after the answer key is built (ADR-010).

Every injected record gets a `defect_manifest` row. D03 (internal tailnets) is generated with
the population, so it is only recorded here. D05 moves the load time of some refunds and credit
notes past their period's close. Each defect draws from its own seeded stream over stably
ordered rows.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from generator.billing_stripe import local_date
from generator.ids import make_id
from generator.population import KIND_INTERNAL
from generator.rng import Stream, table_rng

HOUR_US = 3_600_000_000


class Manifest:
    def __init__(self):
        self.rows = []
        self.seq = defaultdict(int)

    def add(self, code, table, key, at, notes):
        self.seq[code] += 1
        self.rows.append(
            {
                "defect_id": f"{code}-{self.seq[code]:05d}",
                "defect_code": code,
                "source_table": table,
                "record_key": key,
                "injected_at_sim": int(at),
                "notes": notes,
            }
        )


def _latest(rows):
    latest = {}
    for row in rows:
        if (
            row["id"] not in latest
            or row["_fivetran_synced"] > latest[row["id"]]["_fivetran_synced"]
        ):
            latest[row["id"]] = row
    return [latest[k] for k in sorted(latest)]


def inject(sim, ids, stripe, sf_rows, manifest: Manifest, orb_rows=None):
    """Mutate `stripe`, `sf_rows`, and `orb_rows` (table -> list of row dicts) in place."""
    seed, rates = sim.config.seed, sim.config.defects
    b, cal = sim.b, sim.cal
    if orb_rows is not None:
        _late_rows(sim, stripe, orb_rows, manifest)

    # D03: internal Wirefern tailnets, billed at a 100% discount.
    for tn in range(b.n):
        if b.kind[tn] == KIND_INTERNAL:
            manifest.add("D03", "app.tailnets", ids[tn], cal.epoch_us(b.created_day[tn], 0),
                         "internal tailnet on wirefern.example")  # fmt: skip

    # D01: a customer re-created in Stripe partway through its history; later invoices and
    # charges point at the duplicate, which has the same email but no metadata.
    invoices_of = defaultdict(list)
    for row in _latest(stripe["invoice"]):
        invoices_of[row["customer_id"]].append(row)
    rng = table_rng(seed, Stream.DEFECTS, "D01")
    customers = sorted(stripe["customer"], key=lambda r: r["id"])
    for customer, u in zip(customers, rng.random(len(customers)), strict=True):
        history = sorted(invoices_of[customer["id"]], key=lambda r: (r["created"], r["id"]))
        if u >= rates.D01_duplicate_stripe_customer or len(history) < 2:
            continue
        split = history[len(history) // 2]
        moved = {
            r["id"] for r in history if (r["created"], r["id"]) >= (split["created"], split["id"])
        }
        dup = make_id(seed, "stripe_dup_customer", customer["id"], "cus_", 24)
        created = split["created"] - HOUR_US
        stripe["customer"].append(
            {**customer, "id": dup, "created": created, "metadata": json.dumps({}),
             "_fivetran_synced": created + 600_000_000}
        )  # fmt: skip
        for table in ("invoice", "charge"):
            for row in stripe[table]:
                key = row["id"] if table == "invoice" else row["invoice_id"]
                if key in moved:
                    row["customer_id"] = dup
        manifest.add("D01", "stripe.customer", dup, created, f"duplicate of {customer['id']}")

    # D06: an invoice synced twice under a second Stripe ID with the same Orb invoice ID.
    rng = table_rng(seed, Stream.DEFECTS, "D06")
    by_id = defaultdict(list)
    for row in stripe["invoice"]:
        by_id[row["id"]].append(row)
    for iid, u in zip(sorted(by_id), rng.random(len(by_id)), strict=True):
        if u >= rates.D06_duplicate_stripe_sync:
            continue
        dup = make_id(seed, "stripe_dup_invoice", iid, "in_", 24)
        for row in by_id[iid]:
            stripe["invoice"].append(
                {**row, "id": dup, "created": row["created"] + 1_000_000, "charge_id": None,
                 "_fivetran_synced": row["_fivetran_synced"] + 1_000_000}
            )  # fmt: skip
        manifest.add("D06", "stripe.invoice", dup, by_id[iid][0]["created"] + 1_000_000,
                     f"duplicate sync of {iid}")  # fmt: skip

    # D09: rows created by mistake and deleted at the source; Fivetran keeps them as deleted.
    rng = table_rng(seed, Stream.DEFECTS, "D09-charge")
    charges = [r for r in _latest(stripe["charge"]) if r["status"] == "succeeded"]
    for charge, u in zip(charges, rng.random(len(charges)), strict=True):
        if u >= rates.D09_soft_deleted_rows:
            continue
        dup = make_id(seed, "stripe_deleted_charge", charge["id"], "ch_", 24)
        at = charge["created"] + HOUR_US
        stripe["charge"].append(
            {**charge, "id": dup, "amount_refunded": 0, "refunded": False,
             "balance_transaction_id": None, "_fivetran_synced": at, "_fivetran_deleted": True}
        )  # fmt: skip
        manifest.add("D09", "stripe.charge", dup, at, f"deleted copy of {charge['id']}")
    rng = table_rng(seed, Stream.DEFECTS, "D09-opportunity")
    opps = [r for r in sorted(_sf_latest(sf_rows["opportunity"]).values(), key=lambda r: r["id"])]
    for n, (opp, u) in enumerate(zip(opps, rng.random(len(opps)), strict=True)):
        if u >= rates.D09_soft_deleted_rows:
            continue
        dup = f"0069{n:011d}"
        at = opp["_fivetran_synced"] + HOUR_US
        sf_rows["opportunity"].append(
            {**opp, "id": dup, "is_deleted": True, "_fivetran_synced": at}
        )
        manifest.add("D09", "salesforce.opportunity", dup, at, f"deleted copy of {opp['id']}")

    # D13: Stripe test-mode activity: a customer, a paid invoice, its charge, and its balance
    # transaction, all with livemode false.
    live = len({r["id"] for r in stripe["invoice"]})
    n_test = max(1, round(live * rates.D13_test_mode_rows)) if rates.D13_test_mode_rows else 0
    rng = table_rng(seed, Stream.DEFECTS, "D13")
    days = rng.integers(cal.day(sim.config.reporting_start_date), cal.n_days, size=n_test)
    amounts = rng.integers(100, 5_000, size=n_test)
    for k in range(n_test):
        at = int(cal.epoch_us(int(days[k]), 50_000))
        cid = make_id(seed, "stripe_test", f"customer{k}", "cus_", 24)
        iid = make_id(seed, "stripe_test", f"invoice{k}", "in_", 24)
        chid = make_id(seed, "stripe_test", f"charge{k}", "ch_", 24)
        bid = make_id(seed, "stripe_test", f"txn{k}", "txn_", 24)
        amount = int(amounts[k])
        sync = {"livemode": False, "_fivetran_synced": at + 600_000_000, "_fivetran_deleted": False}
        stripe["customer"].append(
            {"id": cid, "created": at, "email": f"qa+{k}@wirefern.example", "name": "Test",
             "currency": "usd", "delinquent": False, "description": "test mode",
             "metadata": json.dumps({}), "is_deleted": False, **sync}
        )  # fmt: skip
        stripe["invoice"].append(
            {"id": iid, "customer_id": cid, "number": f"TEST-{k:04d}", "status": "paid",
             "billing_reason": "manual", "collection_method": "charge_automatically",
             "currency": "usd", "subtotal": amount, "tax": 0, "total": amount,
             "amount_due": amount, "amount_paid": amount, "amount_remaining": 0, "created": at,
             "due_date": None, "period_start": at, "period_end": at, "paid": True,
             "charge_id": chid,
             "metadata": json.dumps({"orb_invoice_id": None, "payment_source": "card"}),
             "status_transitions_finalized_at": at, "status_transitions_paid_at": at,
             "status_transitions_marked_uncollectible_at": None, **sync}
        )  # fmt: skip
        stripe["charge"].append(
            {"id": chid, "customer_id": cid, "invoice_id": iid, "amount": amount,
             "amount_refunded": 0, "currency": "usd", "created": at, "status": "succeeded",
             "paid": True, "captured": True, "refunded": False, "failure_code": None,
             "failure_message": None, "payment_method_type": "card",
             "balance_transaction_id": bid, **sync}
        )  # fmt: skip
        stripe["balance_transaction"].append(
            {"id": bid, "source": chid, "type": "charge", "amount": amount, "fee": 0,
             "net": amount, "currency": "usd", "created": at,
             "available_on": cal.dates[int(days[k])], "status": "available", **sync}
        )  # fmt: skip
        for table, key in (
            ("stripe.customer", cid),
            ("stripe.invoice", iid),
            ("stripe.charge", chid),
            ("stripe.balance_transaction", bid),
        ):
            manifest.add("D13", table, key, at, "test-mode row")  # fmt: skip


def _late_rows(sim, stripe, orb_rows, manifest: Manifest):
    """D05: refunds and credit notes that land after their period's close. The business facts
    and their dates stay the same; only the load timestamp moves to `sync.late_row_lag_days`
    after the close date, so a later as-of build restates the closed period."""
    cfg, cal = sim.config, sim.cal
    rate = cfg.defects.D05_late_rows
    lo, hi = cfg.sync.late_row_lag_days
    extract_end = int(cal.epoch_us(cal.day(cfg.extract_date) + 1, 0))

    def late_load(business_day: dt.date, rng) -> int | None:
        period = f"{business_day:%Y-%m}"
        if period not in sim.seeds.close_calendar.close_dates:
            return None  # dated after the last closed period; nothing to land late against
        close = sim.seeds.close_calendar.close_date(period)
        at = int(cal.epoch_us(cal.day(close) + int(rng.integers(lo, hi + 1)), 43_200))
        return at if at < extract_end else None

    rng = table_rng(sim.config.seed, Stream.DEFECTS, "D05-refund")
    refunds = sorted(stripe["refund"], key=lambda r: r["id"])
    for refund, u in zip(refunds, rng.random(len(refunds)), strict=True):
        if u >= rate:
            continue
        at = late_load(local_date(cal, refund["created"]), rng)
        if at is None or at <= refund["_fivetran_synced"]:
            continue
        refund["_fivetran_synced"] = at
        for row in stripe["balance_transaction"]:
            if row["id"] == refund["balance_transaction_id"]:
                row["_fivetran_synced"] = at
        for row in stripe["charge"]:
            if row["id"] == refund["charge_id"] and row["amount_refunded"] > 0:
                row["_fivetran_synced"] = at
        created = local_date(cal, refund["created"])
        manifest.add(
            "D05", "stripe.refund", refund["id"], at, f"refund created {created} loaded late"
        )

    rng = table_rng(sim.config.seed, Stream.DEFECTS, "D05-credit-note")
    notes = sorted(orb_rows["credit_notes"], key=lambda r: r["id"])
    for note, u in zip(notes, rng.random(len(notes)), strict=True):
        if u >= rate:
            continue
        at = late_load(note["effective_date"], rng)
        if at is None or at <= note["_exported_at"]:
            continue
        note["_exported_at"] = at
        manifest.add("D05", "orb.credit_notes", note["id"], at,
                     f"credit note effective {note['effective_date']} exported late")  # fmt: skip


def _sf_latest(rows):
    latest = {}
    for row in rows:
        if (
            row["id"] not in latest
            or row["_fivetran_synced"] > latest[row["id"]]["_fivetran_synced"]
        ):
            latest[row["id"]] = row
    return latest

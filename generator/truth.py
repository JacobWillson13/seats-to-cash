"""The answer key, built from the clean simulation before any defect is injected.

- truth_mrr_monthly: month-end run rate for every business tailnet with a paid subscription
  active on the last day of the month (SPEC §4). v3 uses distinct active users less the free
  units at the retained price; v4 uses seats held at the end of the last day; Enterprise uses the
  latest contract value / 12. Discount lines round exactly as Orb rounds them.
- truth_revenue_monthly: recognized line revenue by service day, less refunds when issued and
  credit notes when effective (ADR-009, ADR-015), for days through end_date.
- truth_identity: the one Orb, Stripe, and Salesforce record behind each tailnet.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from decimal import Decimal

from generator.billing_orb import ZERO, money
from generator.billing_stripe import local_date
from generator.lifecycle import State
from generator.population import KIND_INTERNAL

SELF_SERVE = {State.STARTER, State.STANDARD, State.PREMIUM}


def _month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def _columns(table, rows):
    return {c.name: [row.get(c.name) for row in rows] for c in table.columns}


def render(sim, orb, stripe_rows, sf_tables):
    from generator.tables import TRUTH_TABLES

    cal, b = sim.cal, sim.b
    ids = orb.ids.business_tailnet
    internal = {tn for tn in range(b.n) if b.kind[tn] == KIND_INTERNAL}

    # Billed recurring amounts by tailnet and service-start month, for mrr_billed_usd.
    billed = defaultdict(lambda: ZERO)
    for line in orb.rows["invoice_line_items"]:
        term = orb.term_by_id[line["subscription_id"]]
        if term.domain == 1:
            billed[term.tailnet, _month_start(line["start_date"])] += Decimal(line["amount"])

    contracts = defaultdict(list)
    for e in sorted(sim.contract_events, key=lambda e: (e.day, e.sec)):
        contracts[e.tailnet].append(e)

    mrr_rows = []
    for m in range(len(cal.months)):
        end_day = int(cal.month_end[m])
        month = cal.dates[int(cal.month_start[m])]
        for (domain, tn), terms in orb.by_key.items():
            if domain != 1:
                continue
            term = next(
                (t for t in terms if t.start <= end_day and (t.end is None or t.end >= end_day)),
                None,
            )
            if term is None:
                continue
            price = orb.book.price(term.price_id)
            if term.state == State.ENTERPRISE:
                current = [e for e in contracts[tn] if e.day <= end_day]
                if not current:
                    continue
                quantity = current[-1].seats
                mrr = money(current[-1].recurring_acv / 12)
            else:
                if term.version == 3:
                    quantity = max(0, orb.active_users(tn, m, term) - (price.free_units or 0))
                else:
                    quantity = orb.held_at(tn, end_day, second=86_400)
                amount = money(price.unit_amount("USD") * quantity)
                mrr = amount - (money(amount * term.discount) if term.discount > 0 else ZERO)
            mrr_rows.append(
                {
                    "tailnet_id": ids[tn],
                    "month": month,
                    "plan_code": price.plan_code,
                    "price_version": price.price_version,
                    "billing_basis": price.billing_basis,
                    "quantity": int(quantity),
                    "mrr_runrate_usd": mrr,
                    "mrr_billed_usd": billed[tn, month],
                    "is_internal": tn in internal,
                }
            )

    # Revenue: recognized daily line revenue, refunds when issued, credit notes when effective.
    revenue = defaultdict(lambda: [ZERO, ZERO, ZERO])
    tailnet_of_customer = {}
    for row in orb.rows["customers"]:
        if row["id"].startswith("oc_1_"):
            tailnet_of_customer[row["id"]] = int(row["id"][5:])
    for row in orb.rows["daily_line_item_revenue"]:
        tn = tailnet_of_customer.get(row["customer_id"])
        if tn is not None and row["revenue_date"] <= sim.config.end_date:
            revenue[tn, _month_start(row["revenue_date"])][0] += Decimal(row["recognized_amount"])
    orb_customer_of_invoice = {row["id"]: row["customer_id"] for row in orb.rows["invoices"]}
    orb_invoice_of_stripe = {
        row["id"]: json.loads(row["metadata"])["orb_invoice_id"] for row in stripe_rows["invoice"]
    }
    invoice_of_charge = {row["id"]: row["invoice_id"] for row in stripe_rows["charge"]}
    for row in stripe_rows["refund"]:
        orb_invoice = orb_invoice_of_stripe[invoice_of_charge[row["charge_id"]]]
        tn = tailnet_of_customer[orb_customer_of_invoice[orb_invoice]]
        day = local_date(cal, row["created"])
        if day <= sim.config.end_date:
            revenue[tn, _month_start(day)][1] += Decimal(row["amount"]) / 100
    for row in orb.rows["credit_notes"]:
        tn = tailnet_of_customer[row["customer_id"]]
        if row["effective_date"] <= sim.config.end_date:
            revenue[tn, _month_start(row["effective_date"])][2] += Decimal(row["total"])
    revenue_rows = [
        {
            "tailnet_id": ids[tn],
            "month": month,
            "recognized_usd": rec,
            "refunds_usd": ref,
            "credit_notes_usd": cn,
            "revenue_usd": rec - ref - cn,
            "is_internal": tn in internal,
        }
        for (tn, month), (rec, ref, cn) in revenue.items()
    ]

    accounts = {}
    sf_accounts = sf_tables["account"]
    for account, tailnet in zip(sf_accounts["id"], sf_accounts["tailnet_id__c"], strict=True):
        if tailnet is not None:
            accounts[tailnet] = account
    stripe_of_orb = {
        json.loads(row["metadata"])["orb_customer_id"]: row["id"] for row in stripe_rows["customer"]
    }
    identity_rows = []
    seen = set()
    for row in orb.rows["customers"]:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        tn = tailnet_of_customer.get(row["id"])
        identity_rows.append(
            {
                "tailnet_id": row["external_customer_id"],
                "orb_customer_id": row["id"],
                "stripe_customer_id": stripe_of_orb.get(row["id"]),
                "salesforce_account_id": accounts.get(row["external_customer_id"]),
                "is_internal": tn in internal,
            }
        )

    return {
        "truth_mrr_monthly": _columns(TRUTH_TABLES["truth_mrr_monthly"], mrr_rows),
        "truth_revenue_monthly": _columns(TRUTH_TABLES["truth_revenue_monthly"], revenue_rows),
        "truth_identity": _columns(TRUTH_TABLES["truth_identity"], identity_rows),
    }

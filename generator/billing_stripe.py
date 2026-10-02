"""Stripe source rendering from the Orb invoices and recorded payment outcomes.

Every Orb invoice with a positive total is synced to Stripe (`external_sync_id` is the Stripe
invoice ID) and collected there. Payment failures, recoveries, and uncollectible write-offs
follow the Orb invoice history, which follows the lifecycle; only refunds are drawn here, from
their own seeded stream. Amounts are integer cents. Rows are clean: defects are injected later
by `generator.defects`.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from generator.ids import make_id
from generator.lifecycle import State
from generator.rng import Stream, table_rng
from generator.tables import STRIPE_TABLES

SYNC_LAG_US = 10 * 60 * 1_000_000  # Fivetran lands Stripe rows ten minutes after the event
FINALIZE_LAG_US = 60 * 1_000_000  # Orb syncs a finalized invoice to Stripe a minute after issue
FAIL_LAG_US = 120 * 1_000_000  # the first automatic charge attempt follows finalization


def cents(amount: str | Decimal) -> int:
    return int((Decimal(amount) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def card_fee(amount: int, pct: float, fixed: int) -> int:
    return int((Decimal(amount) * Decimal(str(pct))).to_integral_value(ROUND_HALF_UP)) + fixed


def ach_fee(amount: int, pct: float, cap: int) -> int:
    return min(int((Decimal(amount) * Decimal(str(pct))).to_integral_value(ROUND_HALF_UP)), cap)


def columns(table, rows):
    return {c.name: [row.get(c.name) for row in rows] for c in table.columns}


class StripeBuilder:
    def __init__(self, sim, orb):
        self.sim, self.orb, self.cal = sim, orb, sim.cal
        self.cfg = sim.config
        self.seed = sim.config.seed
        self.rows = {name: [] for name in STRIPE_TABLES}
        self.customer_of_orb: dict[str, str] = {}
        self.extract_end_us = int(self.cal.epoch_us(self.cal.day(self.cfg.extract_date) + 1, 0))

    def _id(self, namespace: str, key: object, prefix: str) -> str:
        return make_id(self.seed, f"stripe_{namespace}", key, prefix, 24)

    def _midnight(self, date: dt.date) -> int:
        return int(self.cal.epoch_us(self.cal.day(date), 0))

    def customer(self, orb_customer: dict, first_seen_us: int) -> str:
        orb_id = orb_customer["id"]
        if orb_id in self.customer_of_orb:
            return self.customer_of_orb[orb_id]
        cid = orb_customer["payment_provider_id"]
        created = first_seen_us - 3_600_000_000  # checkout precedes the first invoice
        self.rows["customer"].append(
            {
                "id": cid,
                "created": created,
                "email": orb_customer["email"],
                "name": orb_customer["name"],
                "currency": "usd",
                "delinquent": False,
                "description": None,
                "metadata": json.dumps(
                    {"tailnet_id": orb_customer["external_customer_id"], "orb_customer_id": orb_id}
                ),
                "is_deleted": False,
                "livemode": True,
                "_fivetran_synced": created + SYNC_LAG_US,
                "_fivetran_deleted": False,
            }
        )
        self.customer_of_orb[orb_id] = cid
        return cid

    def build(self):
        orb = self.orb
        orb_customers = {}
        for row in orb.rows["customers"]:
            orb_customers.setdefault(row["id"], row)
        versions = defaultdict(list)
        for row in orb.rows["invoices"]:
            versions[row["id"]].append(row)
        credit = {row["invoice_id"]: row for row in orb.rows["credit_notes"]}
        pay = self.cfg.payments
        succeeded = []
        for iid, history in versions.items():
            first = history[0]
            if first["external_sync_id"] is None:
                continue  # zero-total invoices (internal tailnets) never reach Stripe
            term = orb.term_by_id[first["subscription_id"]]
            enterprise = term.state == State.ENTERPRISE
            method = "us_bank_account" if enterprise else "card"
            source = "ach" if enterprise else "card"
            customer = self.customer(orb_customers[first["customer_id"]], first["issued_at"])
            total = cents(first["total"])
            finalized = first["issued_at"] + FINALIZE_LAG_US
            paid_row = next((r for r in history if r["status"] == "paid"), None)
            issue_day = self.cal.day(first["invoice_date"])
            failed = ((term.domain, term.tailnet), issue_day) in orb.failures
            sid = first["external_sync_id"]
            base = {
                "id": sid,
                "customer_id": customer,
                "number": first["invoice_number"],
                "billing_reason": "subscription_cycle",
                "collection_method": "send_invoice" if enterprise else "charge_automatically",
                "currency": "usd",
                "subtotal": cents(first["subtotal"]),
                "tax": 0,
                "total": total,
                "amount_due": total,
                "created": finalized,
                "due_date": self._midnight(first["due_date"]) if enterprise else None,
                "period_start": self._midnight(first["service_period_start"]),
                "period_end": self._midnight(first["service_period_end"] + dt.timedelta(days=1)),
                "metadata": json.dumps({"orb_invoice_id": iid, "payment_source": source}),
                "status_transitions_finalized_at": finalized,
                "livemode": True,
                "_fivetran_deleted": False,
            }
            self.rows["invoice"].append(
                {
                    **base,
                    "status": "open",
                    "amount_paid": 0,
                    "amount_remaining": total,
                    "paid": False,
                    "charge_id": None,
                    "status_transitions_paid_at": None,
                    "status_transitions_marked_uncollectible_at": None,
                    "_fivetran_synced": finalized + SYNC_LAG_US,
                }
            )
            if failed:
                at = finalized + FAIL_LAG_US
                self.rows["charge"].append(
                    self._charge(
                        self._id("charge", f"{sid}:fail", "ch_"), customer, sid, total, at,
                        method, status="failed",
                    )
                )  # fmt: skip
            if paid_row is not None:
                at = max(paid_row["paid_at"], finalized + FAIL_LAG_US + 1_000_000)
                charge = self._charge(
                    self._id("charge", f"{sid}:paid", "ch_"), customer, sid, total, at, method,
                    status="succeeded",
                )  # fmt: skip
                self.rows["charge"].append(charge)
                succeeded.append(charge)
                self._balance(charge, enterprise, pay)
                self.rows["invoice"].append(
                    {
                        **base,
                        "status": "paid",
                        "amount_paid": total,
                        "amount_remaining": 0,
                        "paid": True,
                        "charge_id": charge["id"],
                        "status_transitions_paid_at": at,
                        "status_transitions_marked_uncollectible_at": None,
                        "_fivetran_synced": at + SYNC_LAG_US,
                    }
                )
            elif iid in credit:
                at = credit[iid]["created_at"]
                self.rows["invoice"].append(
                    {
                        **base,
                        "status": "uncollectible",
                        "amount_paid": 0,
                        "amount_remaining": total,
                        "paid": False,
                        "charge_id": None,
                        "status_transitions_paid_at": None,
                        "status_transitions_marked_uncollectible_at": at,
                        "_fivetran_synced": at + SYNC_LAG_US,
                    }
                )
        self._refunds(succeeded)
        return self.rows

    def _charge(self, cid, customer, invoice, amount, at, method, *, status):
        ok = status == "succeeded"
        return {
            "id": cid,
            "customer_id": customer,
            "invoice_id": invoice,
            "amount": amount,
            "amount_refunded": 0,
            "currency": "usd",
            "created": at,
            "status": status,
            "paid": ok,
            "captured": ok,
            "refunded": False,
            "failure_code": None if ok else "card_declined",
            "failure_message": None if ok else "Your card was declined.",
            "payment_method_type": method,
            "balance_transaction_id": self._id("txn", cid, "txn_") if ok else None,
            "livemode": True,
            "_fivetran_synced": at + SYNC_LAG_US,
            "_fivetran_deleted": False,
        }

    def _balance(self, charge, ach: bool, pay):
        amount = charge["amount"]
        fee = (
            ach_fee(amount, pay.ach_fee_pct, pay.ach_fee_cap_cents)
            if ach
            else card_fee(amount, pay.card_fee_pct, pay.card_fee_fixed_cents)
        )
        self._bt(charge["balance_transaction_id"], charge["id"], "charge", amount, fee,
                 charge["created"])  # fmt: skip

    def _bt(self, bid, source, kind, amount, fee, created):
        available = local_date(self.cal, created) + dt.timedelta(
            days=self.cfg.payments.payout_lag_days
        )
        self.rows["balance_transaction"].append(
            {
                "id": bid,
                "source": source,
                "type": kind,
                "amount": amount,
                "fee": fee,
                "net": amount - fee,
                "currency": "usd",
                "created": created,
                "available_on": available,
                "status": "available" if available <= self.cfg.extract_date else "pending",
                "livemode": True,
                "_fivetran_synced": created + SYNC_LAG_US,
                "_fivetran_deleted": False,
            }
        )

    def _refunds(self, succeeded):
        """A seeded share of successful charges is refunded, fully or by half, 1 to 20 days
        later. A refund reverses revenue when issued (ADR-009)."""
        rng = table_rng(self.seed, Stream.STRIPE_REFUNDS, "refund")
        draws = rng.random((len(succeeded), 3))
        for charge, (u, half, lag) in zip(succeeded, draws, strict=True):
            if u >= self.cfg.payments.refund_rate:
                continue
            amount = charge["amount"] // 2 if half < 0.5 else charge["amount"]
            created = charge["created"] + (1 + int(lag * 20)) * 86_400_000_000
            if created >= self.extract_end_us or amount <= 0:
                continue
            rid = self._id("refund", charge["id"], "re_")
            bid = self._id("txn", rid, "txn_")
            self.rows["refund"].append(
                {
                    "id": rid,
                    "charge_id": charge["id"],
                    "amount": amount,
                    "currency": "usd",
                    "created": created,
                    "reason": "requested_by_customer",
                    "status": "succeeded",
                    "balance_transaction_id": bid,
                    "livemode": True,
                    "_fivetran_synced": created + SYNC_LAG_US,
                    "_fivetran_deleted": False,
                }
            )
            self._bt(bid, rid, "refund", -amount, 0, created)
            self.rows["charge"].append(
                {
                    **charge,
                    "amount_refunded": amount,
                    "refunded": amount == charge["amount"],
                    "_fivetran_synced": created + SYNC_LAG_US,
                }
            )


def local_date(cal, ts_us: int) -> dt.date:
    """The reporting-time-zone date of a UTC microsecond timestamp."""
    guess = cal.start + dt.timedelta(days=int((ts_us - int(cal.epoch_us(0, 0))) // 86_400_000_000))
    while int(cal.epoch_us(cal.day(guess), 0)) > ts_us:
        guess -= dt.timedelta(days=1)
    while int(cal.epoch_us(cal.day(guess) + 1, 0)) <= ts_us:
        guess += dt.timedelta(days=1)
    return guess

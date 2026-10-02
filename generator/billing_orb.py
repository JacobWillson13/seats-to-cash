"""Orb source rendering from recorded lifecycle, seat, activity, and contract facts.

Every amount is a local-currency Decimal rounded half up per line. No lifecycle outcome is
sampled here: payment failures, recovery, and uncollectible credits follow transition facts.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from generator.app_db import Ids
from generator.clock import add_months
from generator.lifecycle import State, Trigger
from generator.population import CURRENCIES, KIND_DIRECT, KIND_INTERNAL
from generator.rng import Stream, entity_rng
from generator.seats import ACTORS
from generator.tables import ORB_TABLES

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PAID = {State.PERSONAL_PLUS, State.STARTER, State.STANDARD, State.PREMIUM, State.ENTERPRISE}
SELF_SERVE = {State.STARTER, State.STANDARD, State.PREMIUM}
COUNTRIES = ("US", "DE", "GB")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def decimal(value: Decimal) -> str:
    return f"{money(value):.2f}"


def prorate(unit: Decimal, quantity: int, days: int, month_days: int) -> Decimal:
    return money(unit * quantity * Decimal(days) / Decimal(month_days))


def allocate_daily(amount: Decimal, start: dt.date, end: dt.date):
    """Put the rounded daily residual on the last service day."""
    n = (end - start).days + 1
    regular = money(amount / n)
    for offset in range(n):
        yield (
            start + dt.timedelta(days=offset),
            regular if offset < n - 1 else amount - regular * (n - 1),
        )


def _date(cal, day):
    return cal.start + dt.timedelta(days=int(day))


def _columns(table, rows):
    return {c.name: [row.get(c.name) for row in rows] for c in table.columns}


@dataclass
class Term:
    id: str
    domain: int
    tailnet: int
    state: State
    version: int
    start: int
    sec: int
    end: int | None
    end_sec: int | None
    end_reason: str | None
    price_id: str
    customer_id: str
    currency: str
    channel: str
    discount: Decimal


def _terms(sim, ids):
    tr = sim.transitions.arrays()
    indices = sorted(
        range(len(tr["day"])),
        key=lambda j: (
            int(tr["domain"][j]),
            int(tr["tailnet"][j]),
            int(tr["day"][j]),
            int(tr["sec"][j]),
            j,
        ),
    )
    by_tn = defaultdict(list)
    for j in indices:
        by_tn[int(tr["domain"][j]), int(tr["tailnet"][j])].append(j)
    all_terms = []
    by_key = defaultdict(list)
    for (domain, tailnet), changes in by_tn.items():
        current = None
        for j in changes:
            trigger = Trigger(int(tr["trigger"][j]))
            target = State(int(tr["to_state"][j]))
            version = int(tr["to_version"][j])
            day, sec = int(tr["day"][j]), int(tr["sec"][j])
            # Past-due and recovery retain the same subscription and its fixed price.
            if trigger in (
                Trigger.PAYMENT_FAILED,
                Trigger.PAYMENT_RECOVERED,
                Trigger.ENTERPRISE_EXPANSION,
            ):
                continue
            if target in PAID and trigger not in (Trigger.ENTERPRISE_RENEWAL,) and current:
                if current.state == target and current.version == version:
                    continue
            if current is not None:
                current.end = day - 1
                current.end_sec = sec
                current.end_reason = {
                    Trigger.CHURN_VOLUNTARY: "voluntary",
                    Trigger.DUNNING_EXPIRED: "involuntary",
                    Trigger.MIGRATION_VOLUNTARY: "migrated",
                    Trigger.MIGRATION_FORCED: "migrated",
                    Trigger.ENTERPRISE_NONRENEWAL: "voluntary",
                }.get(trigger, "replaced")
                current = None
            if target not in PAID:
                continue
            code = sim.plan_codes[int(tr["to_plan"][j])]
            price = sim.seeds.price_book.plan_version_price(code, f"v{version}")
            currency = (
                CURRENCIES[int(sim.b.currency[tailnet])]
                if domain
                else CURRENCIES[int(sim.pop.personal.currency[tailnet])]
            )
            channel = "stripe"
            if target == State.ENTERPRISE:
                channel = ("stripe", "aws_marketplace", "azure_marketplace")[
                    int(sim.b.channel[tailnet])
                ]
            discount = ZERO
            if domain and sim.b.kind[tailnet] == KIND_INTERNAL:
                discount = sim.seeds.price_book.price("disc_internal").discount_pct
            elif domain and sim.b.nonprofit[tailnet]:
                discount = sim.seeds.price_book.price("disc_nonprofit").discount_pct
            identifier = f"sub_{domain}_{tailnet}_{len(by_key[domain, tailnet]):03d}"
            customer_id = f"oc_{domain}_{tailnet}"
            current = Term(
                identifier,
                domain,
                tailnet,
                target,
                version,
                day,
                sec,
                None,
                None,
                None,
                price.price_id,
                customer_id,
                currency,
                channel,
                discount,
            )
            all_terms.append(current)
            by_key[domain, tailnet].append(current)
    return all_terms, by_key


class Builder:
    def __init__(self, sim, personal):
        self.sim, self.personal = sim, personal
        self.cal = sim.cal
        self.ids = Ids(sim)
        self.book = sim.seeds.price_book
        self.rows = {name: [] for name in ORB_TABLES}
        self.terms, self.by_key = _terms(sim, self.ids)
        self.term_by_id = {term.id: term for term in self.terms}
        self.lines_of = defaultdict(list)
        self.invoice_latest = {}
        self.invoice_seq = 0
        self.line_seq = 0
        discounts = [price for price in self.book if price.billing_basis == "discount"]
        self.discount_price = {
            "nonprofit": min(discounts, key=lambda price: price.discount_pct),
            "internal": max(discounts, key=lambda price: price.discount_pct),
        }
        self.failures = set()
        self.recoveries = defaultdict(list)
        self.expirations = defaultdict(list)
        tr = sim.transitions.arrays()
        for domain, tn, day, trig in zip(
            tr["domain"], tr["tailnet"], tr["day"], tr["trigger"], strict=True
        ):
            key = (int(domain), int(tn))
            if trig == Trigger.PAYMENT_FAILED:
                self.failures.add((key, int(day)))
            elif trig == Trigger.PAYMENT_RECOVERED:
                self.recoveries[key].append(int(day))
            elif trig == Trigger.DUNNING_EXPIRED:
                self.expirations[key].append(int(day))
        self.seats = defaultdict(list)
        events = sim.seat_events.arrays()
        for j in sorted(
            range(len(events["day"])),
            key=lambda x: (
                int(events["tailnet"][x]),
                int(events["day"][x]),
                int(events["sec"][x]),
                x,
            ),
        ):
            self.seats[int(events["tailnet"][j])].append(
                (
                    int(events["day"][j]),
                    int(events["sec"][j]),
                    int(events["held"][j]),
                    ACTORS[int(events["actor"][j])],
                )
            )
        # (tailnet, month) -> {user: latest logged active day}; a user can be logged twice in
        # the month a trial converts (before and after the conversion).
        self.mau = defaultdict(dict)
        first = sim.mau.arrays()
        for user, day in zip(first["user"], first["day"], strict=True):
            tailnet = int(sim.users.tailnet[user])
            month = int(self.cal.month_of[day])
            seen = self.mau[tailnet, month]
            seen[int(user)] = max(seen.get(int(user), -1), int(day))
        self.personal_devices = {
            (int(t), int(m)): int(n)
            for t, m, n in zip(personal.tailnet, personal.month, personal.user_devices, strict=True)
        }
        self.business_devices = {}
        activity = sim.activity.arrays()
        for tn, day, n in zip(
            activity["tailnet"], activity["day"], activity["user_devices"], strict=True
        ):
            self.business_devices[int(tn), int(self.cal.month_of[day])] = int(n)
        self.mullvad = {}
        for term in self.terms:
            key = (term.domain, term.tailnet)
            if key not in self.mullvad:
                self.mullvad[key] = (
                    entity_rng(sim.config.seed, Stream.MULLVAD_ATTACH, *key).random()
                    < sim.config.addons.mullvad_attach_rate
                )

    def active_users(self, tailnet, month, term) -> int:
        """Distinct users active in the month on or after the term's start: trial days before
        a mid-month conversion are never billed."""
        return sum(1 for day in self.mau[tailnet, month].values() if day >= term.start)

    def usage_start(self, month, term):
        return self.cal.dates[max(int(self.cal.month_start[month]), term.start)]

    def ts(self, day, second=39_600):
        return int(self.cal.epoch_us(day, second))

    def export(self, ts):
        # Fixed one-hour export lag; safely within the configured 1–24 hour window.
        return ts + 3_600_000_000

    def price_key(self, price_id, currency):
        return f"op_{price_id}_{currency.lower()}"

    def catalog(self):
        catalog = {}
        for price in self.book:
            for currency in self.book.currencies:
                key = (price.plan_code, price.price_version, currency)
                plan_id = f"plan_{price.plan_code}_{price.price_version}_{currency.lower()}"
                created_day = max(0, self.cal.day(price.valid_from))
                start = self.ts(created_day, 0)
                if key not in catalog:
                    self.rows["plans"].append(
                        {
                            "id": plan_id,
                            "external_plan_id": price.plan_code,
                            "name": price.plan_name,
                            "price_version": price.price_version,
                            "currency": currency,
                            "created_at": start,
                            "_exported_at": self.export(start),
                        }
                    )
                    catalog[key] = True
                self.rows["prices"].append(
                    {
                        "id": self.price_key(price.price_id, currency),
                        "plan_id": plan_id,
                        "external_price_id": price.price_id,
                        "item_name": price.item,
                        "model_type": {"package": "package", "flat": "flat"}.get(
                            price.billing_basis, "unit"
                        ),
                        "unit_amount": decimal(price.unit_amount(currency))
                        if price.unit_amounts
                        else None,
                        "package_size": price.package_size,
                        "cadence": price.cadence,
                        "billing_timing": price.billing_timing,
                        "_exported_at": self.export(start),
                    }
                )

    def customers(self):
        for domain, count in ((0, len(self.sim.pop.personal.created_day)), (1, self.sim.b.n)):
            for tn in range(count):
                if domain:
                    day, sec = int(self.sim.b.created_day[tn]), int(self.sim.b.created_sec[tn])
                    if day < 0 or day >= self.cal.n_days:
                        continue  # direct prospect not yet a customer
                    company = int(self.sim.b.company[tn])
                    name = self.sim.pop.company_name[company]
                    email = f"billing@{self.sim.pop.company_domain[company]}"
                    currency = CURRENCIES[int(self.sim.b.currency[tn])]
                    provider = (
                        None
                        if int(self.sim.b.kind[tn]) == KIND_DIRECT
                        and int(self.sim.b.channel[tn]) in (1, 2)
                        else "stripe"
                    )
                    external = self.ids.business_tailnet[tn]
                else:
                    day = int(self.sim.pop.personal.created_day[tn])
                    sec = int(self.sim.pop.personal.created_sec[tn])
                    name = f"Personal {tn}"
                    email = self.sim.pop.people.personal_email[
                        int(self.sim.pop.personal.creator[tn])
                    ]
                    currency = CURRENCIES[int(self.sim.pop.personal.currency[tn])]
                    provider = "stripe"
                    external = self.ids.personal_tailnet[tn]
                issued = self.ts(day, sec)
                customer = {
                    "id": f"oc_{domain}_{tn}",
                    "external_customer_id": external,
                    "name": name,
                    "email": email,
                    "currency": currency,
                    "payment_provider": provider,
                    "payment_provider_id": f"cus_{domain}_{tn}" if provider else None,
                    "billing_country": COUNTRIES[CURRENCIES.index(currency)],
                    "created_at": issued,
                    "metadata": json.dumps({"tailnet_id": external}),
                    "_exported_at": self.export(issued),
                }
                self.rows["customers"].append(customer)
                if domain and provider and int(self.sim.b.channel[tn]) in (1, 2):
                    close = next(
                        (
                            e
                            for e in self.sim.contract_events
                            if e.tailnet == tn and e.kind in ("close", "child")
                        ),
                        None,
                    )
                    if close is not None:
                        changed = self.ts(close.day, close.sec)
                        self.rows["customers"].append(
                            {
                                **customer,
                                "payment_provider": None,
                                "payment_provider_id": None,
                                "_exported_at": max(self.export(changed), self.export(issued) + 1),
                            }
                        )

    def subscriptions(self):
        for term in self.terms:
            price = self.book.price(term.price_id)
            created = self.ts(term.start, term.sec)
            base = {
                "id": term.id,
                "customer_id": term.customer_id,
                "plan_id": f"plan_{price.plan_code}_{price.price_version}_{term.currency.lower()}",
                "start_date": _date(self.cal, term.start),
                "net_terms": 30 if term.state == State.ENTERPRISE else 0,
                "invoicing_channel": term.channel,
                "discount_pct": decimal(term.discount),
                "created_at": created,
            }
            self.rows["subscriptions"].append(
                {
                    **base,
                    "status": "active",
                    "end_date": None,
                    "ended_reason": None,
                    "_exported_at": self.export(created),
                }
            )
            if term.end is not None:
                ended = self.ts(term.end + 1, term.end_sec or 70_000)
                self.rows["subscriptions"].append(
                    {
                        **base,
                        "status": "ended",
                        "end_date": _date(self.cal, term.end),
                        "ended_reason": term.end_reason,
                        "_exported_at": max(self.export(ended), self.export(created) + 1),
                    }
                )

    def term_on(self, domain, tn, day):
        for term in reversed(self.by_key[domain, tn]):
            if term.start <= day and (term.end is None or day <= term.end):
                return term
        return None

    def held_at(self, tn, day, *, second=39_600):
        held = 0
        for d, sec, n, _ in self.seats[tn]:
            if d > day or (d == day and sec > second):
                break
            held = n
        return held

    def quantity_changes(self):
        for term in self.terms:
            if term.domain != 1 or term.version != 4 or term.state not in SELF_SERVE:
                continue
            for j, (day, sec, held, actor) in enumerate(self.seats[term.tailnet]):
                if day < term.start or (term.end is not None and day > term.end):
                    continue
                recorded = self.ts(day, sec)
                self.rows["subscription_quantity_changes"].append(
                    {
                        "id": f"sq_{term.id}_{j}",
                        "subscription_id": term.id,
                        "price_id": self.price_key(term.price_id, term.currency),
                        "effective_date": _date(self.cal, day),
                        "quantity": held,
                        "source": "auto_seat" if actor == "system" and j else actor,
                        "recorded_at": recorded,
                        "_exported_at": self.export(recorded),
                    }
                )
        for event in self.sim.contract_events:
            if event.kind not in ("close", "child", "renewal", "expansion"):
                continue
            term = self.term_on(1, event.tailnet, event.day)
            if term is None:
                continue
            recorded = self.ts(event.day, event.sec)
            self.rows["subscription_quantity_changes"].append(
                {
                    "id": f"sq_contract_{event.tailnet}_{event.day}_{event.kind}",
                    "subscription_id": term.id,
                    "price_id": self.price_key(term.price_id, event.currency),
                    "effective_date": _date(self.cal, event.day),
                    "quantity": event.seats,
                    "source": "sales",
                    "recorded_at": recorded,
                    "_exported_at": self.export(recorded),
                }
            )

    def invoice(self, term, issue_day, service_start, service_end, lines):
        if not lines:
            return None
        issue_date = _date(self.cal, issue_day)
        if issue_date > self.sim.config.extract_date:
            return None
        self.invoice_seq += 1
        iid = f"orb_inv_{self.invoice_seq:08d}"
        issued = self.ts(
            issue_day, max(39_600, term.sec + 1) if issue_day == term.start else 39_600
        )
        subtotal = sum((item[5] for item in lines), ZERO)
        discount_total = -sum((item[5] for item in lines if item[0] == "discount"), ZERO)
        external = term.channel != "stripe"
        base = {
            "id": iid,
            "invoice_number": f"WF-{self.invoice_seq:08d}",
            "customer_id": term.customer_id,
            "subscription_id": term.id,
            "currency": term.currency,
            "invoice_date": issue_date,
            "issued_at": issued,
            "service_period_start": service_start,
            "service_period_end": service_end,
            "due_date": issue_date + dt.timedelta(days=30 if term.state == State.ENTERPRISE else 0),
            "voided_at": None,
            "subtotal": decimal(subtotal),
            "discount_total": decimal(discount_total),
            "tax": decimal(ZERO),
            "total": decimal(subtotal),
            "external_sync_id": (
                None if external or subtotal <= 0 else f"in_{self.invoice_seq:08d}"
            ),
        }
        unpaid = ((term.domain, term.tailnet), issue_day) in self.failures and subtotal > 0
        first = {
            **base,
            "status": "external" if external else "issued",
            "paid_at": None,
            "amount_due": decimal(subtotal),
            "_exported_at": self.export(issued),
        }
        self.rows["invoices"].append(first)
        self.invoice_latest[iid] = first
        last_positive = None
        for line_type, price_id, name, start, end, amount, qty, unit, linked in lines:
            self.line_seq += 1
            lid = f"orb_line_{self.line_seq:09d}"
            row = {
                "id": lid,
                "invoice_id": iid,
                "subscription_id": term.id,
                "price_id": self.price_key(price_id, term.currency),
                "line_type": line_type,
                "applies_to_line_id": last_positive if line_type == "discount" else linked,
                "name": name,
                "start_date": start,
                "end_date": end,
                "quantity": qty,
                "unit_amount": decimal(unit),
                "amount": decimal(amount),
                "_exported_at": self.export(issued),
            }
            self.rows["invoice_line_items"].append(row)
            self.lines_of[iid].append(row)
            if line_type != "discount":
                last_positive = lid
            revenue_dates = (
                [(end, amount)] if line_type == "one_time" else allocate_daily(amount, start, end)
            )
            for revenue_date, daily_amount in revenue_dates:
                self.rows["daily_line_item_revenue"].append(
                    {
                        "revenue_date": revenue_date,
                        "invoice_line_item_id": lid,
                        "invoice_id": iid,
                        "customer_id": term.customer_id,
                        "price_id": row["price_id"],
                        "recognized_amount": decimal(daily_amount),
                        "currency": term.currency,
                        "_exported_at": self.export(issued),
                    }
                )
        if not external and not unpaid:
            paid_day = min(issue_day + 1, self.cal.n_days - 1)
            paid = self.ts(paid_day, 54_000)
            if paid <= issued:
                paid = issued + 1_000_000
            version = {
                **base,
                "status": "paid",
                "paid_at": paid,
                "amount_due": decimal(ZERO),
                "_exported_at": max(self.export(paid), self.export(issued) + 1),
            }
            self.rows["invoices"].append(version)
            self.invoice_latest[iid] = version
        return iid

    def positive_line(self, term, line_type, price, start, end, qty, amount, *, name=None):
        unit = price.unit_amount(term.currency) if price.unit_amounts else amount
        return (
            line_type,
            price.price_id,
            name or price.plan_name,
            start,
            end,
            amount,
            qty,
            unit,
            None,
        )

    def discount_line(self, term, positive):
        if term.discount <= 0:
            return None
        kind = (
            "internal"
            if term.domain and self.sim.b.kind[term.tailnet] == KIND_INTERNAL
            else "nonprofit"
        )
        price = self.discount_price[kind]
        amount = -money(positive[5] * term.discount)
        return (
            "discount",
            price.price_id,
            price.plan_name,
            positive[3],
            positive[4],
            amount,
            1,
            amount,
            None,
        )

    def addons(self, term, month, start, end):
        lines = []
        if term.domain and term.version == 4 and term.state in SELF_SERVE:
            price = next(p for p in self.book if p.item == "tagged_resource")
            n = max(0, int(self.sim.b.tagged_resources[term.tailnet]) - (price.free_units or 0))
            if n:
                amount = money(price.unit_amount(term.currency) * n)
                lines.append(self.positive_line(term, "addon", price, start, end, n, amount))
        if self.mullvad[term.domain, term.tailnet]:
            device_month = month if term.version == 3 and term.state in SELF_SERVE else month - 1
            devices = (self.business_devices if term.domain else self.personal_devices).get(
                (term.tailnet, device_month), 0
            )
            price = next(p for p in self.book if p.billing_basis == "package")
            packages = (devices + (price.package_size or 5) - 1) // (price.package_size or 5)
            if packages:
                amount = money(price.unit_amount(term.currency) * packages)
                lines.append(self.positive_line(term, "addon", price, start, end, packages, amount))
        return lines

    def self_serve_invoices(self):
        cal = self.cal
        for (_domain, tailnet), terms in self.by_key.items():
            if not terms or all(t.state == State.ENTERPRISE for t in terms):
                continue
            for month in range(len(cal.months)):
                start_day, end_day = int(cal.month_start[month]), int(cal.month_end[month])
                start, end = cal.dates[start_day], cal.dates[end_day]
                active = [
                    t
                    for t in terms
                    if t.state != State.ENTERPRISE
                    and t.start <= end_day
                    and (t.end is None or t.end >= start_day)
                ]
                if not active:
                    continue
                # v3 MAU uses the last legacy tier held in the service month.
                legacy = [t for t in active if t.version == 3 and t.state in SELF_SERVE]
                if legacy:
                    term = legacy[-1]
                    issue = end_day + 1
                    price = self.book.price(term.price_id)
                    count = max(
                        0, self.active_users(tailnet, month, term) - (price.free_units or 0)
                    )
                    amount = money(price.unit_amount(term.currency) * count)
                    service_start = self.usage_start(month, term)
                    base = self.positive_line(
                        term, "usage", price, service_start, end, count, amount
                    )
                    lines = [base]
                    if disc := self.discount_line(term, base):
                        lines.append(disc)
                    lines += self.addons(term, month, service_start, end)
                    self.invoice(term, issue, service_start, end, lines)
                plus = [t for t in active if t.state == State.PERSONAL_PLUS]
                if plus:
                    term = plus[0]
                    issue = max(start_day, term.start)
                    service_start = cal.dates[issue]
                    price = self.book.price(term.price_id)
                    days = (end - service_start).days + 1
                    amount = prorate(
                        price.unit_amount(term.currency), 1, days, (end - start).days + 1
                    )
                    base = self.positive_line(term, "fixed", price, service_start, end, 1, amount)
                    lines = [base]
                    if disc := self.discount_line(term, base):
                        lines.append(disc)
                    lines += self.addons(term, month, service_start, end)
                    self.invoice(term, issue, service_start, end, lines)
                seat_terms = [t for t in active if t.version == 4 and t.state in SELF_SERVE]
                if seat_terms:
                    term = next(
                        (
                            t
                            for t in seat_terms
                            if t.start <= start_day and (t.end is None or t.end >= start_day)
                        ),
                        seat_terms[0],
                    )
                    issue = max(start_day, term.start)
                    service_start = cal.dates[issue]
                    price = self.book.price(term.price_id)
                    held = self.held_at(
                        tailnet,
                        issue,
                        second=max(39_600, term.sec) if issue == term.start else 39_600,
                    )
                    fraction_days = (end - service_start).days + 1
                    amount = prorate(
                        price.unit_amount(term.currency),
                        held,
                        fraction_days,
                        (end - start).days + 1,
                    )
                    base = self.positive_line(
                        term, "fixed", price, service_start, end, held, amount
                    )
                    lines = [base]
                    if disc := self.discount_line(term, base):
                        lines.append(disc)
                    # Prior month's held-seat additions are billed on this invoice.
                    if month:
                        prior_start, prior_end = (
                            int(cal.month_start[month - 1]),
                            int(cal.month_end[month - 1]),
                        )
                        prior_days = prior_end - prior_start + 1
                        prior_term = self.term_on(1, tailnet, prior_start)
                        prior_paid = (
                            prior_term is not None
                            and prior_term.version == 4
                            and prior_term.state in SELF_SERVE
                        )
                        baseline_day = prior_start if prior_paid else term.start
                        baseline_sec = 39_600 if prior_paid else max(39_600, term.sec)
                        prior_price = self.book.price(
                            prior_term.price_id if prior_paid else term.price_id
                        )
                        previous_held = 0
                        for day, sec, after, _ in self.seats[tailnet]:
                            if day < prior_start:
                                previous_held = after
                                continue
                            if day > prior_end:
                                break
                            delta = max(0, after - previous_held)
                            previous_held = after
                            if delta == 0 or (day, sec) <= (baseline_day, baseline_sec):
                                continue
                            service_date = cal.dates[day]
                            prorated = prorate(
                                prior_price.unit_amount(term.currency),
                                delta,
                                prior_end - day + 1,
                                prior_days,
                            )
                            line = self.positive_line(
                                term,
                                "proration",
                                prior_price,
                                service_date,
                                cal.dates[prior_end],
                                delta,
                                prorated,
                            )
                            lines.append(line)
                            if disc := self.discount_line(term, line):
                                lines.append(disc)
                    lines += self.addons(term, month, service_start, end)
                    self.invoice(term, issue, service_start, end, lines)
            # September additions must still bill on October 1 without October service.
            last = terms[-1]
            if last.domain == 1 and last.version == 4 and last.state in SELF_SERVE:
                month = len(cal.months) - 1
                prior_start, prior_end = int(cal.month_start[month]), int(cal.month_end[month])
                prior_term = self.term_on(1, tailnet, prior_start)
                prior_paid = (
                    prior_term is not None
                    and prior_term.version == 4
                    and prior_term.state in SELF_SERVE
                )
                baseline_day = prior_start if prior_paid else last.start
                baseline_sec = 39_600 if prior_paid else max(39_600, last.sec)
                held = 0
                lines = []
                price = self.book.price(prior_term.price_id if prior_paid else last.price_id)
                for day, sec, after, _ in self.seats[tailnet]:
                    if day < prior_start:
                        held = after
                        continue
                    if day > prior_end:
                        break
                    delta = max(0, after - held)
                    held = after
                    if not delta or (day, sec) <= (baseline_day, baseline_sec):
                        continue
                    amount = prorate(
                        price.unit_amount(last.currency),
                        delta,
                        prior_end - day + 1,
                        prior_end - prior_start + 1,
                    )
                    line = self.positive_line(
                        last,
                        "proration",
                        price,
                        cal.dates[day],
                        cal.dates[prior_end],
                        delta,
                        amount,
                    )
                    lines.append(line)
                    if disc := self.discount_line(last, line):
                        lines.append(disc)
                if lines:
                    self.invoice(
                        last, prior_end + 1, cal.dates[prior_start], cal.dates[prior_end], lines
                    )

    def enterprise_invoices(self):
        events = sorted(self.sim.contract_events, key=lambda e: (e.day, e.sec, e.tailnet))
        by_tn = defaultdict(list)
        for e in events:
            by_tn[e.tailnet].append(e)
        for tailnet, history in by_tn.items():
            terms = [t for t in self.by_key[1, tailnet] if t.state == State.ENTERPRISE]
            for term in terms:
                starts = [
                    e
                    for e in history
                    if e.kind in ("close", "child", "renewal") and e.day == term.start
                ]
                if not starts:
                    continue
                event = starts[-1]
                anniversary = cal_date = self.cal.dates[event.day]
                while (
                    self.cal.day(anniversary) < self.cal.n_days
                    and self.cal.day(anniversary) < event.contract_end_day
                ):
                    issue = self.cal.day(anniversary)
                    next_anniversary = add_months(anniversary, 12)
                    service_end = min(
                        next_anniversary - dt.timedelta(days=1),
                        _date(self.cal, event.contract_end_day - 1),
                    )
                    if term.end is not None:
                        service_end = min(service_end, _date(self.cal, term.end))
                    if service_end < anniversary:
                        break
                    current = next(
                        (
                            e
                            for e in reversed(history)
                            if e.day <= issue and e.contract_start_day == event.contract_start_day
                        ),
                        event,
                    )
                    price = self.book.price(term.price_id)
                    amount = current.recurring_acv
                    line = self.positive_line(
                        term,
                        "fixed",
                        price,
                        anniversary,
                        service_end,
                        1,
                        amount,
                        name="Enterprise annual contract",
                    )
                    lines = [line]
                    if anniversary == cal_date and event.services_amount:
                        service_price = next(p for p in self.book if p.billing_basis == "one_time")
                        delivered = _date(self.cal, event.services_delivery_day)
                        lines.append(
                            self.positive_line(
                                term,
                                "one_time",
                                service_price,
                                anniversary,
                                delivered,
                                1,
                                event.services_amount,
                                name="Professional services",
                            )
                        )
                    self.invoice(term, issue, anniversary, service_end, lines)
                    anniversary = next_anniversary
            for event in history:
                if event.kind != "expansion":
                    continue
                term = self.term_on(1, tailnet, event.day)
                if term is None:
                    continue
                prior = next(
                    (
                        e
                        for e in reversed(history)
                        if e.day < event.day
                        and e.kind in ("close", "child", "renewal", "expansion")
                    ),
                    None,
                )
                if prior is None:
                    continue
                delta = max(ZERO, event.recurring_acv - prior.recurring_acv)
                if not delta:
                    continue
                start = self.cal.dates[event.day]
                anniversary = add_months(self.cal.dates[event.contract_start_day], 12)
                while anniversary <= start:
                    anniversary = add_months(anniversary, 12)
                end = anniversary - dt.timedelta(days=1)
                year_days = (anniversary - add_months(anniversary, -12)).days
                amount = prorate(delta, 1, (end - start).days + 1, year_days)
                price = self.book.price(term.price_id)
                line = self.positive_line(
                    term,
                    "proration",
                    price,
                    start,
                    end,
                    1,
                    amount,
                    name="Enterprise expansion",
                )
                self.invoice(term, event.day, start, end, [line])

    def usage_events(self):
        arr = self.sim.mau.arrays()
        latest = {}
        for user, day in zip(arr["user"], arr["day"], strict=True):
            tn = int(self.sim.users.tailnet[user])
            month = int(self.cal.month_of[day])
            latest[tn, month, int(user)] = max(latest.get((tn, month, int(user)), -1), int(day))
        for (tn, month, user), day in latest.items():
            start, end = int(self.cal.month_start[month]), int(self.cal.month_end[month])
            if not any(
                t.version == 3
                and t.state in SELF_SERVE
                and max(t.start, start) <= day <= end
                and (t.end is None or t.end >= start)
                for t in self.by_key[1, tn]
            ):
                continue
            external = self.ids.business_tailnet[tn]
            key = f"{external}:{self.cal.months[month]}:{self.ids.business_user[user]}"
            recorded = self.ts(int(day), 50_000)
            self.rows["events"].append(
                {
                    "id": f"evt_{tn}_{month}_{int(user)}",
                    "idempotency_key": key,
                    "event_name": "user_active",
                    "external_customer_id": external,
                    "timestamp": recorded,
                    "properties": json.dumps({"user_id": self.ids.business_user[user]}),
                    "_exported_at": self.export(recorded),
                }
            )

    def payment_history(self):
        by_customer_date = defaultdict(list)
        for iid, row in self.invoice_latest.items():
            term = self.term_by_id[row["subscription_id"]]
            by_customer_date[(term.domain, term.tailnet, self.cal.day(row["invoice_date"]))].append(
                iid
            )
        for key, failed_day in sorted(self.failures):
            invoices = by_customer_date[key[0], key[1], failed_day]
            unpaid = [
                iid
                for iid in invoices
                if self.invoice_latest[iid]["status"] == "issued"
                and Decimal(self.invoice_latest[iid]["total"]) > 0
            ]
            if not unpaid:
                continue
            iid = unpaid[-1]
            base = self.invoice_latest[iid]
            recovered = next((d for d in sorted(self.recoveries[key]) if d > failed_day), None)
            expired = next((d for d in sorted(self.expirations[key]) if d > failed_day), None)
            if recovered is not None and (expired is None or recovered < expired):
                paid = self.ts(recovered, 60_000)
                row = {
                    **base,
                    "status": "paid",
                    "paid_at": paid,
                    "amount_due": decimal(ZERO),
                    "_exported_at": self.export(paid),
                }
                self.rows["invoices"].append(row)
                self.invoice_latest[iid] = row
            elif expired is not None:
                effective = _date(self.cal, expired)
                created = self.ts(expired, 70_000)
                self.rows["credit_notes"].append(
                    {
                        "id": f"cn_{iid}",
                        "invoice_id": iid,
                        "customer_id": base["customer_id"],
                        "type": "adjustment",
                        "reason": "uncollectible",
                        "total": base["total"],
                        "effective_date": effective,
                        "created_at": created,
                        "voided_at": None,
                        "_exported_at": self.export(created),
                    }
                )

    def build(self):
        self.catalog()
        self.customers()
        self.subscriptions()
        self.quantity_changes()
        self.self_serve_invoices()
        self.enterprise_invoices()
        self.usage_events()
        self.payment_history()
        return {name: _columns(ORB_TABLES[name], rows) for name, rows in self.rows.items()}


def render(sim, personal):
    return Builder(sim, personal).build()

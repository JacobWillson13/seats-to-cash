"""The price book (seeds/price_book.csv): the single source of truth for every price.

Two lookups, because `valid_from`/`valid_to` mean "on sale", not "billable":
- `list_price(plan_code, date)` is what a new customer is sold on that date.
- `price(price_id)` is what an existing subscription keeps billing at, even after the
  price is withdrawn from sale (grandfathered v3 plans).
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED_COLUMNS = (
    "price_id",
    "plan_code",
    "plan_name",
    "price_version",
    "billing_basis",
    "item",
    "unit_amount_usd",
    "package_size",
    "free_units",
    "max_users",
    "discount_pct",
    "cadence",
    "billing_timing",
    "valid_from",
    "valid_to",
    "channel",
    "notes",
)
AMOUNT_COLUMN = re.compile(r"^unit_amount_([a-z]{3})$")  # only unit_amount_usd is allowed
PRICE_VERSIONS = ("v3", "v4", "all")
CADENCES = ("monthly", "annual")
BILLING_TIMINGS = ("in_advance", "in_arrears")


class PriceBookError(ValueError):
    """The price book file is malformed."""


@dataclass(frozen=True)
class Price:
    price_id: str
    plan_code: str
    plan_name: str
    price_version: str
    billing_basis: str
    item: str
    unit_amount_usd: Decimal | None  # None when priced per contract
    package_size: int | None
    free_units: int | None
    max_users: int | None
    discount_pct: Decimal | None
    cadence: str | None
    billing_timing: str | None
    valid_from: dt.date
    valid_to: dt.date | None
    channel: str
    notes: str

    def unit_amount(self) -> Decimal:
        if self.unit_amount_usd is None:
            raise LookupError(f"{self.price_id} has no list price; it is priced per contract")
        return self.unit_amount_usd

    def on_sale(self, on_date: dt.date) -> bool:
        return self.valid_from <= on_date and (self.valid_to is None or on_date <= self.valid_to)


class PriceBook:
    def __init__(self, prices: list[Price]):
        self._prices = prices
        self._by_id = {p.price_id: p for p in prices}

    @classmethod
    def load(cls, path: Path | str) -> PriceBook:
        path = Path(path)
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if missing := [c for c in REQUIRED_COLUMNS if c not in header]:
                raise PriceBookError(f"{path}: missing columns {missing}")
            if other := [c for c in header if AMOUNT_COLUMN.match(c) and c != "unit_amount_usd"]:
                raise PriceBookError(f"{path}: USD is the only currency; remove columns {other}")
            prices: list[Price] = []
            seen: set[str] = set()
            for line, row in enumerate(reader, start=2):
                try:
                    price = _parse_row(row)
                except (ValueError, InvalidOperation) as exc:
                    raise PriceBookError(f"{path} line {line}: {exc}") from None
                if price.price_id in seen:
                    raise PriceBookError(f"{path} line {line}: duplicate price_id {price.price_id}")
                seen.add(price.price_id)
                prices.append(price)
        return cls(prices)

    def __iter__(self) -> Iterator[Price]:
        return iter(self._prices)

    def __len__(self) -> int:
        return len(self._prices)

    def price(self, price_id: str) -> Price:
        try:
            return self._by_id[price_id]
        except KeyError:
            raise LookupError(f"no price with price_id {price_id!r}") from None

    def plan_version_price(self, plan_code: str, version: str) -> Price:
        """Existing plan terms by version, even after that version stops selling."""
        matches = [
            p for p in self._prices if p.plan_code == plan_code and p.price_version == version
        ]
        if len(matches) != 1:
            raise LookupError(
                f"expected one {plan_code!r} price for {version}, found {len(matches)}"
            )
        return matches[0]

    def list_price(self, plan_code: str, on_date: dt.date) -> Price:
        """The price a new customer is sold for `plan_code` on `on_date`."""
        matches = [p for p in self._prices if p.plan_code == plan_code and p.on_sale(on_date)]
        if not matches:
            raise LookupError(f"no {plan_code!r} price is on sale on {on_date}")
        if len(matches) > 1:
            ids = ", ".join(p.price_id for p in matches)
            raise LookupError(
                f"{plan_code!r} is ambiguous on {on_date} ({ids}); look it up with price()"
            )
        return matches[0]


def _parse_row(row: dict[str, str]) -> Price:
    price_id = _required(row, "price_id")
    version = _required(row, "price_version")
    if version not in PRICE_VERSIONS:
        raise ValueError(f"price_version must be one of {PRICE_VERSIONS}, got {version!r}")
    cadence = row["cadence"] or None
    if cadence is not None and cadence not in CADENCES:
        raise ValueError(f"cadence must be one of {CADENCES}, got {cadence!r}")
    timing = row["billing_timing"] or None
    if timing is not None and timing not in BILLING_TIMINGS:
        raise ValueError(f"billing_timing must be one of {BILLING_TIMINGS}, got {timing!r}")

    amount = Decimal(row["unit_amount_usd"]) if row["unit_amount_usd"] else None
    if amount is not None and amount < 0:
        raise ValueError(f"{price_id} has a negative unit amount")

    discount = Decimal(row["discount_pct"]) if row["discount_pct"] else None
    if discount is not None and not 0 <= discount <= 1:
        raise ValueError(f"{price_id} discount_pct must be between 0 and 1, got {discount}")

    valid_from = dt.date.fromisoformat(_required(row, "valid_from"))
    valid_to = dt.date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
    if valid_to is not None and valid_to < valid_from:
        raise ValueError(f"{price_id} valid_to {valid_to} is before valid_from {valid_from}")

    return Price(
        price_id=price_id,
        plan_code=_required(row, "plan_code"),
        plan_name=_required(row, "plan_name"),
        price_version=version,
        billing_basis=_required(row, "billing_basis"),
        item=_required(row, "item"),
        unit_amount_usd=amount,
        package_size=_optional_int(row["package_size"]),
        free_units=_optional_int(row["free_units"]),
        max_users=_optional_int(row["max_users"]),
        discount_pct=discount,
        cadence=cadence,
        billing_timing=timing,
        valid_from=valid_from,
        valid_to=valid_to,
        channel=_required(row, "channel"),
        notes=row["notes"],
    )


def _required(row: dict[str, str], column: str) -> str:
    if not row[column]:
        raise ValueError(f"{column} is blank")
    return row[column]


def _optional_int(value: str) -> int | None:
    return int(value) if value else None

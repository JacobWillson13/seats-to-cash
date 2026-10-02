"""Loaders for the committed seeds other than the price book."""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from generator.pricebook import PriceBook

FEATURES = (
    "ssh",
    "funnel",
    "exit_node",
    "subnet_router",
    "scim",
    "mdm_config",
    "posture_integration",
    "flow_logs",
    "log_streaming",
    "jit_access",
)
FX_SOURCES = ("ecb", "ecb_carried_forward", "simulated")


class SeedError(ValueError):
    """A seed file is malformed."""


def _rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != columns:
            raise SeedError(f"{path}: expected columns {list(columns)}, got {reader.fieldnames}")
        return list(reader)


def load_public_email_domains(path: Path) -> frozenset[str]:
    """Public webmail domains: a signup on one of these is a personal tailnet (SPEC 2.4)."""
    domains = [row["domain"] for row in _rows(path, ("domain",))]
    if any(d != d.strip().lower() or not d for d in domains):
        raise SeedError(f"{path}: domains must be lowercase with no surrounding spaces")
    return frozenset(domains)


class Entitlements:
    """Which features each (plan_code, price_version) includes."""

    def __init__(self, grid: dict[tuple[str, str], frozenset[str]]):
        self._grid = grid
        self.plans = tuple(grid)

    @classmethod
    def load(cls, path: Path) -> Entitlements:
        grid: dict[tuple[str, str], dict[str, bool]] = {}
        for line, row in enumerate(
            _rows(path, ("plan_code", "price_version", "feature", "entitled")), 2
        ):
            if row["feature"] not in FEATURES:
                raise SeedError(f"{path} line {line}: unknown feature {row['feature']!r}")
            if row["entitled"] not in ("true", "false"):
                raise SeedError(f"{path} line {line}: entitled must be true or false")
            features = grid.setdefault((row["plan_code"], row["price_version"]), {})
            if row["feature"] in features:
                raise SeedError(f"{path} line {line}: duplicate row for {row['feature']}")
            features[row["feature"]] = row["entitled"] == "true"
        for plan, features in grid.items():
            if missing := [f for f in FEATURES if f not in features]:
                raise SeedError(f"{path}: {plan} has no rows for {missing}")
        return cls({plan: frozenset(f for f, on in fs.items() if on) for plan, fs in grid.items()})

    def is_entitled(self, plan_code: str, price_version: str, feature: str) -> bool:
        if feature not in FEATURES:
            raise LookupError(f"unknown feature {feature!r}")
        try:
            return feature in self._grid[(plan_code, price_version)]
        except KeyError:
            raise LookupError(f"no entitlements for {plan_code} {price_version}") from None


class FxRates:
    """USD per unit of foreign currency, one row per calendar day."""

    def __init__(self, rates: dict[tuple[str, dt.date], Decimal]):
        self._rates = rates
        days = sorted({d for _, d in rates})
        self.date_range = (days[0], days[-1])

    @classmethod
    def load(cls, path: Path) -> FxRates:
        rates: dict[tuple[str, dt.date], Decimal] = {}
        columns = ("rate_date", "currency", "usd_per_unit", "source")
        for line, row in enumerate(_rows(path, columns), 2):
            if row["source"] not in FX_SOURCES:
                raise SeedError(f"{path} line {line}: unknown source {row['source']!r}")
            rate = Decimal(row["usd_per_unit"])
            if rate <= 0:
                raise SeedError(f"{path} line {line}: rate must be positive")
            rates[(row["currency"], dt.date.fromisoformat(row["rate_date"]))] = rate
        if not rates:
            raise SeedError(f"{path}: no rates")
        return cls(rates)

    def usd_per_unit(self, currency: str, on_date: dt.date) -> Decimal:
        if currency == "USD":
            return Decimal(1)
        try:
            return self._rates[(currency, on_date)]
        except KeyError:
            raise LookupError(f"no {currency} rate for {on_date}") from None


class CloseCalendar:
    """Close date per period ('YYYY-MM'). Rows after a period's close date are late (D05)."""

    def __init__(self, close_dates: dict[str, dt.date]):
        self.close_dates = close_dates

    @classmethod
    def load(cls, path: Path) -> CloseCalendar:
        return cls(
            {
                row["period"]: dt.date.fromisoformat(row["close_date"])
                for row in _rows(path, ("period", "close_date"))
            }
        )

    def close_date(self, period: str) -> dt.date:
        try:
            return self.close_dates[period]
        except KeyError:
            raise LookupError(f"no close date for period {period}") from None


@dataclass(frozen=True)
class Seeds:
    price_book: PriceBook
    entitlements: Entitlements
    public_email_domains: frozenset[str]
    fx: FxRates
    close_calendar: CloseCalendar

    @classmethod
    def load(cls, seeds_dir: Path | str = "seeds") -> Seeds:
        seeds_dir = Path(seeds_dir)
        try:
            return cls(
                price_book=PriceBook.load(seeds_dir / "price_book.csv"),
                entitlements=Entitlements.load(seeds_dir / "plan_entitlements.csv"),
                public_email_domains=load_public_email_domains(
                    seeds_dir / "free_email_domains.csv"
                ),
                fx=FxRates.load(seeds_dir / "fx_rates.csv"),
                close_calendar=CloseCalendar.load(seeds_dir / "close_calendar.csv"),
            )
        except FileNotFoundError as exc:
            raise SeedError(f"{exc.filename}: seed not found; run `make seeds`") from None

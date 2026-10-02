"""Load and validate the simulation config (config/simulation.yml).

A config file may name a base file with `extends:`; its keys are deep-merged over the base
(ADR-022). Every problem surfaces as a ConfigError whose message names the file and the
offending key.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from generator.clock import first_of_next_month, months_between
from generator.pricebook import PriceBook
from generator.reference import Seeds

Probability = Annotated[float, Field(ge=0, le=1)]
Multiplier = Annotated[float, Field(gt=0)]
NonNegative = Annotated[float, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
Marketplace = Literal["aws", "azure"]
Currency = Literal["USD", "EUR", "GBP"]

SHARE_TOLERANCE = 1e-9


class ConfigError(ValueError):
    """The config, or a seed it must agree with, is invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_range(name: str, pair: tuple[float, float]) -> None:
    low, high = pair
    if low > high:
        raise ValueError(f"{name} must be [low, high] with low <= high, got [{low}, {high}]")


def _check_shares(name: str, shares: dict[Any, float], *, total: float | None) -> None:
    s = sum(shares.values())
    if total is not None and abs(s - total) > SHARE_TOLERANCE:
        raise ValueError(f"{name} must sum to {total}, got {s:g}")
    if total is None and s > 1 + SHARE_TOLERANCE:
        raise ValueError(f"{name} must sum to at most 1, got {s:g}")


class LogNormal(_Section):
    mean: float
    sigma: Annotated[float, Field(gt=0)]


class Population(_Section):
    personal_tailnets: NonNegativeInt
    business_tailnets: NonNegativeInt
    signup_growth_monthly: Annotated[float, Field(gt=-1)]
    currencies: dict[Currency, Probability]
    nonprofit_share: Probability
    internal_tailnets: NonNegativeInt

    @model_validator(mode="after")
    def _shares(self) -> Population:
        _check_shares("currencies", self.currencies, total=1)
        return self


class People(_Section):
    employed_share: Probability
    personal_first_share: Probability
    same_machine_share: Probability
    email_localpart_reuse: Probability


class Personal(_Section):
    plus_upgrade_monthly: Probability
    plus_downgrade_monthly: Probability
    plus_retirement_downgrade_share: Probability
    plus_retirement_window_days: PositiveInt


class Trial(_Section):
    length_days: PositiveInt
    base_conversion: Probability
    bring_to_work_multiplier: Multiplier
    premium_share_at_conversion: Probability


class Seats(_Section):
    initial_users_lognormal: LogNormal
    monthly_user_growth: NonNegative
    removal_monthly: Probability
    headroom_seats_mean: NonNegative
    auto_seat_daily_prob_when_full: Probability
    low_utilization_threshold: Probability
    low_utilization_days: PositiveInt
    low_utilization_hazard_multiplier: Multiplier


class Upgrades(_Section):
    standard_to_premium_monthly: Probability
    starter_to_premium_monthly: Probability
    premium_to_standard_monthly: Probability
    gated_feature_multiplier: Multiplier


class Churn(_Section):
    voluntary_monthly: Probability
    reactivation_monthly: Probability
    payment_failure_rate: Probability
    dunning_recovery_rate: Probability
    dunning_days: PositiveInt


class Enterprise(_Section):
    lead_seat_threshold: PositiveInt
    lead_to_close: Probability
    lead_to_close_lag_days: tuple[NonNegativeInt, NonNegativeInt]
    term_months: dict[PositiveInt, Probability]
    discount_range: tuple[Probability, Probability]
    min_acv_usd: Annotated[float, Field(gt=0)]
    services_attach_rate: Probability
    services_amount_usd: tuple[NonNegative, NonNegative]
    marketplace_share: dict[Marketplace, Probability]
    multi_tailnet_share: Probability
    renewal_rate: Probability
    renewal_uplift_mean: NonNegative
    expansion_monthly: Probability
    expansion_seat_pct_mean: NonNegative

    @model_validator(mode="after")
    def _ranges_and_shares(self) -> Enterprise:
        _check_range("lead_to_close_lag_days", self.lead_to_close_lag_days)
        _check_range("discount_range", self.discount_range)
        _check_range("services_amount_usd", self.services_amount_usd)
        _check_shares("term_months", self.term_months, total=1)
        _check_shares("marketplace_share", self.marketplace_share, total=None)
        if bad := sorted(t for t in self.term_months if t % 12):
            raise ValueError(f"term_months keys must be whole years (multiples of 12), got {bad}")
        return self


class Crm(_Section):
    account_seat_threshold: PositiveInt


class Migration(_Section):
    voluntary_monthly_hazard: Probability
    high_uplift_threshold: NonNegative
    high_uplift_voluntary_multiplier: Multiplier
    high_uplift_churn_multiplier: Multiplier


class Addons(_Section):
    tagged_resource_overage_share: Probability
    mullvad_attach_rate: Probability


class Payments(_Section):
    card_fee_pct: Probability
    card_fee_fixed_cents: NonNegativeInt
    ach_fee_pct: Probability
    ach_fee_cap_cents: NonNegativeInt
    payout_lag_days: NonNegativeInt
    refund_rate: Probability
    marketplace_fee_pct: dict[Marketplace, Probability]


class Sync(_Section):
    fivetran_lag_minutes: tuple[NonNegativeInt, NonNegativeInt]
    orb_export_lag_hours: tuple[NonNegativeInt, NonNegativeInt]
    late_row_lag_days: tuple[NonNegativeInt, NonNegativeInt]

    @model_validator(mode="after")
    def _ranges(self) -> Sync:
        for name in ("fivetran_lag_minutes", "orb_export_lag_hours", "late_row_lag_days"):
            _check_range(name, getattr(self, name))
        return self


class Defects(_Section):
    """Rates per defect denominator (SPEC 5). D03 is population.internal_tailnets."""

    D01_duplicate_stripe_customer: Probability
    D02_sf_missing_tailnet_id: Probability
    D02_sf_mistyped_tailnet_id: Probability
    D04_month_end_early_invoices: Probability
    D05_late_rows: Probability
    D06_duplicate_stripe_sync: Probability
    D07_marketplace_bad_opp_ref: Probability
    D08_crm_amount_includes_nonrecurring: Probability
    D09_soft_deleted_rows: Probability
    D10_manual_adj_missing_approver: Probability
    D10_manual_adj_name_ref: Probability
    D11_orphan_charge: Probability
    D12_orb_quantity_lag: Probability
    D13_test_mode_rows: Probability

    @model_validator(mode="after")
    def _subtypes(self) -> Defects:
        if self.D02_sf_missing_tailnet_id + self.D02_sf_mistyped_tailnet_id > 1:
            raise ValueError("D02 missing and mistyped rates must sum to at most 1")
        if self.D10_manual_adj_missing_approver + self.D10_manual_adj_name_ref > 1:
            raise ValueError("D10 missing-approver and name-ref rates must sum to at most 1")
        return self


class Output(_Section):
    data_dir: Path
    duckdb_path: Path


class SimulationConfig(_Section):
    seed: NonNegativeInt
    sim_start_date: dt.date
    reporting_start_date: dt.date
    end_date: dt.date
    extract_date: dt.date
    reporting_tz: str
    v4_effective_date: dt.date
    legacy_forced_migration_date: dt.date

    population: Population
    people: People
    personal: Personal
    trial: Trial
    seats: Seats
    upgrades: Upgrades
    churn: Churn
    enterprise: Enterprise
    crm: Crm
    migration: Migration
    addons: Addons
    payments: Payments
    sync: Sync
    defects: Defects
    output: Output

    @property
    def forced_migration_effective_date(self) -> dt.date:
        """The first billing cycle after the legacy deadline (SPEC 2.5)."""
        return first_of_next_month(self.legacy_forced_migration_date)

    @model_validator(mode="after")
    def _cross_field(self) -> SimulationConfig:
        try:
            ZoneInfo(self.reporting_tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"reporting_tz: unknown time zone {self.reporting_tz!r}") from None

        dates = ["sim_start_date", "reporting_start_date", "end_date", "extract_date"]
        for earlier, later in zip(dates, dates[1:], strict=False):
            if getattr(self, earlier) > getattr(self, later):
                raise ValueError(f"{earlier} must be on or before {later}")
        if not self.sim_start_date < self.v4_effective_date <= self.end_date:
            raise ValueError("v4_effective_date must fall after sim_start_date and by end_date")
        if self.legacy_forced_migration_date <= self.v4_effective_date:
            raise ValueError("legacy_forced_migration_date must be after v4_effective_date")

        # A hazard times its largest multiplier must still be a probability.
        products = {
            "trial.base_conversion x trial.bring_to_work_multiplier": (
                self.trial.base_conversion * self.trial.bring_to_work_multiplier
            ),
            "upgrades.standard_to_premium_monthly x gated_feature_multiplier": (
                self.upgrades.standard_to_premium_monthly * self.upgrades.gated_feature_multiplier
            ),
            "upgrades.starter_to_premium_monthly x gated_feature_multiplier": (
                self.upgrades.starter_to_premium_monthly * self.upgrades.gated_feature_multiplier
            ),
            "seats.removal_monthly x low_utilization_hazard_multiplier": (
                self.seats.removal_monthly * self.seats.low_utilization_hazard_multiplier
            ),
            "churn.voluntary_monthly x low-utilization and high-uplift multipliers": (
                self.churn.voluntary_monthly
                * self.seats.low_utilization_hazard_multiplier
                * self.migration.high_uplift_churn_multiplier
            ),
            "migration.voluntary_monthly_hazard x high_uplift_voluntary_multiplier": (
                self.migration.voluntary_monthly_hazard
                * self.migration.high_uplift_voluntary_multiplier
            ),
        }
        for name, value in products.items():
            if value > 1:
                raise ValueError(f"{name} = {value:g}, which is not a probability")

        if self.crm.account_seat_threshold > self.enterprise.lead_seat_threshold:
            raise ValueError(
                "crm.account_seat_threshold must not exceed enterprise.lead_seat_threshold, "
                "or enterprise leads would have no Salesforce account"
            )
        if missing := sorted(
            set(self.enterprise.marketplace_share) - set(self.payments.marketplace_fee_pct)
        ):
            raise ValueError(f"payments.marketplace_fee_pct is missing {missing}")
        return self


def _read_yaml(path: Path, chain: tuple[Path, ...] = ()) -> dict[str, Any]:
    path = path.resolve()
    if path in chain:
        raise ConfigError(f"{path}: `extends` cycle: {' -> '.join(str(p) for p in chain)}")
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"{path}: config file not found") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML: {exc}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    base_name = raw.pop("extends", None)
    if base_name is None:
        return raw
    base = _read_yaml(path.parent / base_name, (*chain, path))
    return _deep_merge(base, raw)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _describe(error: dict[str, Any]) -> str:
    where = ".".join(str(part) for part in error["loc"]) or "(top level)"
    message = {
        "extra_forbidden": "unknown key",
        "missing": "missing required key",
    }.get(error["type"], error["msg"].removeprefix("Value error, "))
    if error["type"] in ("extra_forbidden", "missing") or isinstance(error["input"], dict):
        return f"{where}: {message}"  # section-level checks: the message carries the values
    return f"{where}: {message} (got {error['input']!r})"


def load_config(path: Path | str) -> SimulationConfig:
    """Read, merge, and validate a config file."""
    path = Path(path)
    raw = _read_yaml(path)
    try:
        return SimulationConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "\n".join(f"  - {_describe(e)}" for e in exc.errors())
        raise ConfigError(f"{path}: invalid config\n{problems}") from None


def cross_check(config: SimulationConfig, seeds: Seeds) -> None:
    """Check values the config duplicates from the seeds (X5) and seed coverage of the window."""
    problems = _price_book_problems(config, seeds.price_book)
    day = dt.timedelta(days=1)

    if missing := sorted(set(config.population.currencies) - set(seeds.price_book.currencies)):
        problems.append(f"price book has no unit_amount column for currencies {missing}")

    plan_rows = {(p.plan_code, p.price_version) for p in seeds.price_book}
    if missing := sorted(set(seeds.entitlements.plans) - plan_rows):
        problems.append(f"plan_entitlements.csv lists plans missing from the price book: {missing}")

    periods = months_between(config.sim_start_date, config.end_date)
    if missing := [p for p in periods if p not in seeds.close_calendar.close_dates]:
        problems.append(f"close_calendar.csv is missing periods {missing[0]} .. {missing[-1]}")
    elif (
        last_close := seeds.close_calendar.close_dates[periods[-1]]
    ) + config.sync.late_row_lag_days[1] * day > config.extract_date:
        problems.append(
            f"extract_date {config.extract_date} is too early: the last close ({last_close}) "
            f"plus the longest late-row lag ({config.sync.late_row_lag_days[1]} days) is later"
        )

    fx_start, fx_end = seeds.fx.date_range
    if fx_start > config.sim_start_date or fx_end < config.extract_date:
        problems.append(
            f"fx_rates.csv covers {fx_start} .. {fx_end}, "
            f"not the full {config.sim_start_date} .. {config.extract_date}"
        )

    if problems:
        raise ConfigError("config and seeds disagree\n" + "\n".join(f"  - {p}" for p in problems))


def _price_book_problems(config: SimulationConfig, book: PriceBook) -> list[str]:
    problems = []
    v3_end = config.v4_effective_date - dt.timedelta(days=1)
    for price in book:
        if price.price_version == "v4" and price.valid_from != config.v4_effective_date:
            problems.append(
                f"price book {price.price_id} valid_from {price.valid_from} "
                f"!= v4_effective_date {config.v4_effective_date}"
            )
        if price.price_version == "v3" and price.valid_to != v3_end:
            problems.append(
                f"price book {price.price_id} valid_to {price.valid_to} "
                f"!= the day before v4_effective_date ({v3_end})"
            )
        if price.price_version in ("v3", "all") and price.valid_from > config.sim_start_date:
            problems.append(
                f"price book {price.price_id} valid_from {price.valid_from} "
                f"is after sim_start_date {config.sim_start_date}"
            )
    return problems

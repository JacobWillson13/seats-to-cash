"""Load and validate the simulation config (config/simulation.yml).

A config file may name a base file with `extends:`; its keys are deep-merged over the base.
Every problem surfaces as a ConfigError whose message names the file and the offending key.
Every section forbids unknown keys, so settings for features outside the project scope are
rejected rather than silently ignored.
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
from generator.reference import FEATURES, Seeds

Probability = Annotated[float, Field(ge=0, le=1)]
Multiplier = Annotated[float, Field(gt=0)]
NonNegative = Annotated[float, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
Role = Literal["admin", "billing_admin", "member"]
DeviceOs = Literal["macos", "windows", "linux", "ios", "android"]

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
    nonprofit_share: Probability
    internal_tailnets: NonNegativeInt


class People(_Section):
    employed_share: Probability
    personal_first_share: Probability
    same_machine_share: Probability
    email_localpart_reuse: Probability
    webmail_domains: dict[str, Probability]

    @model_validator(mode="after")
    def _shares(self) -> People:
        _check_shares("webmail_domains", self.webmail_domains, total=1)
        return self


class Personal(_Section):
    extra_users_mean: NonNegative
    monthly_active_share: Probability


class Trial(_Section):
    length_days: PositiveInt
    base_conversion: Probability
    bring_to_work_multiplier: Multiplier
    premium_share_at_conversion: Probability


class Seats(_Section):
    initial_users_lognormal: LogNormal
    monthly_user_growth: NonNegative
    company_size_lognormal: LogNormal
    user_departure_monthly: Probability
    growth_gamma_shape: Annotated[float, Field(gt=0)]
    bring_to_work_growth_multiplier: Multiplier
    removal_monthly: Probability
    headroom_seats_mean: NonNegative
    auto_seat_daily_prob_when_full: Probability
    low_utilization_threshold: Probability
    low_utilization_days: PositiveInt
    low_utilization_hazard_multiplier: Multiplier
    approval_required_share: Probability
    approval_lag_days: tuple[NonNegativeInt, NonNegativeInt]
    login_lag_days: tuple[NonNegativeInt, NonNegativeInt]
    never_login_share: Probability
    invite_expiry_days: PositiveInt
    role_shares: dict[Role, Probability]

    @model_validator(mode="after")
    def _ranges_and_shares(self) -> Seats:
        _check_range("approval_lag_days", self.approval_lag_days)
        _check_range("login_lag_days", self.login_lag_days)
        _check_shares("role_shares", self.role_shares, total=1)
        return self


class Activity(_Section):
    user_active_weekday: Probability
    user_active_weekend: Probability
    user_propensity_beta: tuple[Annotated[float, Field(gt=0)], Annotated[float, Field(gt=0)]]
    dormant_user_share: Probability
    dormant_user_propensity: Probability
    devices_per_user_mean: Annotated[float, Field(ge=1)]
    device_os_shares: dict[DeviceOs, Probability]
    advanced_feature_interest_share: Probability
    premium_feature_interest_share: Probability
    feature_daily_prob: dict[str, Probability]
    feature_attempts_mean: Annotated[float, Field(ge=1)]
    tagged_resources_mean: NonNegative
    ephemeral_share: Probability
    ephemeral_minutes_mean: NonNegative

    @model_validator(mode="after")
    def _shares(self) -> Activity:
        _check_shares("device_os_shares", self.device_os_shares, total=1)
        if sorted(self.feature_daily_prob) != sorted(FEATURES):
            raise ValueError(f"feature_daily_prob must have exactly the features {list(FEATURES)}")
        return self


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
    direct_sales_accounts: NonNegativeInt
    lead_seat_threshold: PositiveInt
    lead_to_close: Probability
    lead_to_close_lag_days: tuple[NonNegativeInt, NonNegativeInt]
    term_months: dict[PositiveInt, Probability]
    discount_range: tuple[Probability, Probability]
    min_acv_usd: Annotated[float, Field(gt=0)]
    renewal_rate: Probability
    renewal_uplift_mean: NonNegative
    expansion_monthly: Probability
    expansion_seat_pct_mean: NonNegative

    @model_validator(mode="after")
    def _ranges_and_shares(self) -> Enterprise:
        _check_range("lead_to_close_lag_days", self.lead_to_close_lag_days)
        _check_range("discount_range", self.discount_range)
        _check_shares("term_months", self.term_months, total=1)
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


class Payments(_Section):
    card_fee_pct: Probability
    card_fee_fixed_cents: NonNegativeInt
    ach_fee_pct: Probability
    ach_fee_cap_cents: NonNegativeInt
    payout_lag_days: NonNegativeInt
    refund_rate: Probability


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
    """Rates for the six planted defects (SPEC 3, ADR-010), each over its own denominator.

    D03 has no rate: it is the count `population.internal_tailnets`. No other defect code is
    accepted; an unknown key fails validation.
    """

    D01_duplicate_stripe_customer: Probability
    D05_late_rows: Probability
    D06_duplicate_stripe_sync: Probability
    D09_soft_deleted_rows: Probability
    D13_test_mode_rows: Probability


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
    activity: Activity
    upgrades: Upgrades
    churn: Churn
    enterprise: Enterprise
    crm: Crm
    migration: Migration
    payments: Payments
    sync: Sync
    defects: Defects
    output: Output

    @property
    def forced_migration_effective_date(self) -> dt.date:
        """The first billing cycle after the legacy deadline (SPEC §2)."""
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


# Settings for features removed from the project scope. Their code paths are gone, so any
# value would be silently meaningless; validation names the feature instead.
REMOVED_KEYS = {
    "population.currencies": "multi-currency (the project is USD only)",
    "personal.plus_upgrade_monthly": "Personal Plus",
    "personal.plus_downgrade_monthly": "Personal Plus",
    "personal.plus_retirement_downgrade_share": "Personal Plus",
    "personal.plus_retirement_window_days": "Personal Plus",
    "activity.tagged_resources_overage_mean": "add-ons",
    "addons": "add-ons",
    "enterprise.services_attach_rate": "services",
    "enterprise.services_delivery_lag_days": "services",
    "enterprise.services_amount_usd": "services",
    "enterprise.marketplace_share": "marketplace",
    "payments.marketplace_fee_pct": "marketplace",
    "enterprise.multi_tailnet_share": "multi-tailnet enterprise",
    **{
        f"defects.{key}": "defects other than D01, D03, D05, D06, D09, D13"
        for key in (
            "D02_sf_missing_tailnet_id",
            "D02_sf_mistyped_tailnet_id",
            "D04_month_end_early_invoices",
            "D07_marketplace_bad_opp_ref",
            "D08_crm_amount_includes_nonrecurring",
            "D10_manual_adj_missing_approver",
            "D10_manual_adj_name_ref",
            "D11_orphan_charge",
            "D12_orb_quantity_lag",
        )
    },
}


def _describe(error: dict[str, Any]) -> str:
    where = ".".join(str(part) for part in error["loc"]) or "(top level)"
    unknown = "unknown key"
    if where in REMOVED_KEYS:
        unknown = f"removed from scope ({REMOVED_KEYS[where]}); delete this key"
    message = {
        "extra_forbidden": unknown,
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
    """Check values the config duplicates from the seeds and seed coverage of the window."""
    problems = _price_book_problems(config, seeds.price_book)
    day = dt.timedelta(days=1)

    if unknown := sorted(set(config.people.webmail_domains) - seeds.public_email_domains):
        problems.append(f"people.webmail_domains are not public email domains: {unknown}")

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

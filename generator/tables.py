"""Every raw and truth table: columns, types, keys, and sort order.

This module is the source of truth for table shapes; docs/SCHEMAS.md documents every table
defined here. Timestamps are UTC microseconds without a zone.
"""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa

TS = pa.timestamp("us")
DATE = pa.date32()
STR = pa.string()
INT = pa.int32()
BOOL = pa.bool_()


@dataclass(frozen=True)
class Column:
    name: str
    type: pa.DataType
    nullable: bool = True


@dataclass(frozen=True)
class Table:
    source: str  # data/raw/<source>/, loaded into schema raw_<source>
    name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    sort_key: tuple[str, ...]
    versioned: bool = False

    @property
    def schema(self) -> pa.Schema:
        return pa.schema([pa.field(c.name, c.type, c.nullable) for c in self.columns])


def _c(name, type_, nullable=True) -> Column:
    return Column(name, type_, nullable)


FIVETRAN = (_c("_fivetran_synced", TS, False), _c("_fivetran_deleted", BOOL, False))
HISTORY = (
    _c("_fivetran_start", TS, False),
    _c("_fivetran_end", TS, False),
    _c("_fivetran_active", BOOL, False),
)

APP_TABLES = {
    t.name: t
    for t in (
        Table("app", "tailnets", (
            _c("id", STR, False), _c("name", STR, False), _c("created_at", TS, False),
            _c("creator_user_id", STR, False), _c("signup_domain", STR, False),
            _c("plan_code", STR, False), _c("price_version", STR, False),
            _c("trial_started_at", TS), _c("trial_ended_at", TS), _c("currency", STR, False),
            _c("is_nonprofit", BOOL, False), _c("deleted_at", TS), *FIVETRAN, *HISTORY,
        ), ("id", "_fivetran_start"), ("id", "_fivetran_start"), versioned=True),
        Table("app", "users", (
            _c("id", STR, False), _c("tailnet_id", STR, False), _c("email", STR, False),
            _c("role", STR, False), _c("invited_at", TS, False), _c("approved_at", TS),
            _c("first_login_at", TS), _c("removed_at", TS), *FIVETRAN, *HISTORY,
        ), ("id", "_fivetran_start"), ("id", "_fivetran_start"), versioned=True),
        Table("app", "seat_events", (
            _c("id", STR, False), _c("tailnet_id", STR, False), _c("user_id", STR),
            _c("event_type", STR, False), _c("seats_held_after", INT, False),
            _c("seats_occupied_after", INT, False), _c("actor", STR, False),
            _c("occurred_at", TS, False), *FIVETRAN,
        ), ("id",), ("occurred_at", "id")),
        Table("app", "plan_changes", (
            _c("id", STR, False), _c("tailnet_id", STR, False), _c("changed_at", TS, False),
            _c("from_plan_code", STR, False), _c("to_plan_code", STR, False),
            _c("from_price_version", STR, False), _c("to_price_version", STR, False),
            _c("change_source", STR, False), *FIVETRAN,
        ), ("id",), ("changed_at", "id")),
        Table("app", "device_registrations", (
            _c("id", STR, False), _c("tailnet_id", STR, False), _c("user_id", STR),
            _c("machine_key_hash", STR, False), _c("os", STR, False),
            _c("is_tagged", BOOL, False), _c("registered_at", TS, False), _c("removed_at", TS),
            *FIVETRAN,
        ), ("id",), ("registered_at", "id")),
        Table("app", "tailnet_activity_daily", (
            _c("tailnet_id", STR, False), _c("activity_date", DATE, False),
            _c("active_users", INT, False), _c("user_devices", INT, False),
            _c("tagged_resources", INT, False), _c("ephemeral_minutes", INT, False), *FIVETRAN,
        ), ("tailnet_id", "activity_date"), ("activity_date", "tailnet_id")),
        Table("app", "tailnet_activity_monthly", (
            _c("tailnet_id", STR, False), _c("activity_month", DATE, False),
            _c("active_users", INT, False), _c("user_devices", INT, False), *FIVETRAN,
        ), ("tailnet_id", "activity_month"), ("activity_month", "tailnet_id")),
        Table("app", "feature_usage_daily", (
            _c("tailnet_id", STR, False), _c("activity_date", DATE, False),
            _c("feature", STR, False), _c("attempts", INT, False),
            _c("gated_blocked", BOOL, False), *FIVETRAN,
        ), ("tailnet_id", "activity_date", "feature"), ("activity_date", "tailnet_id", "feature")),
    )
}  # fmt: skip


SF_TABLES = {
    t.name: t
    for t in (
        Table(
            "salesforce",
            "user",
            (
                _c("id", STR, False),
                _c("name", STR, False),
                _c("email", STR, False),
                _c("user_role_name", STR, False),
                _c("is_active", BOOL, False),
                _c("is_deleted", BOOL, False),
                _c("_fivetran_synced", TS, False),
            ),
            ("id",),
            ("id",),
        ),
        Table(
            "salesforce",
            "account",
            (
                _c("id", STR, False),
                _c("name", STR, False),
                _c("website", STR, False),
                _c("type", STR, False),
                _c("industry", STR),
                _c("number_of_employees", INT, False),
                _c("billing_country", STR, False),
                _c("owner_id", STR, False),
                _c("created_date", TS, False),
                _c("last_modified_date", TS, False),
                _c("tailnet_id__c", STR),
                _c("customer_tier__c", STR),
                _c("is_deleted", BOOL, False),
                _c("_fivetran_synced", TS, False),
            ),
            ("id", "_fivetran_synced"),
            ("id", "_fivetran_synced"),
            versioned=True,
        ),
        Table(
            "salesforce",
            "lead",
            (
                _c("id", STR, False),
                _c("account_id", STR, False),
                _c("lead_source", STR, False),
                _c("status", STR, False),
                _c("created_date", TS, False),
                _c("is_deleted", BOOL, False),
                _c("_fivetran_synced", TS, False),
            ),
            ("id",),
            ("id",),
        ),
        Table(
            "salesforce",
            "opportunity",
            (
                _c("id", STR, False),
                _c("account_id", STR, False),
                _c("name", STR, False),
                _c("type", STR, False),
                _c("stage_name", STR, False),
                _c("is_closed", BOOL, False),
                _c("is_won", BOOL, False),
                _c("amount", pa.decimal128(18, 2)),
                _c("close_date", DATE, False),
                _c("created_date", TS, False),
                _c("last_modified_date", TS, False),
                _c("probability", pa.decimal128(5, 2), False),
                _c("owner_id", STR, False),
                _c("lead_source", STR, False),
                _c("contract_term_months__c", INT),
                _c("contract_start_date__c", DATE),
                _c("recurring_arr__c", pa.decimal128(18, 2)),
                _c("is_deleted", BOOL, False),
                _c("_fivetran_synced", TS, False),
            ),
            ("id", "_fivetran_synced"),
            ("id", "_fivetran_synced"),
            versioned=True,
        ),
    )
}

TRUTH_TABLES = {
    "truth_enterprise_contracts": Table(
        "truth",
        "truth_enterprise_contracts",
        (
            _c("tailnet_id", STR, False),
            _c("event_date", DATE, False),
            _c("event_kind", STR, False),
            _c("enterprise_source", STR, False),
            _c("price_id", STR, False),
            _c("contract_start_date", DATE, False),
            _c("contract_end_date", DATE, False),
            _c("term_months", INT, False),
            _c("seats", INT, False),
            _c("discount_pct", STR, False),
            _c("recurring_acv", STR, False),
        ),
        ("tailnet_id", "event_date", "event_kind"),
        ("event_date", "tailnet_id", "event_kind"),
    ),
}

ORB_TABLES = {
    t.name: t
    for t in (
        Table(
            "orb",
            "customers",
            (
                _c("id", STR, False),
                _c("external_customer_id", STR, False),
                _c("name", STR, False),
                _c("email", STR, False),
                _c("currency", STR, False),
                _c("payment_provider", STR),
                _c("payment_provider_id", STR),
                _c("billing_country", STR, False),
                _c("created_at", TS, False),
                _c("metadata", STR, False),
                _c("_exported_at", TS, False),
            ),
            ("id", "_exported_at"),
            ("id", "_exported_at"),
            versioned=True,
        ),
        Table(
            "orb",
            "plans",
            (
                _c("id", STR, False),
                _c("external_plan_id", STR, False),
                _c("name", STR, False),
                _c("price_version", STR, False),
                _c("currency", STR, False),
                _c("created_at", TS, False),
                _c("_exported_at", TS, False),
            ),
            ("id",),
            ("id",),
        ),
        Table(
            "orb",
            "prices",
            (
                _c("id", STR, False),
                _c("plan_id", STR, False),
                _c("external_price_id", STR, False),
                _c("item_name", STR, False),
                _c("model_type", STR, False),
                _c("unit_amount", STR),
                _c("package_size", INT),
                _c("cadence", STR),
                _c("billing_timing", STR),
                _c("_exported_at", TS, False),
            ),
            ("id",),
            ("id",),
        ),
        Table(
            "orb",
            "subscriptions",
            (
                _c("id", STR, False),
                _c("customer_id", STR, False),
                _c("plan_id", STR, False),
                _c("status", STR, False),
                _c("start_date", DATE, False),
                _c("end_date", DATE),
                _c("net_terms", INT, False),
                _c("invoicing_channel", STR, False),
                _c("discount_pct", STR, False),
                _c("ended_reason", STR),
                _c("created_at", TS, False),
                _c("_exported_at", TS, False),
            ),
            ("id", "_exported_at"),
            ("id", "_exported_at"),
            versioned=True,
        ),
        Table(
            "orb",
            "subscription_quantity_changes",
            (
                _c("id", STR, False),
                _c("subscription_id", STR, False),
                _c("price_id", STR, False),
                _c("effective_date", DATE, False),
                _c("quantity", INT, False),
                _c("source", STR, False),
                _c("recorded_at", TS, False),
                _c("_exported_at", TS, False),
            ),
            ("id",),
            ("effective_date", "id"),
        ),
        Table(
            "orb",
            "invoices",
            (
                _c("id", STR, False),
                _c("invoice_number", STR, False),
                _c("customer_id", STR, False),
                _c("subscription_id", STR, False),
                _c("status", STR, False),
                _c("currency", STR, False),
                _c("invoice_date", DATE, False),
                _c("issued_at", TS, False),
                _c("service_period_start", DATE, False),
                _c("service_period_end", DATE, False),
                _c("due_date", DATE, False),
                _c("paid_at", TS),
                _c("voided_at", TS),
                _c("subtotal", STR, False),
                _c("discount_total", STR, False),
                _c("tax", STR, False),
                _c("total", STR, False),
                _c("amount_due", STR, False),
                _c("external_sync_id", STR),
                _c("_exported_at", TS, False),
            ),
            ("id", "_exported_at"),
            ("id", "_exported_at"),
            versioned=True,
        ),
        Table(
            "orb",
            "invoice_line_items",
            (
                _c("id", STR, False),
                _c("invoice_id", STR, False),
                _c("subscription_id", STR, False),
                _c("price_id", STR, False),
                _c("line_type", STR, False),
                _c("applies_to_line_id", STR),
                _c("name", STR, False),
                _c("start_date", DATE, False),
                _c("end_date", DATE, False),
                _c("quantity", INT, False),
                _c("unit_amount", STR, False),
                _c("amount", STR, False),
                _c("_exported_at", TS, False),
            ),
            ("id",),
            ("invoice_id", "id"),
        ),
        Table(
            "orb",
            "credit_notes",
            (
                _c("id", STR, False),
                _c("invoice_id", STR, False),
                _c("customer_id", STR, False),
                _c("type", STR, False),
                _c("reason", STR, False),
                _c("total", STR, False),
                _c("effective_date", DATE, False),
                _c("created_at", TS, False),
                _c("voided_at", TS),
                _c("_exported_at", TS, False),
            ),
            ("id",),
            ("effective_date", "id"),
        ),
        Table(
            "orb",
            "events",
            (
                _c("id", STR, False),
                _c("idempotency_key", STR, False),
                _c("event_name", STR, False),
                _c("external_customer_id", STR, False),
                _c("timestamp", TS, False),
                _c("properties", STR, False),
                _c("_exported_at", TS, False),
            ),
            ("id",),
            ("timestamp", "id"),
        ),
        Table(
            "orb",
            "daily_line_item_revenue",
            (
                _c("revenue_date", DATE, False),
                _c("invoice_line_item_id", STR, False),
                _c("invoice_id", STR, False),
                _c("customer_id", STR, False),
                _c("price_id", STR, False),
                _c("recognized_amount", STR, False),
                _c("currency", STR, False),
                _c("_exported_at", TS, False),
            ),
            ("invoice_line_item_id", "revenue_date"),
            ("revenue_date", "invoice_line_item_id"),
        ),
    )
}

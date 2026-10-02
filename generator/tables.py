"""Every raw and truth table: columns, types, keys, and sort order.

This module is the source of truth for table shapes; from PLAN 1.11 the column tables in
docs/SCHEMAS.md are generated from it. Timestamps are UTC microseconds without a zone.
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

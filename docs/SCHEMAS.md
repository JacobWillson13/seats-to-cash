# Source schemas

`generator/tables.py` is the typed contract for every table: names, columns, primary keys, sort order, and Parquet types. This file documents every table the generator writes, plus the tables still planned for PLAN task b. Raw tables are not the scope boundary: dbt stages every landed table, and the marts use only what the story needs.

Conventions:
- All source tables load under `raw_<source>`; the answer key loads under `raw_truth`. The generator writes Parquet to `data/raw/<source>/` and `data/answer_key/truth/`.
- USD only. Orb amounts are decimal strings; Stripe amounts are integer cents; Salesforce amounts are `decimal(18,2)`.
- Timestamps are UTC microseconds without a zone.
- "Version log" means one row per version of an entity, keyed by the entity ID and a load timestamp. "Append-only" means one row per fact.

## raw_app (product database, Fivetran-shaped)

Every table carries `_fivetran_synced` and `_fivetran_deleted`. Version logs also carry `_fivetran_start`, `_fivetran_end`, and `_fivetran_active` (Fivetran history mode).

| Table | Grain | Columns |
|---|---|---|
| `tailnets` | Version log per tailnet | id, name, created_at, creator_user_id, signup_domain, plan_code, price_version, trial_started_at, trial_ended_at, currency (always `USD`), is_nonprofit, deleted_at |
| `users` | Version log per user | id, tailnet_id, email, role, invited_at, approved_at, first_login_at, removed_at |
| `seat_events` | Append-only | id, tailnet_id, user_id, event_type (`seats_set`, `seat_occupied`, `seat_vacated`, `auto_seat_added`), seats_held_after, seats_occupied_after, actor (`admin`, `scim`, `system`), occurred_at |
| `plan_changes` | Append-only | id, tailnet_id, changed_at, from_plan_code, to_plan_code, from_price_version, to_price_version, change_source (`trial_end`, `self_serve`, `migration_voluntary`, `dunning`, `sales`) |
| `device_registrations` | Append-only | id, tailnet_id, user_id, machine_key_hash, os, is_tagged, registered_at, removed_at |
| `tailnet_activity_daily` | Tailnet × day | tailnet_id, activity_date, active_users, user_devices, tagged_resources (tagged devices), ephemeral_minutes |
| `tailnet_activity_monthly` | Tailnet × month | tailnet_id, activity_month, active_users, user_devices |
| `feature_usage_daily` | Tailnet × day × feature | tailnet_id, activity_date, feature, attempts, gated_blocked |

Plan codes are `personal`, `starter`, `standard`, `premium`, and `enterprise`.

## raw_orb (Orb export)

Every table carries `_exported_at`, the export load time. Price IDs are `op_<price_book price_id>_usd` (for example `op_v4_standard_usd`). Plan IDs are `plan_<plan_code>_<price_version>_usd`.

| Table | Grain | Columns | Used by marts |
|---|---|---|---|
| `customers` | Version log per customer | id, external_customer_id (tailnet ID), name, email, currency, payment_provider (`stripe`), payment_provider_id, billing_country, created_at, metadata | yes |
| `plans` | One row per plan and version | id, external_plan_id, name, price_version, currency, created_at | staged only |
| `prices` | One row per price-book price | id, plan_id, external_price_id, item_name, model_type, unit_amount, package_size, cadence, billing_timing | staged only |
| `subscriptions` | Version log per subscription term | id, customer_id, plan_id, status (`active`, `ended`), start_date, end_date, net_terms, invoicing_channel (`stripe`), discount_pct, ended_reason (`voluntary`, `involuntary`, `migrated`, `replaced`), created_at | yes |
| `subscription_quantity_changes` | Append-only | id, subscription_id, price_id, effective_date, quantity, source (`admin`, `scim`, `system`, `auto_seat`, `sales`), recorded_at | staged only |
| `invoices` | Version log per invoice | id, invoice_number, customer_id, subscription_id, status (`issued`, `paid`), currency, invoice_date, issued_at, service_period_start, service_period_end, due_date, paid_at, voided_at, subtotal, discount_total, tax, total, amount_due, external_sync_id (Stripe invoice ID; null for zero-total invoices) | yes |
| `invoice_line_items` | Append-only | id, invoice_id, subscription_id, price_id, line_type (`usage`, `fixed`, `proration`, `discount`), applies_to_line_id, name, start_date, end_date, quantity, unit_amount, amount | yes |
| `credit_notes` | Append-only | id, invoice_id, customer_id, type (`adjustment`), reason (`uncollectible`), total, effective_date, created_at, voided_at | yes |
| `events` | Append-only usage event | id, idempotency_key, event_name (`user_active`), external_customer_id, timestamp, properties | staged only |
| `daily_line_item_revenue` | Line item × service day | revenue_date, invoice_line_item_id, invoice_id, customer_id, price_id, recognized_amount, currency | staged only; may cross-check revenue |

## raw_stripe (planned, PLAN task b)

Every table includes `livemode`, `_fivetran_synced`, and `_fivetran_deleted` where applicable. D13 rows use test mode and are filtered in staging.

- `customer` (version log): id, created, email, name, currency, delinquent, description, metadata, is_deleted, livemode.
- `invoice` (version log): id, customer_id, number, status, billing_reason, collection_method, currency, subtotal, tax, total, amount_due, amount_paid, amount_remaining, created, due_date, period_start/end, paid, charge_id, metadata, status transition timestamps, livemode.
- `charge` (version log): id, customer_id, invoice_id, amount, amount_refunded, currency, created, status, paid, captured, failure fields, payment method, balance transaction ID, livemode.
- `refund`: id, charge_id, amount, currency, created, reason, status, balance_transaction_id.
- `balance_transaction`: id, source, type, amount, fee, net, currency, created, available_on, status.

## raw_salesforce (enterprise CRM, Fivetran-shaped)

Every PLG tailnet that reaches the enterprise seat threshold, and every direct-sales account, gets an account and an opportunity. Each table carries `is_deleted` and `_fivetran_synced`.

| Table | Grain | Columns |
|---|---|---|
| `account` | Version log (`Prospect`, then `Customer` at signing) | id, name, website, type, industry, number_of_employees, billing_country, owner_id, created_date, last_modified_date, tailnet_id__c, customer_tier__c |
| `opportunity` | Version log (open, then `Closed Won` at signing) | id, account_id, name, type, stage_name, is_closed, is_won, amount, close_date, created_date, last_modified_date, probability, owner_id, lead_source, contract_term_months__c, contract_start_date__c, recurring_arr__c |
| `lead` | One row per direct-sales account | id, account_id, lead_source, status, created_date |
| `user` | The single owning sales user | id, name, email, user_role_name, is_active |

`lead_source` records the enterprise source: `Product Qualified Lead` for PLG seat-threshold leads, and `Inbound` or `Outbound` for direct sales. A direct-sales account that has not signed by 2026-09-30 has no `tailnet_id__c`. Open pipeline with a close date after 2026-09-30 stays open.

## raw_finance (planned, PLAN task b)

- `manual_adjustments`: adjustment_id, account_ref, effective_month, amount_usd, category, reason, entered_by, approved_by, entered_at, _loaded_at. The local generator emits CSV; Fivetran is intended to sync an equivalent Google Sheet.

## raw_truth (audit models only)

| Table | Status | Columns |
|---|---|---|
| `truth_enterprise_contracts` | written | tailnet_id, event_date, event_kind (`close`, `renewal`, `expansion`), enterprise_source (`plg`, `direct`), price_id, contract_start_date, contract_end_date, term_months, seats, discount_pct, recurring_acv |
| `truth_mrr_monthly` | planned (task b) | tailnet_id, month, plan_code, price_version, billing_basis, quantity, mrr_runrate_usd, mrr_billed_usd, is_internal |
| `truth_revenue_monthly` | planned (task b) | tailnet_id, month, revenue_usd |
| `truth_identity` | planned (task b) | tailnet_id, orb_customer_id, stripe_customer_id, salesforce_account_id |
| `defect_manifest` | planned (task b) | defect_id, defect_code, source_table, record_key, injected_at_sim, notes |

Truth references may be read only by models in `models/audit/`. Other marts derive results from raw source tables.

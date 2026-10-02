# Source schemas

`generator/tables.py` is the typed contract for every table: names, columns, primary keys, sort order, and Parquet types. This file documents every table the generator writes; `raw_finance` is still planned. Raw tables are not the scope boundary: dbt stages every landed table, and the marts use only what the story needs.

Conventions:
- The generator writes Parquet to `data/raw/<source>/` and `data/answer_key/truth/`; `make data` then loads every file into DuckDB (`data/seats_to_cash.duckdb`) as `raw_<source>.<table>` and `raw_truth.<table>`.
- A sim day is a business date in America/Los_Angeles; every timestamp converts to that local date (ADR-014).
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

Every table carries `_exported_at`, the export load time. Price IDs are `op_<price_book price_id>_<currency>` (for example `op_v4_standard_usd`); plan IDs are `plan_<plan_code>_<price_version>_<currency>`. Invoiced rows are always USD.

| Table | Grain | Columns | Used by marts |
|---|---|---|---|
| `customers` | Version log per customer | id, external_customer_id (tailnet ID), name, email, currency (`USD`), payment_provider (`stripe`), payment_provider_id, billing_country, created_at, metadata | yes |
| `plans` | One row per plan, version, and price-book currency column | id, external_plan_id, name, price_version, currency, created_at | staged only |
| `prices` | One row per price-book price and currency column | id, plan_id, external_price_id, item_name, model_type, unit_amount, package_size, cadence, billing_timing | staged only |
| `subscriptions` | Version log per subscription term | id, customer_id, plan_id, status (`active`, `ended`), start_date, end_date, net_terms, invoicing_channel (always `stripe`; see disabled options), discount_pct, ended_reason (`voluntary`, `involuntary`, `migrated`, `replaced`), created_at | yes |
| `subscription_quantity_changes` | Append-only | id, subscription_id, price_id, effective_date, quantity, source (`admin`, `scim`, `system`, `auto_seat`, `sales`), recorded_at | staged only |
| `invoices` | Version log per invoice | id, invoice_number, customer_id, subscription_id, status (`issued`, `paid`), currency, invoice_date, issued_at, service_period_start, service_period_end, due_date, paid_at, voided_at, subtotal, discount_total, tax, total, amount_due, external_sync_id (Stripe invoice ID; null for zero-total invoices) | yes |
| `invoice_line_items` | Append-only | id, invoice_id, subscription_id, price_id, line_type (`usage`, `fixed`, `proration`, `discount`), applies_to_line_id, name, start_date, end_date, quantity, unit_amount, amount | yes |
| `credit_notes` | Append-only | id, invoice_id, customer_id, type (`adjustment`), reason (`uncollectible`), total, effective_date, created_at, voided_at | yes |
| `events` | Append-only usage event | id, idempotency_key, event_name (`user_active`), external_customer_id, timestamp, properties | staged only |
| `daily_line_item_revenue` | Line item × service day | revenue_date, invoice_line_item_id, invoice_id, customer_id, price_id, recognized_amount, currency | staged only; may cross-check revenue |

## raw_stripe (Fivetran-shaped)

Amounts are integer cents; `currency` is `usd`. Every table carries `livemode`, `_fivetran_synced`, and `_fivetran_deleted`. Staging keeps only `livemode` rows (D13) that are not `_fivetran_deleted` (D09). Every Orb invoice with a positive total is synced once: the Stripe invoice ID is the Orb `external_sync_id`, and the Stripe customer ID is the Orb customer's `payment_provider_id` (ADR-017).

| Table | Grain | Columns |
|---|---|---|
| `customer` | One row per customer | id, created, email, name, currency, delinquent, description, metadata (JSON: `tailnet_id`, `orb_customer_id`), is_deleted |
| `invoice` | Version log per invoice (`open`, then `paid` or `uncollectible`) | id, customer_id, number, status, billing_reason, collection_method (`charge_automatically`; `send_invoice` for Enterprise), currency, subtotal, tax, total, amount_due, amount_paid, amount_remaining, created, due_date, period_start, period_end, paid, charge_id, metadata (JSON: `orb_invoice_id`, `payment_source` `card` or `ach`), status_transitions_finalized_at, status_transitions_paid_at, status_transitions_marked_uncollectible_at |
| `charge` | Version log per charge (a refund adds a version) | id, customer_id, invoice_id, amount, amount_refunded, currency, created, status (`succeeded`, `failed`), paid, captured, refunded, failure_code, failure_message, payment_method_type (`card`, `us_bank_account`), balance_transaction_id |
| `refund` | One row per refund | id, charge_id, amount, currency, created, reason, status, balance_transaction_id |
| `balance_transaction` | One row per settled charge or refund | id, source (charge or refund ID), type (`charge`, `refund`), amount, fee, net, currency, created, available_on (`created` local date + `payments.payout_lag_days`), status (`available`, `pending`) |

## raw_salesforce (enterprise CRM, Fivetran-shaped)

Every PLG tailnet that reaches the enterprise seat threshold, and every direct-sales account, gets an account and an opportunity. Each table carries `is_deleted` and `_fivetran_synced`.

| Table | Grain | Columns |
|---|---|---|
| `account` | Version log (`Prospect`, then `Customer` at signing) | id, name, website, type, industry, number_of_employees, billing_country, owner_id, created_date, last_modified_date, tailnet_id__c, customer_tier__c |
| `opportunity` | New Business: version log (open, then `Closed Won` at signing). Renewal and Expansion: one `Closed Won` row per contract event. | id, account_id, name, type, stage_name, is_closed, is_won, amount, close_date, created_date, last_modified_date, probability, owner_id, lead_source, contract_term_months__c, contract_start_date__c, recurring_arr__c, purchase_channel__c (`stripe` when won), marketplace_offer_id__c (always null) |
| `lead` | One row per direct-sales account | id, account_id, lead_source, status, created_date |
| `user` | The single owning sales user | id, name, email, user_role_name, is_active |

`recurring_arr__c` on every won opportunity is the contract's total annual value after that event, so the latest won opportunity carries current enterprise ARR (ADR-016). `lead_source` records the enterprise source: `Product Qualified Lead` for PLG seat-threshold leads, and `Inbound` or `Outbound` for direct sales. A direct-sales account that has not signed by 2026-09-30 has no `tailnet_id__c`. Open pipeline with a close date after 2026-09-30 stays open.

## raw_finance (planned, PLAN tier 3)

- `manual_adjustments`: adjustment_id, account_ref, effective_month, amount_usd, category, reason, entered_by, approved_by, entered_at, _loaded_at. The local generator emits CSV; Fivetran is intended to sync an equivalent Google Sheet.

## raw_truth (audit models only)

| Table | Status | Columns |
|---|---|---|
| `truth_enterprise_contracts` | written | tailnet_id, event_date, event_kind (`close`, `renewal`, `expansion`), enterprise_source (`plg`, `direct`), parent_tailnet_id (always null), price_id, currency (`USD`), channel (`stripe`), contract_start_date, contract_end_date, term_months, seats, discount_pct, recurring_acv, services_amount (`0.00`), services_delivery_date |
| `truth_mrr_monthly` | written | tailnet_id, month (first day), plan_code, price_version, billing_basis (`mau`, `seat`, `contract`), quantity, mrr_runrate_usd (rounded to cents), arr_runrate_usd (12 × MRR for `mau` and `seat`; the annual contract value itself for `contract`), mrr_billed_usd (line amounts with service start in the month), is_internal |
| `truth_revenue_monthly` | written | tailnet_id, month, recognized_usd, refunds_usd, credit_notes_usd, revenue_usd (= recognized − refunds − credit notes), is_internal |
| `truth_identity` | written | tailnet_id, orb_customer_id, stripe_customer_id (the canonical customer), salesforce_account_id, is_internal |
| `defect_manifest` | written | defect_id (`D01-00001`), defect_code, source_table (`<source>.<table>`), record_key (the injected or affected row ID), injected_at_sim, notes. D05 rows name a refund or credit note whose load time moved past its period's close. |

Truth references may be read only by models in `models/audit/`.

## finance_close (written by `make close`)

- `close_ledger`: period (`YYYY-MM`), metric, value_usd, as_of_ts (UTC), close_date. Append-only: one row per metric for each posted close (ADR-023). `make close` creates it through a dbt `on-run-start` hook; no generator or dbt model writes it. Other marts derive results from raw source tables.

## Disabled options

These features are outside the project scope. Their generator code remains, but each is switched off in `config/simulation.yml`, and config validation rejects a nonzero value (ADR-012). The table columns they would populate stay in the contracts above with the constant or null values noted.

| Feature | Config switch (must be 0) | Effect on landed tables |
|---|---|---|
| Multi-currency | `population.currencies` EUR and GBP (USD is 1.0) | Every `currency` column is `USD`. The price book's EUR and GBP columns still produce catalog rows in Orb `plans` and `prices`, which no subscription uses. |
| Personal Plus | `personal.plus_upgrade_monthly`, `plus_downgrade_monthly`, `plus_retirement_downgrade_share` | No `personal_plus` subscriptions, plan changes, or invoices. |
| Services | `enterprise.services_attach_rate` | No `one_time` invoice lines; `services_amount` is `0.00`. |
| Marketplace | `enterprise.marketplace_share`, `payments.marketplace_fee_pct` | No `external` invoice status; `invoicing_channel` and `purchase_channel__c` are `stripe`; `marketplace_offer_id__c` is null; customers never change payment provider. |
| Add-ons (tagged resources, Mullvad) | `addons.tagged_resource_overage_share`, `addons.mullvad_attach_rate` | No `addon` invoice lines. `tailnet_activity_daily.tagged_resources` is still measured. |
| Multi-tailnet enterprise | `enterprise.multi_tailnet_share` | No `child` contract events; `parent_tailnet_id` is null. |
| Defects other than the six | `defects.D02_*`, `D04_*`, `D07_*`, `D08_*`, `D10_*`, `D11_*`, `D12_*` | Never injected. |

Bring-to-work facts are kept as data: some business creators ran a personal tailnet first, and their machines can register to both, so `device_registrations.machine_key_hash` links them.

# SCHEMAS: raw table contracts

These are the tables the generator writes and dbt staging reads. Column names follow each vendor's warehouse conventions as closely as practical:

- **Stripe and Salesforce:** Fivetran connector conventions. Before claiming compatibility with Fivetran's packages, diff the headers against the integration-test seed CSVs in `fivetran/dbt_stripe` and `fivetran/dbt_salesforce` and adjust.
- **Product DB:** Fivetran Postgres connector conventions.
- **Orb:** approximates Orb's data export resources. Field names are an assumption (ADR-002).

Conventions for every table:
- Files land at `data/raw/<source>/<table>.parquet`, with `<source>` in {app, orb, stripe, salesforce, finance}, and load into schema `raw_<source>`. `manual_adjustments` is also written as `data/raw/finance/manual_adjustments.csv` for the Google Sheet step.
- Timestamps are UTC, type `timestamp`. Dates are `date`.
- Every raw_app and raw_stripe table carries `_fivetran_synced timestamp` and `_fivetran_deleted boolean`. Salesforce tables carry native `is_deleted boolean` and `_fivetran_synced timestamp`.
- Orb export tables carry `_exported_at timestamp`. Finance files carry `_loaded_at timestamp`.
- Data starts at `sim_start_date` (2023-01-01). The generator sets load timestamps to the business timestamp plus a sync lag from config. D05 rows get a load timestamp after their period's close date. No load timestamp is later than `extract_date` (2026-10-31).
- IDs use vendor-style prefixes and are deterministic from the seed.
- Amounts in Orb tables are decimal strings; tax is always 0 (tax calculation is out of scope).
- `generator/tables.py` holds every table's columns, types, and keys. From task 1.11, the column tables in this file are generated from it; edit `tables.py`, not this file.

### Version logs (ADR-018)

Mutable entities land as version logs, one row per version: `raw_app.tailnets`, `raw_app.users`, `raw_orb.customers`, `raw_orb.subscriptions`, `raw_orb.invoices`, `raw_stripe.customer`, `raw_stripe.invoice`, `raw_stripe.charge`, `raw_salesforce.account`, and `raw_salesforce.opportunity`. Every other table is append-only: each row is written once and never changes.

- Fivetran versioned tables (app, Stripe, Salesforce) add history-mode columns: `_fivetran_start timestamp` (when this version landed; the version timestamp), `_fivetran_end timestamp` (the next version's `_fivetran_start` minus 1 millisecond, or `9999-12-31 23:59:59.999` for the latest), and `_fivetran_active boolean` (true only for the latest). `_fivetran_synced` equals `_fivetran_start`. Raw key: `(id, _fivetran_start)`.
- Orb versioned tables write a new row per change, with `_exported_at` as the version timestamp. Raw key: `(id, _exported_at)`.
- A soft delete (D09) is a final version with `_fivetran_deleted = true` (`is_deleted = true` in Salesforce). This repo keeps the deleted flag in history-mode tables too, so one deletion rule covers every table.
- `_fivetran_active` and `_fivetran_end` describe the log at extract time. As-of reads use only the version timestamp (SPEC 8.1).

## raw_app (product database)

**tailnets** (version log)

| Column | Type | Notes |
|---|---|---|
| id | varchar | `tn_` prefix; PK |
| name | varchar | |
| created_at | timestamp | |
| creator_user_id | varchar | FK users.id |
| signup_domain | varchar | domain of creator's email; drives personal vs business (SPEC 2.4) |
| plan_code | varchar | current plan; matches price_book.plan_code |
| price_version | varchar | v3 or v4 |
| trial_started_at | timestamp | null for personal |
| trial_ended_at | timestamp | |
| currency | varchar | USD, EUR, GBP |
| is_nonprofit | boolean | |
| deleted_at | timestamp | |
| _fivetran_synced | timestamp | |
| _fivetran_deleted | boolean | D09 |

Internal tailnets (D03) are not flagged here; they're identifiable only by `signup_domain = 'wirefern.example'`.

**users** (version log)

| Column | Type | Notes |
|---|---|---|
| id | varchar | `u_`; PK |
| tailnet_id | varchar | |
| email | varchar | |
| role | varchar | owner, admin, billing_admin, member |
| invited_at | timestamp | |
| approved_at | timestamp | null if no approval required |
| first_login_at | timestamp | occupies a seat (SPEC 2.2) |
| removed_at | timestamp | vacates a seat |
| _fivetran_synced, _fivetran_deleted | | |

**seat_events**

| Column | Type | Notes |
|---|---|---|
| id | varchar | PK |
| tailnet_id | varchar | |
| user_id | varchar | null for admin seat-count changes |
| event_type | varchar | seats_set, seat_occupied, seat_vacated, auto_seat_added |
| seats_held_after | integer | |
| seats_occupied_after | integer | |
| actor | varchar | admin, system, scim |
| occurred_at | timestamp | |
| _fivetran_synced, _fivetran_deleted | | |

**plan_changes**

| Column | Type | Notes |
|---|---|---|
| id | varchar | PK |
| tailnet_id | varchar | |
| changed_at | timestamp | |
| from_plan_code, to_plan_code | varchar | |
| from_price_version, to_price_version | varchar | |
| change_source | varchar | self_serve, sales, trial_end, migration_voluntary, migration_forced, dunning |
| _fivetran_synced, _fivetran_deleted | | |

**device_registrations**

| Column | Type | Notes |
|---|---|---|
| id | varchar | PK |
| tailnet_id | varchar | |
| user_id | varchar | null when tagged |
| machine_key_hash | varchar | stable per physical machine across tailnets (SPEC 4.4) |
| os | varchar | macos, windows, linux, ios, android |
| is_tagged | boolean | tagged resource vs user device |
| registered_at, removed_at | timestamp | |
| _fivetran_synced, _fivetran_deleted | | |

**tailnet_activity_daily** (business tailnets)

| Column | Type | Notes |
|---|---|---|
| tailnet_id | varchar | PK part |
| activity_date | date | PK part |
| active_users | integer | |
| user_devices | integer | |
| tagged_resources | integer | drives the tagged-resource add-on above 50 |
| ephemeral_minutes | integer | |
| _fivetran_synced, _fivetran_deleted | | never soft-deleted (D09 skips activity rollups) |

**tailnet_activity_monthly** (personal tailnets): tailnet_id, activity_month (date), active_users, user_devices, _fivetran_synced, _fivetran_deleted.

**feature_usage_daily**

| Column | Type | Notes |
|---|---|---|
| tailnet_id | varchar | PK part |
| activity_date | date | PK part |
| feature | varchar | PK part: ssh, funnel, exit_node, subnet_router, scim, mdm_config, flow_logs, log_streaming, jit_access, posture_integration |
| attempts | integer | |
| gated_blocked | boolean | true when attempted but the current plan lacks the feature (`seeds/plan_entitlements.csv`) |
| _fivetran_synced, _fivetran_deleted | | never soft-deleted (D09 skips activity rollups) |

## raw_orb (billing engine export)

Amounts are decimal strings in the invoice currency.

**customers** (version log): id (PK), external_customer_id (= tailnet_id), name, email, currency, payment_provider (`stripe`, or null for marketplace), payment_provider_id (= Stripe customer id; D01 appends a version pointing at the new customer, so the log keeps the history), billing_country, created_at, metadata (json text), _exported_at.

**plans**: id (PK), external_plan_id (= price_book.plan_code), name, price_version, currency, created_at, _exported_at.

**prices**: id (PK), plan_id, external_price_id (= price_book.price_id), item_name, model_type (unit, package, flat), unit_amount, package_size, cadence (monthly, annual, one_time), billing_timing (in_advance, in_arrears), _exported_at.

**subscriptions** (version log)

| Column | Type | Notes |
|---|---|---|
| id | varchar | PK |
| customer_id | varchar | |
| plan_id | varchar | |
| status | varchar | active, ended, upcoming |
| start_date, end_date | date | |
| net_terms | integer | 0 self-serve, 30 enterprise |
| invoicing_channel | varchar | stripe, aws_marketplace, azure_marketplace |
| discount_pct | varchar | decimal string |
| ended_reason | varchar | voluntary, involuntary, migrated, replaced |
| created_at | timestamp | |
| _exported_at | timestamp | |

**subscription_quantity_changes**: id (PK), subscription_id, price_id, effective_date, quantity, source (admin, auto_seat, sales, system), recorded_at, _exported_at. D12 lags effective_date behind the app DB.

**invoices** (version log: issued, paid, and voided are separate versions)

| Column | Type | Notes |
|---|---|---|
| id | varchar | PK |
| invoice_number | varchar | |
| customer_id | varchar | |
| subscription_id | varchar | |
| status | varchar | draft, issued, paid, void, external (marketplace) |
| currency | varchar | |
| invoice_date | date | the `issued_at` date in America/Los_Angeles |
| issued_at | timestamp | normally 10:00 to 12:00 UTC on the 1st; D04 invoices 23:00 to 23:59 Pacific on the last day of the prior month |
| service_period_start, service_period_end | date | governs month assignment (ADR-009) |
| due_date | date | |
| paid_at, voided_at | timestamp | |
| subtotal, discount_total, tax, total, amount_due | varchar | subtotal = sum of all lines, including negative discount lines; discount_total is informational (minus the sum of discount lines); tax = 0; total = subtotal + tax |
| external_sync_id | varchar | Stripe invoice id; null for marketplace |
| _exported_at | timestamp | |

**invoice_line_items**: id (PK), invoice_id, subscription_id, price_id, line_type (fixed, proration, usage, addon, one_time, discount), applies_to_line_id (the discounted line, for `line_type = discount`; else null), name, start_date, end_date, quantity, unit_amount, amount (negative for discount lines), _exported_at.

**credit_notes**: id (PK), invoice_id, customer_id, type (refund, adjustment), reason, total, effective_date, created_at, voided_at, _exported_at. D05 applies.

**events** (v3 MAU metering): id (PK), idempotency_key, event_name (`user_active`), external_customer_id, timestamp, properties (json text with user_id), _exported_at. One event per active user per tailnet per month, at first activity.

**daily_line_item_revenue**: revenue_date, invoice_line_item_id, invoice_id, customer_id, price_id, recognized_amount, currency, _exported_at. This is Orb's own ratable revenue view. It should reconcile to `fct_revenue_daily` only under the default policy vars; the reconciliation test should skip when vars differ.

## raw_stripe (payments)

Amounts are integers in minor units (cents). Every table has `livemode boolean` where Stripe has it (D13), plus `_fivetran_synced` and `_fivetran_deleted`.

**customer** (version log): id (`cus_`), created, email, name, currency, delinquent, description, metadata (json text with tailnet_id), is_deleted, livemode.

**invoice** (version log)

| Column | Type | Notes |
|---|---|---|
| id | varchar | `in_` |
| customer_id | varchar | |
| number | varchar | |
| status | varchar | draft, open, paid, void, uncollectible |
| billing_reason | varchar | manual (synced from Orb) |
| collection_method | varchar | charge_automatically, send_invoice (enterprise) |
| currency | varchar | |
| subtotal, tax, total, amount_due, amount_paid, amount_remaining | integer | |
| created | timestamp | |
| due_date | timestamp | |
| period_start, period_end | timestamp | |
| paid | boolean | |
| charge_id | varchar | |
| metadata | varchar | json text: orb_invoice_id, payment_source = orb, sync_attempt (D06) |
| status_transitions_finalized_at, status_transitions_paid_at, status_transitions_voided_at | timestamp | |
| livemode | boolean | |

**invoice_line_item**: id (`il_`), invoice_id, amount, currency, description, period_start, period_end, proration (boolean), quantity, type (`invoiceitem`), metadata (json text: orb_line_id, orb_price_id), livemode.

**charge** (version log): id (`ch_` for card, `py_` for ACH), customer_id, invoice_id (null for D11), amount, amount_refunded, currency, created, status (succeeded, failed, pending), paid, captured, failure_code, failure_message, payment_method_type (card, us_bank_account), balance_transaction_id, livemode.

**refund**: id (`re_`), charge_id, amount, currency, created, reason (requested_by_customer, duplicate, fraudulent), status, balance_transaction_id. D05 applies.

**balance_transaction**: id (`txn_`), source (charge or refund id), type (charge, refund, payout, adjustment), amount, fee, net, currency, created, available_on, payout_id, status.

**payout**: id (`po_`), amount, currency, arrival_date, created, status.

## raw_salesforce (CRM)

Every table has `is_deleted boolean` and `_fivetran_synced`. Keep volume small; the real Developer Edition org caps storage at 5 MB, though the generated tables here aren't loaded into it.

**account** (version log)

| Column | Type | Notes |
|---|---|---|
| id | varchar | `001` prefix |
| name | varchar | |
| website | varchar | fallback match key for D02 |
| type | varchar | Prospect, Customer, Former Customer |
| industry | varchar | |
| number_of_employees | integer | |
| billing_country | varchar | |
| owner_id | varchar | FK user |
| created_date, last_modified_date | timestamp | |
| tailnet_id__c | varchar | D02: missing or mistyped |
| customer_tier__c | varchar | |

These fields are written by Hightouch in the real org, not by the generator: seats_purchased__c, seat_utilization__c, arr__c, pql_score__c, migration_risk__c, signals_updated_at__c.

**lead**: id, account_id, lead_source (`Inbound` or `Outbound`), status, created_date, is_deleted, _fivetran_synced. Direct enterprise prospects enter this table before a product tailnet exists.

**opportunity** (version log; D05 late Salesforce changes append a version that edits amount or close_date after the period's close)

| Column | Type | Notes |
|---|---|---|
| id | varchar | `006` |
| account_id | varchar | |
| name | varchar | |
| type | varchar | New Business, Expansion, Renewal |
| stage_name | varchar | |
| is_closed, is_won | boolean | |
| amount | numeric | D08: may include services or the multi-year total |
| close_date | date | |
| created_date, last_modified_date | timestamp | |
| probability | numeric | |
| owner_id | varchar | |
| lead_source | varchar | Salesforce standard LeadSource: `Product Qualified Lead`, `Inbound`, or `Outbound` |
| contract_term_months__c | integer | |
| contract_start_date__c | date | |
| recurring_arr__c | numeric | often blank; derive from line items |
| purchase_channel__c | varchar | direct, aws_marketplace, azure_marketplace |
| marketplace_offer_id__c | varchar | |

**opportunity_line_item**: id, opportunity_id, product_2_id, product_code, quantity, unit_price, total_price, service_date.

**product_2**: id, name, product_code (= price_book.price_id or `ps_services`), family (Subscription, Services), is_active.

**user**: id (`005`), name, email, user_role_name, is_active.

## raw_finance (files and sheets)

Column types for both tables are defined in `generator/tables.py`.

**marketplace_disbursements**: disbursement_line_id (PK), marketplace (aws, azure), report_month, disbursement_date, buyer_account_id, offer_id, product_code, gross_amount, marketplace_fee, net_amount, currency, opportunity_ref (D07), _loaded_at.

**manual_adjustments** (a Google Sheet in production, CSV in dev): adjustment_id, account_ref (tailnet_id or account name; D10), effective_month, amount_usd, category (service_credit, write_off, reclass, waiver), reason, entered_by, approved_by (D10), entered_at, _loaded_at.

## seeds (dbt seeds, also read by the generator)

- `price_book.csv`: committed; the single source of truth for prices. Fixed local list prices in `unit_amount_usd`, `unit_amount_eur`, and `unit_amount_gbp` (ADR-020). `disc_internal` is the 100% discount for D03 internal tailnets.
- `plan_entitlements.csv`: committed; plan_code, price_version, feature, entitled. One row per plan, version, and feature. A gated attempt is using a feature whose row says `entitled = false` for the tailnet's current plan. Trials use Premium's rows for the price version current at trial start.
- `free_email_domains.csv`: one column, `domain`. Built once by the SETUP command from the public HubSpot-derived list.
- `fx_rates.csv` (a dbt seed, not a raw table): rate_date, currency, usd_per_unit, source. One row per calendar day from `sim_start_date` through `end_date` for EUR and GBP (USD is 1). `source` is `ecb` (published that day) or `ecb_carried_forward` (weekend or ECB holiday); every committed rate is real ECB data. Rows dated after `end_date` (late rows up to `extract_date`) convert at the `end_date` rate. Built once by `scripts/fetch_fx.py` from ECB reference rates (EUR base, converted to USD per unit). Fallback: seeded random walk, labeled `source = simulated`.
- `close_calendar.csv`: period, close_date (5th business day of the following month, weekends only, no holidays). Committed; built by `scripts/build_close_calendar.py`. The generator reads it to place D05 rows.

## raw_truth (answer key; audit models only)

- **truth_mrr_monthly**: tailnet_id, month, plan_code, price_version, billing_basis, quantity, mrr_runrate_usd, mrr_billed_usd, is_internal
- **truth_revenue_daily**: tailnet_id, revenue_date, revenue_usd (under default policy vars)
- **truth_identity**: tailnet_id, orb_customer_id, stripe_customer_id (one row per Stripe customer), salesforce_account_id, parent_account_id, enterprise_source (`plg` or `direct` for enterprise; null otherwise)
- **truth_enterprise_contracts**: immutable enterprise close, child, renewal, and expansion facts with tailnet_id, event_date/kind, enterprise_source, parent_tailnet_id, price_id, currency, channel, contract_start/end_date, term_months, seats, discount_pct, recurring_acv, services_amount, and services_delivery_date.
- **truth_bring_to_work**: business_tailnet_id, origin_personal_tailnet_id, person_id, link_observable_by (machine_key, email_localpart, none)
- **truth_migration**: tailnet_id, legacy_plan_code, projected_uplift_pct, migrated_on, migration_type
- **defect_manifest**: defect_id, defect_code (D01 to D13), source_table, record_key, injected_at_sim, notes. D03 rows list the internal tailnet ids, though D03 is generated rather than injected.

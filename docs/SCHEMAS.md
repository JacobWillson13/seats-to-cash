# Source schemas in the focused demo

`generator/tables.py` is the typed contract for names, columns, primary keys, sort order, and Parquet types. All source tables are loaded under `raw_<source>`. Amounts are USD: Orb decimal strings and Stripe integer cents. Timestamps are UTC. This file lists only in-scope tables.

## raw_app (Fivetran-shaped product source)

- `tailnets` (version log): id, name, created_at, creator_user_id, signup_domain, plan_code, price_version, trial_started_at, trial_ended_at, currency (USD), is_nonprofit, deleted_at, Fivetran sync/history columns.
- `users` (version log): id, tailnet_id, email, role, invited_at, approved_at, first_login_at, removed_at, Fivetran sync/history columns.
- `seat_events` (append-only): id, tailnet_id, user_id, event_type, seats_held_after, seats_occupied_after, actor, occurred_at, Fivetran sync columns.
- `plan_changes` (append-only): id, tailnet_id, changed_at, from/to plan and price version, change_source, Fivetran sync columns.
- `device_registrations` (append-only): id, tailnet_id, user_id, machine_key_hash, OS, is_tagged, registered_at, removed_at, Fivetran sync columns.
- `tailnet_activity_daily`: tailnet_id, activity_date, active_users, user_devices, tagged_resources, ephemeral_minutes, Fivetran sync columns.
- `tailnet_activity_monthly`: tailnet_id, activity_month, active_users, user_devices, Fivetran sync columns.
- `feature_usage_daily`: tailnet_id, activity_date, feature, attempts, gated_blocked, Fivetran sync columns.

## raw_orb

- `customers` (version log): id, external_customer_id, name, email, currency, payment_provider, payment_provider_id, billing_country, created_at, metadata, _exported_at.
- `subscriptions` (version log): id, customer_id, plan_id, status, start_date, end_date, net_terms, invoicing_channel, discount_pct, ended_reason, created_at, _exported_at.
- `invoices` (version log): id, invoice_number, customer_id, subscription_id, status, currency, invoice_date, issued_at, service_period_start/end, due_date, paid_at, voided_at, subtotal, discount_total, tax, total, amount_due, external_sync_id, _exported_at.
- `invoice_line_items`: id, invoice_id, subscription_id, price_id, line_type, applies_to_line_id, name, start_date, end_date, quantity, unit_amount, amount, _exported_at.
- `credit_notes`: id, invoice_id, customer_id, type, reason, total, effective_date, created_at, voided_at, _exported_at.

## raw_stripe

- `customer` (version log): id, created, email, name, currency, delinquent, description, metadata, is_deleted, livemode.
- `invoice` (version log): id, customer_id, number, status, billing_reason, collection_method, currency, subtotal, tax, total, amount_due, amount_paid, amount_remaining, created, due_date, period_start/end, paid, charge_id, metadata, status transition timestamps, livemode.
- `charge` (version log): id, customer_id, invoice_id, amount, amount_refunded, currency, created, status, paid, captured, failure fields, payment method, balance transaction ID, livemode.
- `refund`: id, charge_id, amount, currency, created, reason, status, balance_transaction_id.
- `balance_transaction`: id, source, type, amount, fee, net, currency, created, available_on, status.

Every Stripe table includes `livemode`, `_fivetran_synced`, and `_fivetran_deleted` where applicable. D13 rows use test mode and are filtered in staging.

## raw_salesforce

- `account` (version log): id, name, website, type, industry, employee count, billing country, owner_id, created/modified dates, tailnet_id__c, customer_tier__c, is_deleted, _fivetran_synced.
- `opportunity` (version log): id, account_id, name, type, stage_name, is_closed, is_won, amount, close_date, created/modified dates, probability, owner_id, LeadSource, contract term/start, recurring ARR and purchase channel, is_deleted, _fivetran_synced.

Only enterprise sales accounts and opportunities are generated; no reps, product catalog, or opportunity line items are in scope.

## raw_finance

- `manual_adjustments`: adjustment_id, account_ref, effective_month, amount_usd, category, reason, entered_by, approved_by, entered_at, _loaded_at. The local generator emits CSV; Fivetran is intended to sync an equivalent Google Sheet.

## raw_truth (audit models only)

- `truth_mrr_monthly`: tailnet_id, month, plan_code, price_version, billing_basis, quantity, mrr_runrate_usd, mrr_billed_usd, is_internal.
- `truth_revenue_monthly`: tailnet_id, month, revenue_usd.
- `truth_identity`: tailnet_id, orb_customer_id, stripe_customer_id, salesforce_account_id.
- `defect_manifest`: defect_id, defect_code, source_table, record_key, injected_at_sim, notes.

Truth references may be read only by models in `models/audit/`. Other marts derive results from raw source tables.

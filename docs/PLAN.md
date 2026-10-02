# Remaining work plan

Three tiers, in order. Finish each tier completely (tests green, everything pushed) before starting the next; whatever exists at any point must be demoable. Iterate with `config/ci.yml`; run the default config only at tags. After each tag, update `docs/STATUS.md`.

## Tier 1: the spine

- [x] **1. Generator**: Stripe customer, invoice (synced from Orb, metadata `orb_invoice_id` and `payment_source`), charge, refund, and balance_transaction; Salesforce account and opportunity; `truth_mrr_monthly`, `truth_revenue_monthly`, `truth_identity`, and `defect_manifest`; D01, D03, D06, D09, and D13 recorded in the manifest; a DuckDB loader behind `make data`.
  - Accept: truth tables match facts rebuilt independently from the raw sources; the manifest has only planted codes and every record exists; the determinism test passes; `make data` loads every raw schema. Tag `generator-done`.
- [x] **2. dbt on DuckDB** (`profiles.yml` at the repo root): staging for every landed table with D09 and D13 filters and D06 dedupe; internal tailnets (D03) excluded from finance marts; `int_identity` (resolves D01), `int_invoice_lines`, `int_subscription_terms_monthly`; `dim_customer`, `fct_mrr_monthly`, `fct_arr_movements` (with repricing), `fct_revenue_monthly`, `fct_deferred_revenue_rollforward`, `fct_billings_revenue_cash`; `audit_mrr_vs_truth`, `audit_defect_scorecard`, and `scripts/check_truth_fence.py`.
  - Accept: the ARR waterfall closes every month; the deferred revenue rollforward ties; Orb invoice totals equal deduped Stripe totals; Stripe charges minus refunds minus fees equal balance-transaction net; unit tests for proration and the repricing cases pass; `make build` passes. Tag `dbt-done`.
- [x] **3. `make snowflake`**: read `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_PRIVATE_KEY_PATH` from `.env`, load the raw tables with `write_pandas`, and run `dbt build --target snowflake`. The owner runs it locally; exact steps in SETUP.
- [x] **4. Dashboard and README**: `analyses/dashboard/*.sql` in Snowflake syntax for ARR trend, ARR waterfall by movement type, billings vs. revenue vs. cash, deferred revenue, and the defect scorecard; README with real numbers from a default DuckDB run. Tag `demo-v1`.

## Tier 2: stack and finance depth

- [x] **5. Migration exposure and account signals**: `fct_migration_exposure`; `fct_account_signals` (salesforce_account_id, tailnet_id, arr_usd, seats_held, seat_utilization, migration_risk_tier, sync_eligible); a migration-exposure dashboard query.
- [x] **6. LookML**: `lookml/` views for `fct_mrr_monthly` and `fct_arr_movements` plus one explore, parsed with `lkml` in a test.
- [x] **7. Close process**: D05 late refunds and credit notes; `as_of_ts` filters in staging; `make close PERIOD=YYYY-MM` and `make close-history` (2026-04 through 2026-09); `fct_close_ledger` and `fct_restatements`; a restatements dashboard query.
- [ ] **8. CI**: a GitHub Actions workflow running `make test-gen` and `dbt build` on DuckDB with `config/ci.yml`. Update the README and tag `demo-done`.

## Tier 3: if time remains

- [ ] **9.** The `manual_adjustments` CSV, shaped for a Fivetran-synced Google Sheet.
- [ ] **10.** A unit test for an annual invoice spanning 2024-02-29.
- [ ] **11.** The audit's test gaps: a direct test that trials get no invoices, and an uncollectible credit-note check per unpaid invoice.

# Remaining work plan

Work only on `main`. Finish the tasks in order, commit and push after each task, and run `git pull --rebase origin main` before every push. Tags are `generator-done`, `dbt-done`, and `demo-done`.

## 4b. Generator remainder

- [ ] **Generator sources and truth**: reduce raw output to in-scope Orb tables; add Stripe customer, invoice, charge, refund, and balance transaction; Salesforce enterprise account and opportunity; the manual-adjustments CSV; the six specified defects; the four answer-key tables; invariant tests; and the DuckDB loader.
  - Accept: only six defect codes occur; clean generation precedes injection; truth tables match independently reconstructed facts; all foreign keys, amounts, and timestamps validate; offline generation and two-run byte determinism pass; `make data` loads every raw table and prints counts.
  - Commit, push, then tag `generator-done`.

## 4c. dbt on DuckDB

- [ ] **Sources and staging**: dbt project, DuckDB/Snowflake profiles, source declarations and staging for every in-scope table. Every staging model honors `as_of_ts` using source load time for append-only rows and creation time for entities. Add shared seeds and cross-database macros.
  - Accept: `dbt deps`, `dbt debug`, staging key tests, deleted/test-mode filtering, and as-of fixtures pass.
- [ ] **Identity and finance intermediates**: `int_identity`, `int_invoice_lines`, and `int_subscription_terms_monthly`.
  - Accept: D01 resolves to one Stripe customer per tailnet; line classification and monthly subscription terms reconcile to source facts.
- [ ] **Finance marts and audits**: `dim_customer`, `fct_mrr_monthly`, `fct_arr_movements`, `fct_revenue_monthly`, `fct_deferred_revenue_rollforward`, `fct_billings_revenue_cash`, `audit_mrr_vs_truth`, and `audit_defect_scorecard`.
  - Accept: monthly ARR waterfall closes; MRR matches truth to the cent outside manifested defect rows; invoice totals tie to deduplicated Stripe; charges less refunds and fees tie to balance-transaction net; deferred revenue ties; truth-fence check passes.
- [ ] **dbt tests and CI**: unit tests for proration, price-volume repricing, and a 2024-02-29 annual invoice; GitHub Actions builds a small DuckDB configuration.
  - Accept: `make build` and required SQL lint pass locally and in CI. Commit, push, tag `dbt-done`.

## 4d. Close and outputs

- [ ] **Close history and restatements**: `make close PERIOD=YYYY-MM`, `make close-history` for 2026-04 through 2026-09, `fct_close_ledger`, and `fct_restatements` with late-row reasons.
  - Accept: late refunds or credit notes restate affected periods; re-closing without `FORCE=1` is refused.
- [ ] **Migration exposure and Salesforce signals**: `fct_migration_exposure` and `fct_account_signals` with required fields and eligibility.
  - Accept: projected MRR and risk tiers are reproducible; a local sync dry run includes only eligible accounts.
- [ ] **LookML**: views for MRR and ARR movements and one explore.
  - Accept: `lkml` parses all LookML files.

## 4e. Snowflake

- [ ] **Snowflake run**: if `.env` contains `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_PRIVATE_KEY_PATH`, load Parquet with `write_pandas` and run `dbt build --target snowflake`; otherwise record the skip in `docs/STATUS.md` and continue.
  - Accept: Snowflake dbt build passes when credentials are available; no credentials or private keys enter git.

## 4f. Dashboard and README

- [ ] **Dashboard SQL and README**: one query per tile for ARR trend, ARR waterfall, billings/revenue/cash, deferred revenue, restatements, defect scorecard, and migration exposure. Rewrite README with project story, measured results, DuckDB `make demo`, architecture, decisions, and first questions.
  - Accept: every query runs on DuckDB; README contains only measured numbers and working local commands. Commit, push, tag `demo-done`.

# Remaining work plan

Only remaining tasks are listed, in order. Commit and push after each task, run `git pull --rebase origin main` before every push, and add a `docs/STATUS.md` update after each tag. Tags are `generator-done`, `dbt-done`, and `demo-done`.

## a. Finish Orb billing

- [ ] **Close the billing test gaps from the audit**: assert directly that no trial tailnet gets an Orb subscription or invoice during its trial, and check each `uncollectible` credit note against its invoice (unpaid at the churn date, same customer, total equal to the invoice total).
  - Accept: both assertions run on the CI config and pass; `make test-gen` and `make lint` pass.

## b. Rest of the generator

- [ ] **Stripe, Finance, answer key, defects, and loader**: add Stripe customer, invoice, charge, refund, and balance transaction from Orb invoices and recorded payment outcomes; the Finance `manual_adjustments.csv`; `truth_mrr_monthly`, `truth_revenue_monthly`, `truth_identity`, and `defect_manifest`; injection of D01, D05 (late refunds and credit notes), D06, D09, and D13 after clean generation, with manifest rows for those five and for D03; invariant tests; and the DuckDB loader so `make data` loads every raw and truth table and prints counts. Add a `make` determinism target.
  - Accept: only the six defect codes occur; clean generation precedes injection; truth tables match independently reconstructed facts; all foreign keys, amounts, and timestamps validate; offline generation and two-run byte determinism pass; `make data` loads every table into DuckDB and prints counts; SCHEMAS lists every table the generator writes.
  - Commit, push, then tag `generator-done`.

## c. dbt core on DuckDB

- [ ] **Sources and staging**: dbt project, DuckDB and Snowflake profiles (secrets from `.env`), sources and staging for every landed table, shared seeds, and cross-database macros. Every staging model honors `as_of_ts`, using load time for append-only rows and creation time for entities; `raw_app` version logs keep their version logic. Log dbt and SQLFluff in the DECISIONS dependency log.
  - Accept: `dbt deps`, `dbt debug`, staging key tests, deleted and test-mode filtering, and as-of fixtures pass.
- [ ] **Identity and finance intermediates**: `int_identity`, `int_invoice_lines`, and `int_subscription_terms_monthly`.
  - Accept: D01 resolves to one Stripe customer per tailnet; line classification and monthly subscription terms reconcile to source facts.
- [ ] **Finance marts, reconciliations, and audits**: `dim_customer`, `fct_mrr_monthly`, `fct_arr_movements` (with repricing), `fct_revenue_monthly`, `fct_deferred_revenue_rollforward`, `fct_billings_revenue_cash`, `audit_mrr_vs_truth`, `audit_defect_scorecard`, and `scripts/check_truth_fence.py`.
  - Accept: the monthly ARR waterfall closes; MRR matches truth to the cent outside manifested defect rows; invoice totals tie to deduplicated Stripe; charges less refunds and fees tie to balance-transaction net; deferred revenue ties; the truth-fence check passes.
- [ ] **dbt unit tests and CI**: unit tests for proration, price-volume repricing, and a 2024-02-29 annual invoice; a `make build` target; GitHub Actions builds the `config/ci.yml` dataset on DuckDB.
  - Accept: `make build`, the truth-fence check, and SQLFluff pass locally and in CI. Commit, push, tag `dbt-done`.

## d. Close and outputs

- [ ] **Close history and restatements**: `make close PERIOD=YYYY-MM`, `make close-history` for 2026-04 through 2026-09, `fct_close_ledger`, and `fct_restatements` with late-row reasons.
  - Accept: late refunds or credit notes restate affected periods; re-closing without `FORCE=1` is refused.
- [ ] **Migration exposure and account signals**: `fct_migration_exposure` and `fct_account_signals` with the required fields and sync eligibility.
  - Accept: projected MRR and risk tiers are reproducible; a local sync dry run includes only eligible accounts.
- [ ] **LookML**: views for MRR and ARR movements and one explore. Log lkml in the dependency log.
  - Accept: `lkml` parses all LookML files.

## e. Snowflake

- [ ] **`make snowflake`**: load Parquet with `write_pandas` and run `dbt build --target snowflake`, reading `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_PRIVATE_KEY_PATH` from `.env`. The owner runs it locally; an agent session without credentials implements the target and records the skip in `docs/STATUS.md`.
  - Accept: the target exists and fails clearly without credentials; the owner's local Snowflake build passes; no credentials or private keys enter git.

## f. Dashboard SQL and README

- [ ] **Dashboard SQL, README, and `make demo`**: one query per tile for ARR trend, ARR waterfall, billings/revenue/cash, deferred revenue, restatements, defect scorecard, and migration exposure. Add `make demo`. Rewrite README with the project story, measured results, the DuckDB demo command, architecture, decisions, and first questions.
  - Accept: every query runs on DuckDB; README contains only measured numbers and working local commands. Commit, push, tag `demo-done`.

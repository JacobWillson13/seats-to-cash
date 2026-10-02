# PLAN: seats-to-cash

Four days, 8 to 10 focused hours each. Work top to bottom. A task is done only when its acceptance criteria pass and `make build` is green. In Phase 1, before dbt exists, the gate is `make test-gen` plus the task's acceptance checks; `make build` applies from task 2.1.

Priority tags: **[M]** must ship, **[S]** should ship, **[C]** could ship.

**Cut order if behind:** 4.3 LookML, 4.6 Funnel mirror, 3.7 Fivetran, 3.6 Hightouch, 3.5 Snowflake, 3.4 legacy refactor. Never cut an [M] task.

**Three-day version:** Day 4 becomes 4.1 (PQL optional), 4.2 with three pages (ARR, close, data quality), 4.4, 4.5, and 4.7.

## Phase 0: Pre-flight (1 hour, before Day 1)

- [x] 0.1 [M] Create the GitHub repo `seats-to-cash` (private while building, public at the end) and copy these files in.
- [ ] 0.2 [M] Install the local toolchain (SETUP section 1).
- [ ] 0.3 [S] Create the Salesforce Developer Edition, Hightouch, and Fivetran accounts now so signup approvals don't block Day 3. Do not start the Snowflake trial yet; its 30-day clock should run through your interviews.
- [ ] 0.4 [M] Keep Wirefern or pick another name. Search it first to confirm it isn't a real company.

## Phase 1, Day 1: Generator

Kickoff prompt for Claude Code:

> Read CLAUDE.md, docs/SPEC.md sections 2 to 5, and docs/SCHEMAS.md. Then do PLAN tasks 1.1 to 1.3 only. Before writing billing code, show me the module layout and the state machine transition table with the config keys each transition uses.

- [x] 1.1 [M] Scaffold: uv project, `generator/` package, Makefile targets `setup`, `data`, and `test-gen`, pre-commit with ruff, `.gitignore`, `.env.example`.
  - Accept: `make setup` works on a fresh clone and `python -m generator --help` prints usage.
  - Note: pre-commit hooks are local and call `uv run ruff`, so the lockfile pins one ruff version for hooks and `make lint`. Ruff's banned-api rule (TID251) blocks the wall clock, stdlib `random`, `uuid4`, and `np.random.seed`, enforcing the determinism rule at lint time.
- [x] 1.2 [M] Config and seeds: a pydantic model for `config/simulation.yml` that cross-checks duplicated values (price book dates, forced migration date); `config/ci.yml` at 10% scale; a price book loader with `list_price(plan_code, date)` for new sales and `price(price_id)` for existing subscriptions; loaders for `seeds/plan_entitlements.csv`; `seeds/free_email_domains.csv` (SETUP 1.3); `scripts/fetch_fx.py` writing `seeds/fx_rates.csv` from 2023-01-01, with a seeded random-walk fallback; `scripts/build_close_calendar.py` writing `seeds/close_calendar.csv`.
  - Accept: an invalid config fails with a clear message; a price lookup by (plan_code, date) returns v3 on 2026-04-07 and v4 on 2026-04-08; the close calendar has every period from 2023-01 through 2026-09 on the 5th weekday of the following month.
  - Note: `fx_rates.csv` runs through `end_date` and holds only real ECB data; weekends and ECB holidays carry the last rate (`ecb_carried_forward`). The seeded walk exists only for `--offline` scratch builds and can't overwrite the committed seed.
  - Note: added `python -m generator --check` (validate config and seeds, then exit), `scripts/build_free_email_domains.py`, and `make seeds`. `ci.yml` is an `extends:` overlay rather than a copy (ADR-022). The cross-check also confirms that the last close date plus the longest late-row lag fits before `extract_date`.
- [ ] 1.3 [M] Population and lifecycle: people, companies, domains, and tailnets; the state machine in SPEC 4.2; the planted mechanisms in SPEC 4.3.
  - Accept: monthly counts of signups, trials, conversions, and churn print as a table and look plausible; the bring-to-work share is near the config value.
- [ ] 1.4 [M] Seats and activity: users, approvals, logins, the seat ledger with auto seats, daily activity, feature usage with gated attempts, and device registrations with machine keys.
  - Accept: seats held >= occupied on every tailnet-day; the utilization distribution has a visible low tail.
- [ ] 1.5 [M] Orb billing: customers, plans, prices, subscriptions, quantity changes, invoices on the 1st, proration lines on the next invoice, v3 MAU arrears billing with 3 free users, enterprise annual invoices with services, add-ons, nonprofit discounts, credit notes, MAU events, daily line-item revenue, and marketplace subscriptions with `status = external` invoices. The migration month emits both the final v3 invoice and the first v4 invoice.
  - Accept: lines sum to subtotals; a hand-built case (a seat added on the 16th of a 30-day month) prorates to exactly 15/30 of the seat price.
- [ ] 1.6 [M] Stripe: customers, synced invoices with metadata, invoice lines, card and ACH charges, failures and retries, refunds, balance transactions with fees, and daily payouts.
  - Accept: charges minus refunds minus fees equals the sum of balance transaction net; every non-external Orb invoice with total > 0 has exactly one Stripe invoice.
- [ ] 1.7 [S] Salesforce: reps, products, accounts for business tailnets with `crm.account_seat_threshold` (10) or more seats or enterprise contracts, and opportunities (new, expansion, renewal, lost) with line items.
  - Accept: every enterprise Orb subscription has a Closed Won opportunity.
- [ ] 1.8 [M] Finance: monthly marketplace disbursements net of fees, and the manual adjustments sheet (Parquet plus the CSV export). The close calendar is a seed from task 1.2.
- [ ] 1.9 [M] Defects: inject D01, D02, and D04 to D13 at config rates after clean generation, and write `defect_manifest`. D03 is generated in the population; the manifest lists its internal tailnet ids.
  - Accept: manifest counts are within 10% of rate x denominator (SPEC 5), with a floor of plus or minus 3 rows; `--no-defects` produces a clean dataset for debugging and sets `internal_tailnets` to 0.
- [ ] 1.10 [M] Answer key and invariants: write `raw_truth` tables from the clean simulation; pytest covers every invariant in SPEC 4.6.
  - Accept: `make test-gen` is green; two runs with SEED=42 produce identical file hashes.
- [ ] 1.11 [M] Loader: Parquet into the DuckDB raw schemas; `make data SEED=42` runs end to end. Regenerate the column tables in SCHEMAS.md from `generator/tables.py` so they can't drift.
  - Accept: finishes in under 5 minutes and prints row counts per table. Hand-check five customers against the answer key (one v4 seat, one v3 MAU, one migrated, one enterprise, one marketplace) and record the results under this task.

## Phase 2, Day 2: Core finance models

Kickoff prompt:

> Read CLAUDE.md, SPEC sections 6 to 8, and DECISIONS.md. Do tasks 2.1 to 2.3. Use cross-database macros everywhere; every model must also run on Snowflake later.

- [ ] 2.1 [M] dbt init: `dbt_project.yml` with the vars in SPEC 8.7, and a check in `generator/config.py` that `reporting_tz` and `reporting_start_date` match their config duplicates; profiles for `dev` (DuckDB) and `snowflake`, packages `dbt_utils` and `audit_helper`, `.sqlfluff`, and groups `finance`, `growth`, and `audit`.
  - Accept: `dbt debug` and `dbt deps` pass.
- [ ] 2.2 [M] Sources and staging: `sources.yml` for every raw table with freshness and descriptions; staging per SCHEMAS.md, including deleted and test-mode filters and the `as_of_filter` and `as_of_latest` macros (SPEC 8.1); seeds loaded.
  - Accept: staging primary keys are unique and not null; versioned tables resolve to one row per key at any `as_of_ts`; D09 and D13 rows are gone; D06 duplicates are flagged, not yet removed.
- [ ] 2.3 [M] `int_identity_spine` and `int_unmatched_identities`.
  - Accept: "each Stripe customer maps to one tailnet" passes after handling D01; the unmatched queue holds the D02 accounts the fallback couldn't resolve.
- [ ] 2.4 [M] `int_seat_ledger_daily` and `int_subscription_terms_monthly`.
- [ ] 2.5 [M] `int_invoice_lines_unified` with line classification; internal tailnets excluded (D03).
- [ ] 2.6 [M] `fct_mrr_monthly` (run-rate and billed), `dim_customer`, `dim_plan_version`, `dim_date`.
  - Accept: `audit_mrr_vs_truth` reports the match rate. Target: 100% of customer-months to the cent, excluding keys in the defect manifest.
- [ ] 2.7 [M] `fct_arr_movements` with the repricing decomposition (SPEC 6.1) and FX.
  - Accept: waterfall reconciliation passes at portfolio and customer-month level; repricing unit tests pass.
- [ ] 2.8 [M] `int_revenue_schedule`, `fct_revenue_daily`, `fct_deferred_revenue_rollforward`.
  - Accept: the rollforward ties every month; revenue matches truth under default vars; switching `refund_treatment` changes period totals but not lifetime totals.
- [ ] 2.9 [M] Every unit test listed in SPEC 8.3.
- [ ] 2.10 [M] Audit models, `audit_defect_scorecard`, `scripts/check_truth_fence.py`, and `make scorecard`.
  - Accept: the scorecard prints injected, detected, and handled counts per defect code.
- [ ] 2.11 [S] CI with GitHub Actions on pull requests and main: `make setup`, `make data` with `config/ci.yml`, `dbt build`, the fence check, and SQLFluff lint. On main, publish dbt docs to GitHub Pages.
  - Accept: a green badge in the README and a working docs URL.

## Phase 3, Day 3: Close process and their stack

Kickoff prompt:

> Read SPEC 8.5 and 8.6 and DECISIONS ADR-011 and ADR-012. Do tasks 3.1 to 3.3.

- [ ] 3.1 [M] Close process: `make close PERIOD=` (reading `seeds/close_calendar.csv` from 1.2), `fct_close_ledger`, `fct_restatements`, `make close-history`, and `close_summary`.
  - Accept: after `make close-history`, restatements exist for periods with D05 rows, each with a reason; re-closing a closed period is refused without `FORCE=1`.
- [ ] 3.2 [M] `fct_bookings_to_cash` with the AR rollforward test.
  - Accept: `analyses/trace_customer.sql` traces one enterprise customer from opportunity to invoice to revenue to cash in a single query.
- [ ] 3.3 [S] `fct_pricing_migration_exposure` with the portfolio summary.
  - Accept: report the share of answer-key high-uplift accounts that land in the High tier.
- [ ] 3.4 [S] Legacy refactor. Write `legacy/legacy_arr_report.sql`: one 250 to 300 line query in the style of an inherited analyst report (nested subqueries, hardcoded plan IDs, magic numbers) with exactly three planted bugs: it counts proration as MRR, buckets billings by invoice issue date, and includes internal tailnets. Compare it to `fct_mrr_monthly` with `audit_helper.compare_queries` and write up the result in `docs/LEGACY_REFACTOR.md`.
  - Accept: the doc shows the match percentage and attributes every mismatch to one of the three bugs.
- [ ] 3.5 [S] Snowflake. Start the trial now. Follow SETUP section 2; `make snowflake` loads raw, builds, and runs `scripts/parity_check.py` (row counts and monthly sums for every mart, DuckDB vs Snowflake, exact match).
  - Accept: the parity check passes; a screenshot of the query history is saved in `docs/img/`.
- [ ] 3.6 [S] Hightouch. Create the Salesforce custom fields (SETUP 3), then sync 1, `fct_account_signals` to Account as an upsert on `tailnet_id__c` (limit to enterprise and High-risk accounts to stay under 5 MB), and sync 2, `close_summary` to Slack.
  - Accept: a screenshot of a Salesforce Account page showing the synced fields is saved in `docs/img/`.
- [ ] 3.7 [C] Fivetran: the "Finance manual adjustments" Google Sheet to Snowflake `raw_finance.manual_adjustments` through the Google Sheets connector. The DuckDB path keeps reading the CSV.

## Phase 4, Day 4: Growth and the story

Kickoff prompt:

> Read SPEC 8.4 and 9. Do task 4.1, then scaffold the Evidence project for 4.2.

- [ ] 4.1 [M] `int_person_links`, `fct_plg_funnel`, `fct_bring_to_work`, the PQL score, and `fct_account_signals`.
  - Accept: bring-to-work precision and recall against the answer key, reported separately for machine-key and email-local-part matching; PQL top-decile conversion lift reported.
- [ ] 4.2 [M] Evidence report with the five pages in SPEC 9 and the synthetic-data footer.
  - Accept: `make report` builds the static site, deployed to GitHub Pages under `/report/`.
- [ ] 4.3 [C] LookML: 3 views, 1 explore, 1 model, with an `lkml` parse check in CI. dbt2looker can scaffold views; expect to fix its output.
- [ ] 4.4 [M] Final README with every placeholder replaced by a real number, final DECISIONS.md, and a Known limitations section.
- [ ] 4.5 [M] Record the Loom (script below) right after a fresh `make demo`, so the numbers on screen match the README.
- [ ] 4.6 [C] Funnel mirror of the report from the home server (SETUP 7). GitHub Pages stays the primary link.
- [ ] 4.7 [M] Final QA: fresh clone on a second machine, `make demo` in under 10 minutes, every link works, no secrets in history, and the repo set to public.

### Loom script (4 minutes)

- 0:00 The three questions, and that everything is synthetic.
- 0:30 Architecture in one picture: sources in Fivetran and Orb shapes, dbt layers, Evidence, Hightouch.
- 1:00 The ARR waterfall: why repricing is its own bar and what that changes about 2026 growth.
- 1:45 Close: run `make close` and show a restatement caused by a late refund, with its reason.
- 2:30 The defect scorecard: what the tests catch, the one they miss, and why.
- 3:15 Bring-to-work, and the Salesforce field Hightouch keeps current.
- 3:45 What I'd look at first on a real team.

## Daily exit checks

- Day 1: `make data` is deterministic; five hand checks recorded under 1.11.
- Day 2: `make build` is green; the waterfall and rollforward tie; the scorecard runs.
- Day 3: close history with restatements; Snowflake parity passes, or a note explains why it was cut.
- Day 4: a fresh-clone demo in under 10 minutes; README numbers filled in; Loom recorded.

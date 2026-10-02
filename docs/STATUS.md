# Repo status audit

Audit date: 2026-10-02. Audited commit: `0dd4570` (`docs: focus scope`). This was an audit only. No code, config, test, or doc file other than this one was changed.

Short version: the generator covers raw_app, enterprise Salesforce, and Orb billing, and it is healthy: 72 of 72 tests pass, lint is clean, and output is byte-deterministic. The docs were narrowed to the focus scope in `0dd4570`, but the code was not. It still generates EUR/GBP, marketplace, services, Mullvad, tagged resources, Personal Plus, multi-tailnet enterprise, and bring-to-work. Stripe, Finance, defects, the four answer-key tables, the DuckDB loader, and everything from dbt onward are not started. The next PLAN task is **4b Generator sources and truth**, and none of its acceptance criteria are met yet.

---

## 1. Git integrity

| Item | Value |
|---|---|
| Current branch | `claude/loving-carson-lrqdxj` (session branch, same commit as main) |
| HEAD | `0dd457073faef83d986cb129b1f9b3fb5c481717` |
| `main` vs `origin/main` | Equal (`0dd4570`) |
| Local branches | `main`, `claude/loving-carson-lrqdxj` |
| Remote branches | `origin/main`. `git fetch --prune` deleted a stale `origin/claude/loving-carson-lrqdxj`. The remote also has `refs/pull/1/head` → `8c86f1d`, which is already merged. |
| Tags | None. PLAN's `generator-done`, `dbt-done`, and `demo-done` have not been created. |
| Working tree | Clean before the audit, except as noted under §2 |

### Last 30 commits on main (the whole history has 17)

```
0dd4570          docs: focus scope
8d9e8c1 [MERGE]  Merge generator billing work        (parents eefa790, e81857c)
e81857c [MERGE]  Merge generator billing work        (parents e9606bd, eefa790)
eefa790          wip: complete orb billing and focus-scope transition
0175c1a          gen: add direct enterprise sales and pooled calibration
e9606bd [MERGE]  Merge pull request #1 from JacobWillson13/gen/complete-1-3-1-4
8c86f1d          docs: AGENTS.md symlink to CLAUDE.md
7b4803d          docs: design Orb billing and migration invoices
454055f          gen: validate seats activity and raw history
d89e964          gen: complete population and lifecycle simulation
20c9275          gen: cap fx seed at end_date with ECB data only; guard seeds from make data
6a9d93e          gen: config validation, price book, seed loaders and builders
23676e5          gen: scaffold uv project, generator package, Makefile, pre-commit
cbd23da          docs: resolve review items
208000a          docs: initial spec and scaffold
```

Notes:
- `e81857c` and `8d9e8c1` are two merges with no content. The tree diff from `eefa790` to `8d9e8c1` is empty. They are leftovers from the interrupted session and do no harm.
- `eefa790` is a `wip:` commit, so it does not follow the `<area>: <change>` style. It added `billing_orb.py` (979 lines) and its tests, and it also edited the docs during the move to the focus scope.
- `data/reports/calibration.md` is tracked in git even though `.gitignore` ignores `data/`. It was force-added in `0175c1a` and `eefa790`. See §2.

### Required commits

All ten exist and are ancestors of `main`: `cbd23da`, `23676e5`, `6a9d93e`, `d89e964`, `454055f`, `7b4803d`, `0175c1a`, `eefa790`, `e81857c`, `8d9e8c1`. **None are missing.**

### Commits on remote branches that are not on main

None. `git log --all --not main` is empty, and `refs/pull/1/head` (`8c86f1d`) is an ancestor of main.

---

## 2. Health

| Check | Result |
|---|---|
| `uv sync` | Pass (exit 0) |
| `make test-gen` | **72 passed, 0 failed, 0 skipped** in 138.7 s |
| `make lint` | Pass: `ruff check` reports all checks passed, and `ruff format --check` reports 48 files already formatted |
| `make data CONFIG=config/ci.yml` | Pass, 8.6 s total |
| `make data SEED=42` (default config) | Pass, 36.4 s total |
| Determinism target | **No `make` target exists.** Pytest `test_ci_parquet_is_byte_identical_across_hash_seeds` covers CI scale and passed. I also checked by hand: the default config with seed 42, run again with `PYTHONHASHSEED=123` into a separate directory, gave **23 of 23 Parquet files byte-identical**. |

Test files: `test_cli` 3, `test_config` 18, `test_enterprise_sales` 2, `test_generation_acceptance` 2, `test_offline` 7, `test_orb_billing` 10, `test_population_lifecycle` 5, `test_pricebook` 10, `test_seats_and_raw` 6, `test_seeds` 9.

**Side effect:** every `make data` rewrites the tracked `data/reports/calibration.md`. It changes the stage-timing table, which is wall-clock timing, so the working tree becomes dirty. I restored the file with `git checkout` after the audit.

### Default run (`config/simulation.yml`, seed 42): tables written

Everything is written as Parquet under `data/raw/<source>/` and `data/answer_key/truth/`. **Nothing is loaded into DuckDB**: there is no loader and no `data/seats_to_cash.duckdb`. The "schema" below is the label the CLI prints.

| schema.table | rows |
|---|---:|
| raw_app.tailnets | 32,769 |
| raw_app.users | 115,050 |
| raw_app.seat_events | 3,663 |
| raw_app.plan_changes | 4,689 |
| raw_app.device_registrations | 209,172 |
| raw_app.tailnet_activity_daily | 521,986 |
| raw_app.tailnet_activity_monthly | 453,940 |
| raw_app.feature_usage_daily | 479,792 |
| raw_salesforce.user | 1 |
| raw_salesforce.account | 206 |
| raw_salesforce.lead | 32 |
| raw_salesforce.opportunity | 206 |
| raw_truth.truth_enterprise_contracts | 111 |
| raw_orb.customers | 28,082 |
| raw_orb.plans | 39 |
| raw_orb.prices | 42 |
| raw_orb.subscriptions | 3,151 |
| raw_orb.subscription_quantity_changes | 1,224 |
| raw_orb.invoices (version log; 23,919 distinct IDs) | 47,643 |
| raw_orb.invoice_line_items | 26,733 |
| raw_orb.credit_notes | 180 |
| raw_orb.events | 135,899 |
| raw_orb.daily_line_item_revenue | 834,525 |

Stage timings (seconds): population 2.55, personal lifecycle 0.11, business lifecycle/seats/activity 6.70, direct sales lifecycle and activity 3.90, personal activity and devices 0.07, render raw_app 1.94, write raw_app Parquet 3.98, render enterprise Salesforce and truth 0.35, write enterprise Salesforce and truth Parquet 0.02, render Orb billing 13.75, write raw_orb Parquet 2.97. **Total 36.35.**

The CI run wrote the same 23 tables, for example raw_app.tailnets 3,294, raw_orb.invoices 4,859, raw_orb.invoice_line_items 2,847, and raw_salesforce.account 16. Its total time was 8.62 s.

What the default Orb output contains:
- Invoice currencies: USD 20,540, EUR 2,286, GBP 1,093.
- Subscription channels: stripe 2,075, aws_marketplace 12, azure_marketplace 1.
- Out-of-scope line items: Personal Plus fixed 8,187, Mullvad 829, tagged resources 124, professional services 22.
- Subscriptions: 642 `personal_plus`.

The CLI still prints "payments and finance stages arrive with PLAN 1.6 to 1.8", which uses the old PLAN numbering.

---

## 3. Scope matrix

### In scope

| Item | Implemented | Tested | Paths |
|---|---|---|---|
| Personal free, never billed | yes | yes (no `plan_personal_v*` subscriptions) | `generator/lifecycle.py`, `generator/billing_orb.py`, `tests/generator/test_orb_billing.py::test_lifecycle_cadence_and_no_trial_invoices` |
| v3 Starter/Premium MAU arrears, 3 free users | yes | yes (worked examples 2 and 3, plus the required-invoice invariant) | `generator/billing_orb.py`, `generator/activity.py`, `tests/generator/test_orb_billing.py` |
| v4 Standard/Premium seats in advance | yes | yes | `generator/billing_orb.py`, `generator/seats.py` |
| v4 proration (next-invoice, remaining days) | yes | yes (example 1, `test_first_day_addition_after_invoice_is_prorated_next_month`) | same |
| Auto seats | yes | yes (`test_full_seat_auto_adds_and_departure_reuses_vacancy`) | `generator/seats.py`, `tests/generator/test_seats_and_raw.py` |
| Enterprise annual invoices | yes | yes (default-scale anniversary test) | `generator/billing_orb.py`, `generator/enterprise.py`, `test_orb_billing.py::test_default_enterprise_annual_cadence_marketplace_and_runtime` |
| Enterprise PLG source plus direct-sales source | yes | yes | `generator/lifecycle.py`, `generator/simulate.py`, `generator/enterprise.py`, `tests/generator/test_enterprise_sales.py` |
| Nonprofit discount (separate linked negative line) | yes | yes (example 2, `applies_to_line_id` check) | `generator/billing_orb.py`, `seeds/price_book.csv` (`disc_nonprofit`) |
| USD only | **no**: EUR and GBP are generated and billed | No. The test asserts the currency is in USD/EUR/GBP. | `generator/population.py:23`, `generator/billing_orb.py`, `config/simulation.yml:19` |
| raw_app (8 tables) | yes | yes (schema, sort, references, version-log replay) | `generator/app_db.py`, `generator/tables.py`, `tests/generator/test_seats_and_raw.py` |
| raw_orb: the 5 required tables | yes, but **10** tables are written | yes | `generator/billing_orb.py`, `generator/tables.py` |
| raw_stripe: 5 tables | no | no | — |
| raw_salesforce: account, opportunity | yes, plus out-of-scope `user` and `lead` | yes | `generator/salesforce_enterprise.py`, `tests/generator/test_enterprise_sales.py` |
| raw_finance.manual_adjustments | no | no | — |
| D01 duplicate Stripe customer | no (config rate only) | no | `config/simulation.yml:139` |
| D03 internal tailnets | partial: generated as population on `wirefern.example` with a 100% internal discount; no manifest row | no direct test | `generator/population.py`, `generator/billing_orb.py:141` |
| D05 late refunds/credit notes | no (only the close-calendar reference) | no | `generator/reference.py:116`, `config/simulation.yml:143` |
| D06 duplicate Stripe sync | no | no | `config/simulation.yml:144` |
| D09 soft deletes | no: `deleted_at` is always null and `is_deleted` is always False | no | `generator/app_db.py:186`, `generator/salesforce_enterprise.py` |
| D13 Stripe test-mode rows | no | no | `config/simulation.yml:152` |
| truth_mrr_monthly | no | no | — |
| truth_revenue_monthly | no | no | — |
| truth_identity | no | no | — |
| defect_manifest | no | no | — |
| (extra) truth_enterprise_contracts | yes, but not in the focus answer key | yes | `generator/salesforce_enterprise.py`, `generator/tables.py:192` |
| DuckDB loader | no | no | — |
| dbt project, staging, intermediates | no: no `dbt_project.yml`, no `models/`, and dbt is not in `pyproject.toml` | no | — |
| Marts: dim_customer, fct_mrr_monthly, fct_arr_movements, fct_revenue_monthly, fct_deferred_revenue_rollforward, fct_billings_revenue_cash, fct_close_ledger, fct_restatements, fct_migration_exposure, fct_account_signals | no | no | — |
| Audit models and `scripts/check_truth_fence.py` | no (the script is required by CLAUDE.md but does not exist) | no | — |
| `make build/close/close-history/snowflake/demo` | no (the Makefile has only setup/seeds/data/test-gen/lint) | no | `Makefile` |
| LookML, dashboard SQL, Hightouch, CI workflow | no | no | — |
| Determinism and offline generation | yes | yes | `generator/rng.py`, `pyproject.toml` banned APIs, `tests/generator/test_generation_acceptance.py`, `test_offline.py` |

### Out of scope: where each item still appears

Docs hits are listed in §5. This table covers code, config with nonzero values, seeds, and tests.

| Item | Where it appears |
|---|---|
| Marketplace (AWS/Azure) | config `simulation.yml:104` (`marketplace_share` aws 0.20, azure 0.05), `:131` (`marketplace_fee_pct` 0.03/0.03), `:146` (D07 0.20). Code: `generator/config.py:27,184,198,227,251,356-358`; `generator/lifecycle.py:129,176,299-300`; `generator/simulate.py:367-369`; `generator/enterprise.py:99`; `generator/billing_orb.py:136`; `generator/tables.py:181` (`marketplace_offer_id__c`); `generator/salesforce_enterprise.py:127`. Tests: `tests/generator/test_orb_billing.py:376,453` (test name includes `marketplace`). Data: 13 marketplace subscriptions. |
| Services | config `simulation.yml:101-103` (`services_attach_rate` 0.30, lag, amount). Seed `price_book.csv:13` `ps_services`. Code: `generator/config.py:181-196`; `generator/enterprise.py:35-36,67-103`; `generator/billing_orb.py:830-842`; `generator/tables.py:211-212`; `generator/salesforce_enterprise.py:46-48`. Data: 22 services lines. |
| Add-ons: tagged resources | config `simulation.yml:75-76,121` (overage share 0.12). Seed `price_book.csv:11` `v4_tagged_resource`. Code: `generator/population.py:126,343,385-389,422`; `generator/billing_orb.py:584-587`; `generator/config.py:145-146,216`. The raw_app `tailnet_activity_daily.tagged_resources` column (`generator/tables.py:88`, `app_db.py:323`, `activity.py:55,181`, `simulate.py:48,67,134,412`) is listed in SCHEMAS, so that activity measure may stay. Tests: `test_orb_billing.py:41`, `test_seats_and_raw.py:90`. Data: 124 lines. |
| Add-ons: Mullvad | config `simulation.yml:122` (0.05). Seed `price_book.csv:12` `all_mullvad`. Code: `generator/billing_orb.py:235-241,589-597`; `generator/config.py:217`; `generator/rng.py:26` (`MULLVAD_ATTACH`). Tests: `test_orb_billing.py:55`. Data: 829 lines. |
| Multi-currency and FX | config `simulation.yml:19` (EUR 0.10, GBP 0.05). Seeds: `fx_rates.csv` (2,738 rows) and the `unit_amount_eur/gbp` columns in `price_book.csv`. Scripts: `scripts/fetch_fx.py`; `Makefile` `seeds` target. Code: `generator/population.py:23,183,221,397,407`; `generator/config.py:28,66,72,418-442`; `generator/reference.py:84-112,142,155` (FxRates); `generator/pricebook.py` (11 hits); `generator/billing_orb.py` (per-currency plans and prices, `COUNTRIES`); `generator/enterprise.py` (3 hits, including `/ rate`); `generator/app_db.py` (2). Tests: `test_config.py` (3), `test_pricebook.py:36` `test_local_currency_prices`, `test_seeds.py:65-124` (4 FX tests), `test_offline.py`, `test_orb_billing.py:504`. |
| Personal Plus | config `simulation.yml:30-33` (all nonzero). Seeds `price_book.csv:3` and `plan_entitlements.csv:12-21`. Code: `generator/lifecycle.py` (21 hits: state, triggers, edges, retirement); `generator/population.py:92-93,207-225`; `generator/simulate.py:83,106,194`; `generator/billing_orb.py:25,632`; `generator/calibration.py:63,68,260-268`; `generator/config.py:90-93`. Tests: `test_population_lifecycle.py:63-64,100-101`. Data: 642 subscriptions and 8,187 lines. |
| Multi-tailnet enterprise | config `simulation.yml:105` (0.15). Code: `generator/config.py:185`; `generator/lifecycle.py:87,310`; `generator/simulate.py:384`; the `child` contract kind in `enterprise.py`; `parent_tailnet_id` in truth. Tests: `test_orb_billing.py:466` (`"child"`). |
| Defects other than the six | config `simulation.yml:140-151`: D02 ×2, D04, D07, D08, D10 ×2, D11, D12, all nonzero. Code: `generator/config.py:245-265` (required pydantic fields). |
| PLG funnel and PQL | Code: `generator/population.py:111` (`lead_source: 0 PQL`). Raw Salesforce `lead` table (`generator/tables.py`, `salesforce_enterprise.py`) and `user`, which are not in SCHEMAS. Tests: `test_enterprise_sales.py` (lead assertions). |
| Bring-to-work | config `simulation.yml:24-26,40,49` (`personal_first_share` 0.30, `same_machine_share` 0.70, `email_localpart_reuse` 0.40, multipliers 1.8 and 1.5). Code: `generator/population.py:116-119,295-336,409-411`; `generator/activity.py:169`; `generator/lifecycle.py:98,213`; `generator/seats.py:181`; `generator/rng.py:23`; `generator/simulate.py:45,65`; `generator/calibration.py:100-106,145,152,201,302`; `generator/config.py:78-80,101,111,324`. Tests: `test_config.py:51`. |
| Legacy refactor | Not in code. Only in the README. |
| Slack sync | Not in code. `simulate.py:89` `min_seat_slack` is unrelated. Only in the README. |
| Evidence, GitHub Pages, Funnel mirror, parity script | Not in code, config, or seeds. Only in the README. `funnel` in `seeds/plan_entitlements.csv` and `config/simulation.yml:72` (`feature_daily_prob.funnel`) is the product *feature* that raw_app `feature_usage_daily` uses, not the Funnel mirror. |
| Forced migration (legacy) | `config/simulation.yml:12` `legacy_forced_migration_date: 2027-04-08`, `generator/config.py`, `lifecycle.py`, `test_config.py`. This matches SPEC, because the date is outside the window. |

---

## 4. Billing (task a)

**Worked examples.** All three BILLING_DESIGN.md examples are pytest fixtures, and all three pass:
`test_design_example_standard_adds_seat_on_june_16`, `test_design_example_starter_migration_has_two_may_invoices`, and `test_design_example_premium_keeps_legacy_price` (`tests/generator/test_orb_billing.py:116,172,230`). They check every invoice date, total, line type, price ID, quantity, unit price, amount, and service period.

| Invariant | Covered? | Where |
|---|---|---|
| Lines sum to subtotal | **Yes**, on every CI invoice | `test_all_orb_contracts_references_and_amounts` |
| total = subtotal (tax 0) | **Yes** | same |
| Trials and free plans get no invoices | **Partial.** Free Personal is asserted (no `plan_personal_v*` subscription). Trials are covered only indirectly: the expected-invoice sets exclude trial states, and the `starts` set built in the test is never asserted on. | `test_lifecycle_cadence_and_no_trial_invoices`, `test_every_active_v3_and_v4_month_has_its_required_invoice` |
| Migration month has two invoices on the same date | **Yes**: worked example 2, plus every simulated `MIGRATION_VOLUNTARY` (exactly two invoices on the migration date, covering the prior and current months) | `test_every_active_v3_and_v4_month_has_its_required_invoice` |
| Enterprise gets one invoice per contract year | **Yes** for multiyear contracts at anniversary: exactly one invoice, one fixed line equal to the ACV, and a one-year period. Runs only in the default-scale fixture and skips contracts with an expansion before the anniversary. | `test_default_enterprise_annual_cadence_marketplace_and_runtime` |
| Involuntary churn with an unpaid invoice gets a credit note | **Yes, by count**: the number of credit notes equals the number of `DUNNING_EXPIRED` transitions, all with reason `uncollectible` and type `adjustment`. The test does not check per-invoice that the linked invoice was unpaid. | `test_all_orb_contracts_references_and_amounts` |

**Orb tables written (10):** customers, plans, prices, subscriptions, subscription_quantity_changes, invoices, invoice_line_items, credit_notes, events, daily_line_item_revenue.

**Downstream readers:** none. No dbt project, Stripe generator, truth builder, or loader exists, and nothing in `generator/` reads the Orb output. Only the tests read the Parquet. All 10 tables pass the schema, sort, and primary-key test. `plans`, `prices`, and `subscription_quantity_changes` are FK-checked, and `daily_line_item_revenue` is reconciled to line amounts. The focus scope keeps only the first five tables listed in SCHEMAS. `plans`, `prices`, `subscription_quantity_changes`, `events`, and `daily_line_item_revenue` are outside it.

---

## 5. Docs

### Contradictions: docs vs code

1. **USD only** (SPEC §2–3, BILLING_DESIGN, SCHEMAS, CLAUDE.md) vs EUR/GBP generated and billed (§3). The `billing_orb.py:3` docstring says "local-currency Decimal".
2. **Orb tables**: SCHEMAS, SPEC, and BILLING_DESIGN ("five in-scope Orb source contracts") vs 10 in `generator/tables.py`.
3. **Salesforce**: SCHEMAS says "no reps … only accounts and opportunities", but the code writes `salesforce.user` and `salesforce.lead`. Opportunity also has `marketplace_offer_id__c`.
4. **raw_truth**: SCHEMAS lists four truth tables. The code writes only `truth_enterprise_contracts`, which is not in SCHEMAS, and it lands in `data/answer_key/` while the CLI prints the label `raw_truth`.
5. **Defects**: SPEC §3 and ADR-010 say "No other defect codes are generated", but `config/simulation.yml` and `generator/config.py` still define D02, D04, D07, D08, D10, D11, and D12. None are injected yet.
6. **BILLING_DESIGN "Status: implemented"** describes only in-scope plans. The code also bills Personal Plus, Mullvad, tagged resources, services, and the marketplace channel.
7. **BILLING_DESIGN price IDs** (`v4_standard`, `disc_nonprofit`) vs the emitted Orb IDs (`op_v4_standard_usd`, `op_disc_nonprofit_usd`).
8. **SCHEMAS**: "`docs/SCHEMAS.md` column tables are generated from `tables.py` from PLAN 1.11" (`tables.py:3`). No generator for that exists, and PLAN 1.11 no longer exists.
9. **ORB_BILLING_VALIDATION.md** says "The default seed-42 run and acceptance evidence are summarized here", but the file has only 3 lines and contains no numbers.
10. **CLAUDE.md commands** `make build`, `make close`, `make close-history`, `make snowflake`, and `make demo` do not exist in the Makefile. `scripts/check_truth_fence.py` does not exist. SETUP's `make build` fails for the same reason.
11. **CLAUDE.md "Add dependencies to the DECISIONS dependency log"**: `pyproject.toml` has faker, free-email-domains, pydantic, pyyaml, and pre-commit, which are not logged. The log lists dbt, SQLFluff, and lkml, which are not installed.
12. **Dangling references in code and config**: ADR-018 (`app_db.py:3`), ADR-019 (`simulation.yml:6`), ADR-022 (`ci.yml:1`, `config.py:4`), and ADR-023 (`population.py:3`, `rng.py:1`, `simulate.py:5`) point at ADRs that no longer exist (DECISIONS has 001–011). SPEC 2.2/2.4/2.5/2.6/4.2/4.3/4.4/4.5/5/8.5/8.6 point at subsections that no longer exist (SPEC has flat §1–6). PLAN 1.3/1.4/1.5/1.6/1.11 appear in test docstrings, `__main__.py:76`, and the Makefile.
13. **`.gitignore` excludes `data/`** (CLAUDE.md: keep `data/` ignored), but `data/reports/calibration.md` is tracked and gets rewritten by every `make data`.
14. **SPEC §2 Enterprise ACV** is "contracted seats, Premium list price, and recorded discount". The code also has a minimum ACV floor (`min_acv_usd`), which BILLING_DESIGN mentions but SPEC does not, and services.
15. **SETUP "Committed USD price … seeds"**, but the seeds also include `fx_rates.csv` and EUR/GBP price columns.

### Contradictions between docs

1. **README vs everything else**: 13 defects vs 6. Marketplace disbursement sources, Evidence report, GitHub Pages, bring-to-work, PQL, parity, Slack close summary, legacy refactor ("inherited-query refactor"), and "Requires uv and Node" all appear in the README and are out of scope. The README is still the pre-focus template with `{{…}}` placeholders.
2. **README "Known limitations"** cites ADR-002 and ADR-005 for Orb export assumptions. Those ADRs are now about source ownership and month assignment.
3. **CLAUDE.md "Work on `main`"** and PLAN "Work only on `main`" vs the session branch used for this audit.
4. **PLAN 4b requires "the DuckDB loader"**, and CLAUDE.md says `make data` "loads DuckDB raw schemas". The Makefile comment says the load "arrives with PLAN 1.11".
5. **CLAUDE.md "Add a STATUS update after each completion tag"** and PLAN 4e "record the skip in `docs/STATUS.md`". This file did not exist until now.
6. **SPEC §5 vs focus scope**: SPEC lists six marts plus close, exposure, and signals in prose. PLAN tasks match the focus list. They agree on content but name things differently (`fct_migration_exposure`, while the old PLAN used `fct_pricing_migration_exposure`).
7. **ADR-009 and ADR-011** are Proposed (Finance-owned), while BILLING_DESIGN says "Status: implemented" on top of ADR-011.

### Grep: docs/ and README.md

| Term | Hits |
|---|---|
| marketplace | `README.md:23`, `README.md:56` ("marketplaces"), `README.md:67`, `README.md:83` |
| Evidence (case-insensitive) | `README.md:59`, `README.md:63`. Plain-English "evidence": `docs/DECISIONS.md:39`, `docs/ORB_BILLING_VALIDATION.md:3` (not the tool) |
| Funnel | none |
| PQL | `README.md:40` |
| bring-to-work | `README.md:28`, `README.md:39` |
| FX movement | none |
| Personal Plus | none |
| services | none |
| add-on | none |
| Mullvad | none |
| parity | `README.md:38`, `README.md:75` |
| [CUT] | none |

### PLAN.md

- **Checked:** none. The pre-focus phase-0/1 checkboxes, including 1.1–1.5 done, were removed in `0dd4570`.
- **Unchecked (in order):** 4b Generator sources and truth; 4c Sources and staging; 4c Identity and finance intermediates; 4c Finance marts and audits; 4c dbt tests and CI; 4d Close history and restatements; 4d Migration exposure and Salesforce signals; 4d LookML; 4e Snowflake run; 4f Dashboard SQL and README.
- PLAN has no "4a" section and no record of the finished generator work.
- **Next task:** **4b Generator sources and truth.**

### ADRs (docs/DECISIONS.md)

| # | Title | Status |
|---|---|---|
| ADR-001 | Synthetic company and deterministic clock | Accepted |
| ADR-002 | Source ownership | Accepted |
| ADR-003 | USD price book | Accepted |
| ADR-004 | DuckDB first, Snowflake compatible | Accepted |
| ADR-005 | Month assignment and reporting time | Accepted |
| ADR-006 | ARR is month-end run rate | Accepted |
| ADR-007 | Price-volume decomposition | Accepted |
| ADR-008 | As-of source handling | Accepted |
| ADR-009 | Revenue and refunds | Proposed (Finance Controller) |
| ADR-010 | Defect scope | Accepted |
| ADR-011 | Provisional invoice policy | Proposed (Finance Controller) |

---

## 6. Recommendation (ordered, not started)

1. **S: Housekeeping.** Untrack `data/reports/calibration.md` or move the report out of `data/`. Remove the wall-clock timings from any committed report. Fix the stale CLI and Makefile messages ("PLAN 1.6 to 1.8", "PLAN 1.11").
2. **L: Remove out-of-scope generation (start of 4b).** Make currency USD-only: drop EUR/GBP, `fx_rates.csv`, `fetch_fx.py`, FxRates, the price-book EUR/GBP columns, and the FX tests. Remove Personal Plus (lifecycle states and triggers, price row, entitlements, tests), marketplace channel and fees, services, Mullvad and tagged-resource add-on billing, multi-tailnet children, the bring-to-work mechanism and its config, the `lead` and `user` Salesforce tables, and the config keys for the eight out-of-scope defects. Cut Orb to the five tables, or record an ADR to keep `daily_line_item_revenue` and the others. Then update the tests, the worked examples (if IDs change), and the calibration report. This step resets the RNG streams, so all calibration numbers change.
3. **S: Billing test gaps.** Add an explicit no-trial-invoice assertion, and a per-invoice check that each credit note's invoice was unpaid at churn.
4. **M: Stripe generator (4b).** Generate customer, invoice, charge, refund, and balance_transaction from Orb invoices and payment outcomes, with integer cents, fees from `payments`, and refunds, plus tests.
5. **S: Finance `manual_adjustments.csv` (4b).**
6. **M: Answer key (4b).** Generate `truth_mrr_monthly`, `truth_revenue_monthly`, `truth_identity`, and `defect_manifest` from the clean simulation, and decide whether `truth_enterprise_contracts` stays (update SCHEMAS if it does). Check them against independently rebuilt facts.
7. **M: Defect injection (4b).** Inject D01, D05 (late refunds and credit notes only), D06, D09, and D13 after clean generation, add manifest rows for D03, and test that only these six codes occur.
8. **S: DuckDB loader and `make data` row counts (4b).** Also add a `make` determinism target if wanted. Tag `generator-done` and add a STATUS update.
9. **S: Doc sync.** Rewrite README to the focus scope, or blank it until 4f. Fix dangling ADR, SPEC, and PLAN references in code. Fill in or delete `ORB_BILLING_VALIDATION.md`. Fix the dependency log. Decide whether ADR-009 and ADR-011 stay Proposed.
10. **M: dbt sources and staging (4c)**, including the dbt dependencies in `pyproject.toml` and the DECISIONS log, profiles, and as-of handling.
11. **M: Identity and finance intermediates (4c).**
12. **L: Finance marts and audits (4c)**, plus `scripts/check_truth_fence.py`.
13. **M: dbt unit tests and GitHub Actions CI (4c).** Tag `dbt-done`.
14. **M: Close history and restatements, plus the `make close` and `close-history` targets (4d).**
15. **M: Migration exposure and account signals (4d).**
16. **S: LookML (4d).**
17. **S: Snowflake run or recorded skip (4e).**
18. **M: Dashboard SQL, final README, `make demo` (4f).** Tag `demo-done`.

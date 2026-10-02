# Repo status

Updated 2026-10-02 after the focus-scope reconcile. The first audit (commit `98ed111`) is in git history.

## Progress log

### Snowflake follow-ups

- **Your run on Snowflake:** `make snowflake` loaded all 32 tables, and `dbt build --target snowflake` passed 126/126.
- **`fct_account_signals.account_name`:** taken from the Salesforce account and tested not null. Hightouch maps it to `Name` when it creates accounts in a fresh Developer org (SETUP).
- **Closes on either warehouse:** `make close` and `make close-history` take `TARGET=snowflake` (ADR-025).
  - `scripts/close.py` uses one ledger class over DuckDB or the Snowflake connector, reading `.env` like `make snowflake`.
  - The as-of build runs `dbt build --target snowflake`, and `close-history` ends with a Snowflake rebuild.
  - The DuckDB path is unchanged: re-verified end to end on CI data (six closes, then 128/128).
  - The Snowflake path is covered by tests with a fake DB-API connection. **It has not connected to Snowflake from here.**
- **`make dashboard-snowflake`:** compiles `analyses/dashboard/*.sql` for Snowflake without a connection into `target/snowflake/` and prints the seven file paths.
- **Tests:** `make test` passes 115, including the new close tests.

### Tier 3 (items 10 and 11; item 9 skipped by decision) — final state

- **Item 10, leap day:**
  - dbt unit test `annual_invoice_spanning_leap_day`: a 366-day year from 2024-01-15 recognizes $32.79 a day, including 2024-02-29, with the $31.65 residual on the last day.
  - Generator test: a contract signed on 2024-02-29 is invoiced again on 2025-02-28.
- **Item 11, audit test gaps:**
  - `test_trials_are_never_invoiced` checks that no subscription or line covers a trial day.
  - `test_each_uncollectible_credit_note_writes_off_its_unpaid_invoice` checks each note against its invoice: same customer, a failed payment on the issue date, never paid, full total, effective at dunning expiry.
- **Bug found and fixed (ADR-024):** the trial test showed that in a trial's conversion month, the v3 usage line covered the whole calendar month and billed trial-period users. The line now starts at conversion and counts only users active from then; the answer key, Orb usage events, and dbt all follow.
- **D05 retuned:** the fix shifted downstream random draws. At 0.10, D05 then restated only 2 closed periods, so it is now 0.20.
- **Final default run (`make demo` 52 s, 127 dbt nodes; `make close-history` 104 s):**
  - ARR $980,882.52 (Dec 2025) → $1,640,773.80 (Sep 2026).
  - 16 closed figures restated in 5 of 6 periods (April, June, July, August, September). July is a late credit note alone; June and September mix credit notes and refunds.
  - D05 36/36 handled.
  - MRR 14,924/14,924 and revenue 15,247/15,247 match truth.
  - The README has every number from this run.
- **Tests:** `make test` passes 111 (generator 103, project 8).
- **Tags (local only; pushes return HTTP 403):**
  - `generator-done` 2b3ce84
  - `dbt-done` 07a2ff6
  - `demo-v1` 78c0bad
  - `demo-done` 80897a9 (Tier 2 complete). The Tier 3 commit after it changes the demo numbers, and the README reflects that later commit.
- **Still open:**
  - `make snowflake` has never run against an account.
  - The GitHub Actions workflow has not run (it triggers on pull requests and pushes to `main`).
  - Item 9 (manual adjustments) is skipped.

### demo-done (Tier 2 complete)

- **Built:**
  - `fct_migration_exposure` and `fct_account_signals` (ADR-022), plus a migration-exposure dashboard query.
  - `lookml/` (two views, one explore), parse-tested with lkml.
  - D05 late refunds and credit notes.
  - As-of gates in every staging model.
  - `make close` and `make close-history` with an append-only `finance_close.close_ledger`, `fct_close_ledger`, and `fct_restatements` (ADR-023), plus a restatements dashboard query.
  - `.github/workflows/ci.yml`.
- **D05 rate:** raised from 0.05 to 0.10 so that restatements cover several periods and include late credit notes.
- **Default run:** `make demo` takes 50 s and passes 126 dbt nodes; `make close-history` takes 97 s.
  - Six closes are posted. 14 closed figures were restated afterwards, in 5 of the 6 periods:
    - April: late credit notes, revenue −$234.00.
    - May: late credit notes, revenue −$18.00.
    - June: a late credit note and a late refund, revenue −$1,332.00.
    - July: late refunds, revenue −$57.00.
    - September: late refunds, revenue −$154.00.
  - August had no late rows. Every restatement is explained.
  - D05: 21 injected, 8 detected at a close, 21 handled.
  - Migration exposure: 453 legacy tailnets with $437,760 ARR project to $664,200 on v4. Risk tiers: 396 high (248 above 40% uplift, plus 148 with no legacy MRR), 46 medium, 11 low.
  - Account signals: 152 accounts, 128 sync-eligible.
  - Answer-key audits are unchanged: MRR 14,924/14,924 and revenue 15,247/15,247.
- **Tests:** `make test` passes 108 (generator 100, project 8).
- **Open:**
  - The workflow triggers on pull requests and pushes to `main`, so it has not run yet; its steps all pass locally.
  - Tags cannot be pushed (HTTP 403). Create `demo-done` on the commit that adds this entry.
  - `make snowflake` has never run against a real account here.

### demo-v1 (Tier 1 complete)

- **Built:**
  - `make snowflake`: key-pair `.env`, `write_pandas` into `RAW_*` schemas, then `dbt build --target snowflake`. The exact steps are in SETUP and the design in ADR-021. It is not run here: the owner runs it locally. The models and analyses compile for the Snowflake target offline.
  - `analyses/dashboard/*.sql` (ARR trend, ARR waterfall, billings/revenue/cash, deferred revenue, defect scorecard), `make dashboard`, `make demo`, and a README with measured numbers.
- **Changed:** repricing now applies only to price-version changes, discount changes, and enterprise per-seat changes. A tier upgrade on the same version is expansion (ADR-007; a unit test covers it).
- **Default `make demo`:** 56 s from an empty database; 107 dbt nodes pass.
  - ARR $994,742.52 (Dec 2025) → $1,641,205.80 (Sep 2026).
  - Jan–Sep 2026 repricing $103,315.46: $22,392.00 from v3 → v4 migration and $80,923.46 from enterprise renewals.
  - MRR 14,924/14,924 and revenue 15,247/15,247 match truth.
- **Tests:** `make test` 95 passed (generator 91, project 4).
- **Open:** tags cannot be pushed (HTTP 403). Create `demo-v1` on the commit that adds this entry.

### dbt-done

- **Built:**
  - 27 staging models. D09 and D13 rows are filtered; D06 is deduplicated by `orb_invoice_id`.
  - Intermediate: `int_identity` (resolves D01 by email), `int_stripe_customer_map`, `int_invoice_lines`, `int_subscription_terms_monthly`, `int_seats_month_end`, `int_line_revenue_daily`, and `int_months`.
  - Marts: `fct_mrr_monthly`, `fct_arr_movements` (repricing split, ADR-007), `fct_arr_waterfall`, `fct_revenue_monthly`, `fct_deferred_revenue_rollforward`, `fct_billings_revenue_cash`, and `dim_customer`.
  - Audits: MRR, revenue, and identity against truth, plus `audit_defect_scorecard`.
  - `scripts/check_truth_fence.py` and `make build`.
- **Tests:** `make build` on the default data passes 107 nodes in 13 s.
  - Reconciliation tests: ARR waterfall, deferred-revenue rollforward, Orb vs. deduped Stripe, and Stripe cash vs. balance transactions.
  - Audit-must-match tests and an Orb allocation cross-check.
  - Unit tests for proration and repricing.
  - `make test-gen` passes 91 tests; `tests/project` passes 2.
- **Default run (seed 42):**
  - MRR matches truth on 14,924 of 14,924 tailnet-months; revenue matches on 15,247 of 15,247.
  - Every planted defect is detected and handled: D01 13/13, D03 40/40, D06 70/70, D09 103/103, D13 80/80.
  - Closing ARR: Jan 2024 $93,799.92; Jan 2025 $365,660.76; Jan 2026 $1,053,717.36; Sep 2026 $1,641,205.80.
  - Jan–Sep 2026 movements: new $431,443.68, expansion $426,577.90, repricing $152,995.46, contraction −$96,936.00, churn −$301,373.76, reactivation $33,756.00.
  - Jan–Sep 2026 totals: billings $1,132,596.21, revenue $983,440.66, net cash $1,108,245.80.
- **Tags:** the git proxy returns HTTP 403 for tag pushes, so tags exist only locally. To create them after merging:
  - `git tag generator-done 2b3ce84`
  - `git tag dbt-done <the commit that adds this entry>`

### generator-done

- **Built:**
  - Stripe customer, invoice, charge, refund, and balance_transaction, synced from Orb.
  - Salesforce renewal and expansion opportunities.
  - `truth_mrr_monthly`, `truth_revenue_monthly`, `truth_identity`, and `defect_manifest`.
  - Injection of D01, D06, D09, and D13, with D03 recorded.
  - Timestamps on LA business dates (ADR-014).
  - The DuckDB loader behind `make data`.
- **Default run (seed 42):**
  - 32 tables loaded into `data/seats_to_cash.duckdb` in 33 s.
  - Stripe: 935 customers, 20,280 invoice versions, 10,530 charge versions, 106 refunds, 10,086 balance transactions.
  - truth_mrr_monthly: 15,936 rows. September 2026 truth ARR, excluding internal tailnets: $1,641,205.80.
- **Defect manifest (306 rows):**
  - D01: 13 customers.
  - D03: 40 internal tailnets.
  - D06: 70 invoices.
  - D09: 103 charges.
  - D13: 20 bundles of customer, invoice, charge, and balance transaction (80 rows).
- **Tests:** `make test-gen` 91 passed. The new tests rebuild v4 seats, v3 usage MRR, and enterprise ARR from the raw sources and match the answer key to the cent.
- **Open:** D09 hit no Salesforce opportunity at seed 42. The rate is 1% of about 250 opportunities, so this happens about 8% of the time; the CI test tolerates zero.

## Earlier status (focus-scope reconcile)

## Where things stand

- **Generator:** builds and tests `raw_app` (8 tables), `raw_orb` (10 tables), enterprise `raw_salesforce` (account, opportunity, lead, user), and `truth_enterprise_contracts`. Output is deterministic and generation works offline.
- **Out-of-scope features are disabled in config, not deleted.** The features are multi-currency, Personal Plus, services, marketplace, add-ons (tagged resources, Mullvad), multi-tailnet enterprise, and defects other than D01, D03, D05, D06, D09, and D13.
  - Each switch is 0, or USD only for currencies.
  - `SimulationConfig.disabled_settings()` makes validation reject any nonzero value.
  - `docs/SCHEMAS.md` § Disabled options and the config comments list them.
  - At seed 42 the output contains no EUR/GBP invoice, Personal Plus subscription, add-on or services line, marketplace invoice, or child contract.
- **Kept as data:** the bring-to-work machine-key links, and the Salesforce `lead` and `user` tables (ADR-012).
- **Enterprise:** two sources, PLG and direct sales (ADR-013). At seed 42 the default config closes 62 contracts in the window (32 PLG, 30 direct). Before the features were disabled it was 58 (28 PLG, 30 direct); the change comes from disabling multi-tailnet and marketplace. `lead_source` on opportunity and `enterprise_source` in the truth table are documented.
- **Not started:** Stripe, Finance adjustments, the four answer-key tables, defect injection, the DuckDB loader, and everything from dbt onward. See PLAN.

## Health (at `48c369a`)

| Check | Result |
|---|---|
| `make lint` | Pass (ruff check; 48 files formatted) |
| `make test-gen` | **83 passed**, 0 failed |
| `make data SEED=42` | Pass, 27.1 s; leaves the working tree clean |
| `python -m generator --check` | Pass |

Default run (seed 42): raw_app.tailnets 31,683; users 113,505; seat_events 3,940; plan_changes 3,613; device_registrations 178,434; tailnet_activity_daily 517,368; tailnet_activity_monthly 453,940; feature_usage_daily 478,345; salesforce.user 1; account 216; lead 32; opportunity 216; truth_enterprise_contracts 97; orb.customers 28,070; plans 39; prices 42; subscriptions 2,078; subscription_quantity_changes 1,332; invoices 31,188 (version rows); invoice_line_items 17,442; credit_notes 100; events 125,874; daily_line_item_revenue 559,552.

## What the reconcile changed

Commits `97303c5` and `48c369a` on `claude/loving-carson-lrqdxj`:

1. **`97303c5` first deleted** the out-of-scope code paths, following the initial instruction. **`48c369a` restored them** per your clarification and disabled them in config instead. Net change to code, seeds and tests against `0dd4570`: 23 files, +143/−74.
2. **Config:** out-of-scope switches set to 0 and currencies set to USD only. Validation rejects nonzero values, with tests for every switch.
3. **Tests:** pinned enterprise counts updated to 32/30/62. Tests that assumed marketplace, child, or EUR/GBP rows now assert their absence.
4. **References:** code comments citing ADR-018/019/022/023, old SPEC subsections, or PLAN 1.x now cite existing sections or nothing. The stale "PLAN 1.6 to 1.8" CLI message is removed.
5. **Tracking:** `data/reports/calibration.md` is untracked, so `make data` no longer dirties the tree.
6. **Docs:**
   - SPEC: both enterprise sources, the minimum ACV, and the raw-table policy.
   - SCHEMAS: every written table with grain and value domains, plus a Disabled options section.
   - DECISIONS:
     - ADR-012: features, not raw tables, define scope.
     - ADR-013: the two enterprise sources.
     - ADR-001: determinism detail added.
     - Dependency log: corrected, with planned dependencies by task.
   - BILLING_DESIGN: all ten Orb tables, the `op_<id>_usd` price-ID format, the ADR-011 relationship, and a coverage table with known gaps. `ORB_BILLING_VALIDATION.md` (a 3-line stub) is folded into it and deleted.
   - SETUP: only working commands.
   - CLAUDE.md: scope and a command-availability table.
   - README: rewritten to the focus scope, with no placeholders and no unmeasured numbers.
   - PLAN: rewritten as tasks a–f.

Doc contradictions from the first audit are resolved. A grep of SPEC and README for removed or out-of-scope features and for `[CUT]` or `{{` finds nothing. Plain-English "evidence" remains in DECISIONS.

## Scope matrix (focus scope)

| Item | Implemented | Tested |
|---|---|---|
| Personal free, never billed | yes | yes |
| v3 Starter/Premium MAU arrears, 3 free users | yes | yes |
| v4 Standard/Premium seats, proration, auto seats | yes | yes |
| Enterprise annual invoices, PLG and direct sources | yes | yes |
| Nonprofit discount; USD only | yes | yes |
| raw_app; raw_orb (5 required + 5 extra); raw_salesforce | yes | yes |
| raw_stripe (5 tables), raw_finance.manual_adjustments | no | no |
| D03 internal tailnets | partial (generated, no manifest) | no |
| D01, D05, D06, D09, D13 | no | no |
| truth_mrr_monthly, truth_revenue_monthly, truth_identity, defect_manifest | no | no |
| DuckDB loader; dbt; marts; close; exposure; signals; LookML; dashboard | no | no |

## Next

PLAN task **a**: close the two Orb billing test gaps (explicit no-trial-invoice assertion, and a per-invoice credit-note check). Then task **b**: Stripe, Finance, answer key, defects, loader, then the `generator-done` tag.

## Notes

- The PLG opportunity `lead_source` value is `Product Qualified Lead` (a Salesforce LeadSource label). It is not a PQL scoring feature.
- The price book still carries EUR/GBP columns and rows for the disabled add-ons, services, and Personal Plus. They produce unused Orb catalog rows (`plans` 39, `prices` 42). `fx_rates.csv` and `scripts/fetch_fx.py` stay because config cross-checks the FX seed.
- ADR-009 and ADR-011 remain Proposed (Finance-owned); the generator implements ADR-011 provisionally.
- Snowflake (task e) is run locally by the owner.
- This session pushes to `claude/loving-carson-lrqdxj`, not `main`. Merge it to `main` to land the work.

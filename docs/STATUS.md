# Repo status

Updated 2026-10-02 after the focus-scope reconcile. The first audit (commit `98ed111`) is in git history.

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

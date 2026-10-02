# DECISIONS

Architecture and modeling decisions, newest at the bottom. Status is one of: Accepted, Proposed (needs a Finance or stakeholder call), Assumption (a guess about a real system that should be verified), or Superseded.

Template:

```
## ADR-NNN: Title
Status:
Context:
Decision:
Alternatives considered:
Consequences:
```

## ADR-001: Simulate the data instead of using public datasets

Status: Accepted
Context: No public dataset has seat-based B2B billing spread across product, billing, payment, and CRM systems. The KKBox churn data is real but consumer-only, with no seats or contracts. Synthetic SaaS sets on Kaggle and GitHub are generic single-table data with no system boundaries, and at least one author found their synthetic data carried no churn signal at all.
Decision: Build an event-driven simulator with documented causal mechanisms (SPEC 4.3) and a hidden answer key.
Alternatives considered: KKBox (wrong business model); Kaggle synthetic sets (no cross-system identity or billing mechanics); generating the dataset in Stripe test mode (test clocks hold only three customers each, and Stripe's list-all API calls omit test-clock objects, so a connector wouldn't sync them).
Consequences: Results are only as realistic as the mechanisms, so the mechanisms are written down and the README says they were planted.

## ADR-002: Land raw data in vendor shapes

Status: Accepted (Orb fields are an Assumption)
Context: Reviewers know what Fivetran output looks like. Staging that reads plausible vendor tables is more convincing than staging that reads tidy CSVs.
Decision: Stripe, Salesforce, and product DB tables follow Fivetran column conventions, including `_fivetran_synced` and `_fivetran_deleted`. Orb tables approximate Orb's data export resources.
Alternatives considered: A tidy normalized schema (easier, but skips the staging work the role actually involves).
Consequences: More staging work. Orb field names may differ from the real export.

## ADR-003: dbt Core 1.x, not Core v2

Status: Accepted. Revisit when v2 reaches general availability.
Context: dbt Core v2.0 shipped in June 2026 as an alpha built on the Fusion engine. Fusion doesn't yet generate the local docs site and doesn't work natively with SQLFluff.
Decision: Pin `dbt-core<2`.
Consequences: Stable docs, lint, and package support. A note in the README says the project targets 1.x.

## ADR-004: DuckDB for development, Snowflake for the final run, with exact parity

Status: Accepted
Context: The Snowflake trial lasts 30 days and can't be extended. The demo has to keep working after it expires.
Decision: DuckDB is the default target and the `make demo` path. Snowflake is a second target, with `scripts/parity_check.py` requiring identical row counts and monthly sums for every mart.
Consequences: Every model has to use cross-database macros. The Snowflake run is captured in screenshots and a parity report.

## ADR-005: System roles

Status: Assumption
Context: The target team's public stack lists Snowflake, dbt, Hightouch, Fivetran, Looker, Stripe, Salesforce, and Orb. The public pricing FAQ says overage seat charges go to Stripe. Orb's documentation describes a pattern where Orb is the billing engine and invoices sync to Stripe with metadata linking the two records.
Decision: The product DB owns users, seats, and usage. Orb owns subscriptions and invoices. Stripe owns payment collection. Salesforce owns sales-led deals.
Consequences: If the real split differs (for example, Stripe Billing for self-serve and Orb only for usage), the identity spine and the invoice-unification layer change, but the marts don't. This is a good interview question.

## ADR-006: The customer grain is the paying tailnet

Status: Accepted
Decision: `fct_mrr_monthly` is keyed by tailnet and month. Enterprise rollups use `parent_account_id` from Salesforce. Enterprise logo counts use the parent.
Consequences: Multi-tailnet enterprises show up as one logo and several billing accounts, which matches how billing actually works.

## ADR-007: ARR is run-rate; billed MRR is reported separately

Status: Accepted
Context: Invoice-based MRR double counts the migration month (a v3 arrears invoice and a v4 advance invoice on the same day) and treats proration as recurring. Fivetran's own Stripe package changed how its MRR report prices historical months in two releases in mid-2026 (v1.9.0 and v1.10.0), which shows the definition is a judgment call that needs writing down.
Decision: `arr_usd` = month-end run-rate MRR x 12, per SPEC 6. `mrr_billed_usd` is reported next to it so the gap is visible and explained.
Alternatives considered: Invoice-based MRR; subscription-object MRR from Stripe (not applicable here, since Stripe holds no subscriptions).
Consequences: ARR doesn't spike in migration months or from mid-month seat adds.

## ADR-008: Repricing is its own ARR movement

Status: Accepted
Context: Without it, every legacy customer moving to new list prices looks like expansion, which overstates organic growth during the migration window.
Decision: Use the price-volume decomposition in SPEC 6.1. A customer-month can carry both a repricing row and an expansion or contraction row.
Alternatives considered: Tagging migration months only (loses the split when quantity also changes).
Consequences: Needs month-t quantities under the prior terms, which is why the MAU basis is tracked even after migration.

## ADR-009: Timezone and month assignment

Status: Proposed (Finance confirms)
Decision: The reporting timezone is America/Los_Angeles.
- Billings: the month of the service period start, in reporting tz.
- Revenue: the recognition day, in reporting tz.
- Cash: the balance transaction or disbursement date, in reporting tz.
- MRR and ARR: the month-end state, in reporting tz.
Consequences: Invoices issued early (D04) land in the right month. The legacy query buckets by issue date and gets this wrong, on purpose.

## ADR-010: Foreign exchange

Status: Proposed
Decision: Report USD. MRR and ARR use month-end ECB-derived rates; revenue uses daily rates. The `fx` movement isolates rate changes from real ARR movement.
Consequences: Constant-currency views are possible later without remodeling.

## ADR-011: Revenue recognition policy defaults

Status: Proposed. Owner: Finance and the Controller. Analytics engineering implements these policies; it doesn't set them.
Decision: Defaults are set as dbt vars:
- `refund_treatment`: `reverse_when_issued` (alternative: `restate_original_period`)
- `marketplace_revenue`: `gross`, with the fee as a cost (alternative: `net`)
- `mullvad_treatment`: `gross` (alternative: `net` with `mullvad_net_rate`)
- Recurring and proration lines are ratable by day; v3 usage is recognized in the usage month; services at delivery.
Consequences: Changing a policy is a one-line var change plus a rebuild, and a reconciliation test confirms lifetime totals don't move.

## ADR-012: Closed periods are immutable; changes become restatements

Status: Accepted
Decision: Periods lock at their close date. `make close` builds as of the close timestamp (staging filters on load timestamps <= `as_of_ts`) and appends to `fct_close_ledger`. Later changes surface in `fct_restatements` with a reason. They never silently overwrite what was reported.
Consequences: Any reported number can be reproduced, and an auditor can see what changed after close and why.

## ADR-013: The answer key is fenced

Status: Accepted
Decision: Truth tables live in their own source (`raw_truth`). Only models in the `audit` group read them, and `scripts/check_truth_fence.py` fails CI if anything else does. dbt group access doesn't restrict sources, so the CI check is what enforces it.
Consequences: Marts can't cheat. The scorecard measures real detection.

## ADR-014: Evidence for the report, LookML as code

Status: Accepted
Context: Looker has no dependable self-serve trial for an individual: the console trial converts to a paid instance after 30 days, and LookML access otherwise goes through sales. A static site also survives the Snowflake trial ending.
Decision: Build the shareable report in Evidence (SQL and Markdown compiled to a static site). Write LookML views and an explore in `lookml/`, parse-checked but not run on a live instance.
Consequences: The README says plainly that the LookML is untested against Looker.

## ADR-015: Marketplace revenue is its own channel

Status: Accepted
Decision: Marketplace deals are Orb subscriptions with `invoicing_channel` set to a marketplace and `status = external` invoices. Cash comes from disbursement reports. Disbursements match to Salesforce on offer or opportunity reference, with a fallback on buyer mapping, amount, and month, and an unmatched queue for the rest.
Consequences: Bookings to cash ties out for marketplace deals without Stripe.

## ADR-016: Bring-to-work attribution

Status: Accepted
Decision: Machine-key matching is the primary method; email local-part matching is secondary, with lower confidence. Precision and recall are reported separately per method against the answer key.
Consequences: The funnel shows a measured confidence instead of a single overclaimed number.

## ADR-017: The PQL score is a transparent points model

Status: Accepted
Context: Sales has to understand why an account is flagged. With planted mechanisms, an ML model would mostly rediscover the simulation's own rules.
Decision: Use the points model in SPEC 8.4 and report lift by score band.
Consequences: It's easy to explain and easy to tune.

## Dependency log

| Dependency | Why |
|---|---|
| numpy, pandas, pyarrow | simulation and Parquet output |
| duckdb | dev warehouse and loader |
| faker | names and domains |
| pydantic, pyyaml | config validation |
| free-email-domains | public free-email domain list for personal vs business routing |
| dbt-core (<2), dbt-duckdb, dbt-snowflake | transformation (ADR-003) |
| snowflake-connector-python | Snowflake loader |
| dbt_utils, audit_helper (dbt packages) | macros; the legacy refactor comparison |
| pytest, ruff, sqlfluff, sqlfluff-templater-dbt, pre-commit | tests and lint |
| lkml | LookML parse check |
| Evidence (npm) | static report |

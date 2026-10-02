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
- Normal invoices are issued 10:00 to 12:00 UTC on the 1st, which is also the 1st in Pacific time. `invoice_date` is the `issued_at` date in reporting tz. D04 invoices are issued 23:00 to 23:59 Pacific on the last day of the prior month, already the 1st in UTC, so only a reporting-tz bucket by issue date gets them wrong.
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
Decision: Periods lock at their close date. `make close` builds as of the close timestamp (staging reads append-only tables with load timestamps <= `as_of_ts`, and the latest version <= `as_of_ts` of versioned tables; see ADR-018) and appends to `fct_close_ledger`. Later changes surface in `fct_restatements` with a reason. They never silently overwrite what was reported.
Consequences: Any reported number can be reproduced, and an auditor can see what changed after close and why.

## ADR-013: The answer key is fenced

Status: Accepted
Decision: Truth tables live in their own source (`raw_truth`). Only dbt models in the `audit` group read them, and `scripts/check_truth_fence.py` fails CI if any other dbt node does. dbt group access doesn't restrict sources, so the CI check is what enforces it. The fence covers dbt nodes only: `generator/` writes the answer key and `tests/` reads it to check generator invariants.
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

## ADR-018: Mutable raw tables are version logs

Status: Accepted
Context: Staging reconstructs a closed period by keeping rows with load timestamp <= `as_of_ts`. That works for append-only rows but not for rows that get updated. An invoice issued in September and voided in October has an October load timestamp, so a filter on the latest row drops it from the September close instead of showing it as issued.
Decision: Ten mutable tables land as version logs, one row per version: `raw_app.tailnets`, `raw_app.users`, `raw_orb.customers`, `raw_orb.subscriptions`, `raw_orb.invoices`, `raw_stripe.customer`, `raw_stripe.invoice`, `raw_stripe.charge`, `raw_salesforce.account`, `raw_salesforce.opportunity`. Fivetran sources use history-mode columns (`_fivetran_start`, `_fivetran_end`, `_fivetran_active`); Orb tables write a new row per change ordered by `_exported_at`. One staging macro, `as_of_latest`, picks per key the latest version with version timestamp <= `as_of_ts`, then applies deleted flags. Everything else stays append-only and uses `as_of_filter`.
Alternatives considered: Snapshotting each raw table at every close date (the close would depend on when someone ran it, and the generator would have to fake snapshots); dbt snapshots over current-state tables (can't reconstruct history that predates the first snapshot run).
Consequences: Any period can be rebuilt as of any timestamp. D01 resolves through the `raw_orb.customers` history of `payment_provider_id`, and late Salesforce edits (a D05 subtype) become visible as versions. Raw primary keys include the version timestamp, so uniqueness tests move to staging. `_fivetran_active` and `_fivetran_end` reflect the log at extract time and must not drive as-of logic.

## ADR-019: Simulate a 2023 burn-in year

Status: Accepted
Context: A simulation that starts on the first reporting day has no customers, no deferred revenue, and no annual contracts mid-term, so January 2024 would look like a company's first month and every customer would show as `new`.
Decision: Simulate from `sim_start_date` 2023-01-01 and report from `reporting_start_date` 2024-01-01. Emit all raw data from 2023. Marts report from 2024, and 2023 rows feed opening balances (ARR, deferred revenue, AR) only.
Alternatives considered: Seeding an opening book directly (needs a second, hand-built generator path with its own invariants); reporting from 2023 (the first months would still lack history).
Consequences: Generation covers 33 months instead of 21, which adds run time. The price book's v3 and all-version rows start at 2023-01-01. ARR movements in January 2024 are real movements, not a mass of `new`.

## ADR-020: Fixed local-currency list prices

Status: Accepted (prices are illustrative)
Context: About 15% of customers bill in EUR or GBP. Converting USD list prices at each month's FX rate would make a customer's invoice change every month with no change in what they bought, and would hide the `fx` ARR movement inside price changes.
Decision: Self-serve prices are fixed per currency in the price book (`unit_amount_usd`, `unit_amount_eur`, `unit_amount_gbp`). Customers are billed in their own currency. Enterprise contracts are priced from the Premium seat price in the contract currency; USD config amounts (minimum ACV, services) convert at the contract-start rate.
Alternatives considered: USD-only billing (unrealistic for EU and UK self-serve); monthly conversion of USD prices (invoices drift with no customer action).
Consequences: Local-currency invoices are stable, and the `fx` movement isolates exchange-rate effects on USD-reported ARR (ADR-010).

## ADR-021: Invented domains use the reserved .example TLD

Status: Accepted
Context: Faker's company domains are plausible real names and can belong to real businesses. The demo's synthetic-only rule covers generated people, customers, and companies.
Decision: Every invented domain uses `.example` (RFC 2606), including the company's own: `wirefern.example`. Personal emails use real public webmail domains (gmail.com and so on), because personal-vs-business routing classifies against the public free-email list, and webmail domains identify no customer. Vendor names from the public pricing page (Stripe, Orb, Mullvad, AWS, Azure) are fine.
Alternatives considered: `.test` or `.invalid` (less readable); Faker's domains filtered against a blocklist (can't prove a name isn't real).
Consequences: No generated company domain can resolve to a real business. Company domains are generated so they never collide with the free-email list.

## ADR-022: config/ci.yml is an overlay, not a copy

Status: Accepted
Context: CI needs the same simulation at 10% scale. A full copy of `simulation.yml` would drift every time a rate changes.
Decision: A config file may name a base file with `extends:`; its keys are deep-merged over the base (mappings merge, everything else replaces). `config/ci.yml` overrides only the three population counts.
Alternatives considered: A full copy (drifts); a `--scale` CLI flag (hides which counts scale and which don't).
Consequences: Rate changes in `simulation.yml` reach CI automatically. A test asserts that `ci.yml` differs from the base only in population counts.


## ADR-023: Deterministic population and daily business simulation

Status: Accepted
Context: The generator needs a 2023 opening book and repeatable Parquet, while business users, seats, and usage evolve daily. The CI overlay is smaller than the default population (ADR-022). A fixed seed alone does not make a reduced population a row-for-row subset of a larger run.
Decision: Configured personal and business population counts are totals over the full 2023-01 through 2026-09 simulation, allocated to months by largest remainder after applying `population.signup_growth_monthly`. Internal tailnets are additional. Personal lifecycle and activity are simulated monthly; business state is kept in stable creation-order arrays and advanced by vectorized daily phases: activation, departures, administrator actions, logins, activity, then lifecycle. Named NumPy RNG streams use fixed integer keys. Population entities use per-slot streams; business phases use per-day streams over the current stable array order. Timings use `perf_counter` only in the calibration report and never enter source rows.
Material behavioral assumptions: personal users join within 30 days of signup and monthly activity is sampled rather than expanded to daily rows; a pre-v4 Personal signup starts with at most three users, even if it later upgrades to Personal Plus. Business initial users and company size use the configured lognormal draws, with company size limiting new invitations; growth is reduced as users approach headcount. Departures and gross new invitations together implement net growth. Invitations may await approval, expire, or never log in. An occupied seat begins at first login. A gated attempt can influence an upgrade for 30 days. The low-utilization clock uses occupied/held on seat plans and a 30-day active-user proxy on v3 MAU plans. Payment failure is drawn at the first-of-month eligible self-serve or Personal Plus invoice opportunity; billing and payments must consume those recorded transitions, as specified in BILLING_DESIGN.md.
Consequences: Equal seed, config, seeds, and software produce byte-identical Parquet even across Python hash seeds. Changing a population count changes month slots, array lengths, and daily draw consumption, so outputs for a given logical entity are not guaranteed to match between CI and default configs. This is an explicit per-config determinism guarantee; `config/ci.yml` is not a subsample of the default output. The calibration report shows mechanism estimates with exposures and intervals instead of treating thin samples as tests.
Measured seed-42 default run: eight raw_app tables in 3.99 seconds of timed stages, against the 90-second task 1.3/1.4 budget; 25,000 personal and 3,000 business signups; 884/3,000 (29.5%) bring-to-work creators; 1,026 ever-paying business tailnets. There were 28 enterprise closes versus about 60 in SPEC 4.5. The funnel was 116 leads reaching 25 seats, 36 selected at `enterprise.lead_to_close = 0.35`, six scheduled beyond 2026-09-30, and 28 actual closes. The shortfall originates mainly in the lead population and finite close window, not a failed close draw. The 116-lead count reflects the configured initial-user, headcount, and growth distributions; no rate was tuned to force the target. The v4 Standard gated-upgrade estimate is 2.85x vs 4x configured on only four gated and four comparison upgrades (95% interval 0.71 to 11.40), so the flag is descriptive, not a test failure.
Offline acceptance: with dependencies already installed, actual CI-scale generation runs while outbound socket connections, DNS lookup, and child process creation are blocked, and committed seeds remain unchanged. Dependency installation is a separate setup step. `make demo` is not implemented in Phase 1; when added, its generation path must be checked offline with installed dependencies and must not invoke `make seeds`.

## ADR-024: Two enterprise acquisition sources

Status: Accepted
Context: The self-serve seat-threshold funnel yielded 28 contracts, below the roughly 60 in SPEC 4.5. Changing its existing close rate would obscure the funnel mechanics.
Decision: Keep the PLG lead and close path and add `enterprise.direct_sales_accounts: 32` on the existing monthly growth curve. Each direct prospect has a Salesforce lead and opportunity before signing; its product tailnet begins only on the recorded contract date. Opportunity LeadSource is Product Qualified Lead for PLG and Inbound or Outbound for direct. `enterprise_source` is recorded with immutable contract facts for downstream channel analysis. Opportunities closing after the simulation end remain open pipeline. Contract economics draw from an entity-keyed stream so they do not move PLG lifecycle draws.
Consequences: At seed 42 default scale, 28 PLG plus 30 direct contracts close (58 total), within the 55–65 target. Two direct opportunities close after the window and remain open. The CI overlay uses three direct prospects. The channel split supports growth analysis without changing existing conversion, close, or churn rates. The pooled Starter and Standard gated-upgrade ratio is 3.423 on 113 gated and 48 comparison upgrades (122,600 and 178,253 exposure-days); Starter alone is 3.455 on 109 and 44, Standard alone 2.852 on four and four. The thin Standard sample does not justify tuning.

## ADR-025: Provisional Orb invoicing policies

Status: Proposed. Owner: Finance and the Controller.
Context: SPEC 2.1–2.6 and 7 define cadence and valuation but leave mid-month first bills, tier changes, fractional-cent rounding, discount scope, settlement timing, and expansion invoicing open. BILLING_DESIGN.md lists the choices. Task 1.5 needs a concrete output before Finance ratifies them.
Decision: Round every line half up to cents, sum rounded lines for subtotal, and put daily-allocation residual on the last service day. Issue an immediate partial-month v4 invoice at conversion/reactivation; defer a mid-month v4 tier-price change to the next cycle. Discount base recurring, usage, and seat-proration lines only, using the price-book discount. Restore retained v3 Personal Plus price if a future lifecycle reactivation event is introduced; none exists now. Create paid invoice versions the day after successful issue or on recorded dunning recovery, and issue an adjustment/uncollectible credit note on recorded involuntary churn. Charge enterprise expansions immediately for remaining contract-year days and use the latest contracted ACV at the next anniversary. For Mullvad, meter v3 on its usage month and advance plans from prior-month measured device count; the first advance month has no prior quantity. For the interim channel-billings validation report, convert local invoice lines to USD at the line service-start date using the committed FX seed; final dbt policy remains subject to Finance approval.
Consequences: These policies are implemented and tested but remain Proposed for Finance approval. Changing one requires an ADR update and regenerated data. Orb does not independently draw payment failures or recoveries. The default seed-42 run rendered Orb in 2.2 seconds and wrote its Parquet in 0.5 seconds, well below the 60-second stage budget.

## Dependency log

| Dependency | Why |
|---|---|
| uv_build | build backend for the `generator` package |
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

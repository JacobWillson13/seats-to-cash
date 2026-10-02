# Decisions

Choices that shape the focused ARR and close story. Prices come only from `seeds/price_book.csv`. Policy items marked Proposed remain Finance-owned.

## ADR-001: Synthetic company and deterministic clock

Status: Accepted

Wirefern and every generated customer are fictional. Generated dates come from config and the simulation clock; there is no wall-clock dependency or unseeded randomness. `.example` is used for invented company domains.

## ADR-002: Source ownership

Status: Accepted

`raw_app` owns customer, seat, and activity facts; Orb owns subscriptions and invoices; Stripe owns collection facts; Salesforce owns enterprise accounts and opportunities; Finance owns manual adjustments. The generator's answer key is audit-only. dbt derives business facts from the raw sources.

## ADR-003: USD price book

Status: Accepted

The committed USD values in `seeds/price_book.csv` are the single price authority. Existing subscriptions retain their recorded price ID through sale-window changes. No source or mart hardcodes list prices.

## ADR-004: DuckDB first, Snowflake compatible

Status: Accepted

DuckDB is the local development target. Models use dbt cross-database functions and must also compile and build on Snowflake. Raw source schemas retain the same names on both platforms.

## ADR-005: Month assignment and reporting time

Status: Accepted

Reporting timezone is `America/Los_Angeles`. Billings use service-period start month, revenue uses recognition date, cash uses settlement date, and MRR/ARR use month-end state. Invoice issue date does not define service month.

## ADR-006: ARR is month-end run rate

Status: Accepted

ARR is month-end MRR multiplied by 12. Invoices are evidence for billed amounts, not the ARR definition. A migration can create two invoices on one day without duplicating ARR.

## ADR-007: Price-volume decomposition

Status: Accepted

For plan and price changes, split the value change into quantity movement at prior price and repricing at prior quantity. Classify remaining changes as new, expansion, contraction, churn, or reactivation. The waterfall must reconcile to the month-end ARR delta.

## ADR-008: As-of source handling

Status: Accepted

Existing mutable `raw_app` tables keep their version-log treatment. Other mutable entity rows use their creation timestamp for the `as_of_ts` staging gate; append-only rows use their load timestamp. Close snapshots are immutable after posting.

## ADR-009: Revenue and refunds

Status: Proposed. Owner: Finance Controller.

Recognize v3 usage in its service month, v4 seats over the billed calendar days, and enterprise contracts over service days. The default refund policy reverses revenue when issued. Late rows are visible in a later as-of build and are recorded as restatements rather than changing the original close ledger row.

## ADR-010: Defect scope

Status: Accepted

Only D01 duplicate Stripe customer, D03 internal tailnets, D05 late refunds and credit notes, D06 duplicate Stripe sync, D09 soft deletes, and D13 Stripe test-mode rows are planted. Defects are introduced after clean answer-key generation and carry a manifest record.

## ADR-011: Provisional invoice policy

Status: Proposed. Owner: Finance Controller.

Invoice lines round half up to cents; subtotal sums rounded lines and tax is zero. Enterprise invoices cover one contract year at signing and each anniversary, never the whole term upfront. Unpaid invoices that end in involuntary churn receive adjustment credit notes with reason `uncollectible`. See `BILLING_DESIGN.md` for testable examples.

## Dependency log

| Dependency | Purpose |
|---|---|
| NumPy, pandas, PyArrow | Simulation and Parquet |
| DuckDB | Local analytics warehouse |
| dbt Core, dbt-duckdb, dbt-snowflake | Transformations |
| pytest, Ruff, SQLFluff | Tests and lint |
| lkml | LookML parse test |

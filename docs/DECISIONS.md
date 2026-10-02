# Decisions

Choices that shape the focused ARR and close story. Prices come only from `seeds/price_book.csv`. Policy items marked Proposed remain Finance-owned.

## ADR-001: Synthetic company and deterministic clock

Status: Accepted

Wirefern and every generated customer are fictional. Generated dates come from config and the simulation clock; there is no wall-clock dependency or unseeded randomness. `.example` is used for invented company domains.

Randomness comes from explicit NumPy generators keyed by the config seed and fixed integers (`generator/rng.py`): one stream per entity for population draws, and one stream per day or month for the simulation loop. Two runs with the same seed and config write byte-identical Parquet.

## ADR-002: Source ownership

Status: Accepted

`raw_app` owns customer, seat, and activity facts; Orb owns subscriptions and invoices; Stripe owns collection facts; Salesforce owns enterprise accounts and opportunities; Finance owns manual adjustments. The generator's answer key is audit-only. dbt derives business facts from the raw sources. Orb's role and its export field names are modeling assumptions, not a copy of a real Orb account.

## ADR-003: USD price book

Status: Accepted

The committed `unit_amount_usd` values in `seeds/price_book.csv` are the single price authority, and USD is the only currency: config sets `population.currencies` to USD only and validation rejects any other nonzero share. Existing subscriptions retain their recorded price ID through sale-window changes. No source or mart hardcodes list prices. Pre-v4 (v3) prices are illustrative.

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

Existing mutable `raw_app` tables keep their version-log treatment (Fivetran history mode). Other mutable entity rows use their creation timestamp for the `as_of_ts` staging gate; append-only rows use their load timestamp. Close snapshots are immutable after posting.

## ADR-009: Revenue and refunds

Status: Proposed. Owner: Finance Controller.

Recognize v3 usage in its service month, v4 seats over the billed calendar days, and enterprise contracts over service days. The default refund policy reverses revenue when issued. Late rows are visible in a later as-of build and are recorded as restatements rather than changing the original close ledger row.

## ADR-010: Defect scope

Status: Accepted

Only D01 duplicate Stripe customer, D03 internal tailnets, D05 late refunds and credit notes, D06 duplicate Stripe sync, D09 soft deletes, and D13 Stripe test-mode rows are planted. Defects are introduced after clean answer-key generation and carry a manifest record. D03 is generated with the population (internal tailnets on `wirefern.example` with a 100% discount) rather than injected later. Config also carries rate keys for other defect codes; they are disabled at 0, nothing injects them, and validation rejects a nonzero rate.

## ADR-011: Provisional invoice policy

Status: Proposed. Owner: Finance Controller.

Invoice lines round half up to cents; subtotal sums rounded lines and tax is zero. Enterprise invoices cover one contract year at signing and each anniversary, never the whole term upfront. Unpaid invoices that end in involuntary churn receive adjustment credit notes with reason `uncollectible`. The generator implements this provisional policy; see `BILLING_DESIGN.md` for testable examples. A Finance change to the policy means a generator change.

## ADR-012: Features define scope, not raw tables

Status: Accepted

Scope is set by features: plans, defects, metrics, and outputs. Raw tables the generator already writes and tests stay, even when no mart needs them (for example Orb `plans`, `prices`, `subscription_quantity_changes`, `events`, and `daily_line_item_revenue`, and Salesforce `lead` and `user`). Every landed table is documented in `SCHEMAS.md` and staged by dbt; the marts read only what the story needs. Bring-to-work facts (shared machine keys between personal and business tailnets) are kept as data.

Features outside the project scope keep their generator code but are disabled in config: every switch is 0 (or USD only for currencies), and `SimulationConfig.disabled_settings()` makes validation reject a nonzero value. The disabled switches are listed in the config comments and in `SCHEMAS.md`; columns they would populate stay in the table contracts with constant or null values.

## ADR-013: Two enterprise sources

Status: Accepted

Enterprise contracts come from product-led growth and from direct sales. A PLG tailnet that reaches `enterprise.lead_seat_threshold` seats becomes a lead and closes at `enterprise.lead_to_close` after a lag; its opportunity has `lead_source` `Product Qualified Lead`. A direct-sales account (`enterprise.direct_sales_accounts`) appears in Salesforce as a lead with `lead_source` `Inbound` or `Outbound` before any product tailnet exists; its tailnet is created on the signing date. `truth_enterprise_contracts.enterprise_source` records `plg` or `direct` for every contract event. Direct-sales deals are simulated after the PLG cohort in their own pass, so adding them does not change any PLG draw. At seed 42 the default config closes 62 contracts in the window: 32 PLG and 30 direct.

## ADR-014: A sim day is a Los Angeles business date

Status: Accepted

The simulation counts days. Each day index is a business date in the reporting time zone, `America/Los_Angeles`, and each event's second-of-day is local time. `Calendar.epoch_us` converts (day, second) from local time to UTC using that day's UTC offset at local noon, so DST changes overnight never move an event to another date. Converting any landed timestamp back to Los Angeles time gives its sim date, and month-end state in dbt (seats held, refunds issued) agrees with the answer key. Date columns (invoice dates, service periods, close dates) are already local dates.

## ADR-015: Refunds and credit notes reduce revenue when they happen

Status: Accepted (implements the ADR-009 default)

Monthly revenue is line revenue recognized by service day, less refunds in the Los Angeles month the refund is created, less credit notes in their effective month. Revenue after `end_date` is outside the reporting window. The deferred-revenue rollforward uses gross line billings and gross recognized revenue, so refunds and credit notes do not break it; they are reported beside it.

## ADR-016: Enterprise ARR comes from Salesforce won opportunities

Status: Accepted

Each enterprise contract event has a Closed Won opportunity: New Business at signing, then Renewal or Expansion. `recurring_arr__c` is the contract's total annual value after the event. Enterprise MRR at a month end is the latest won opportunity's `recurring_arr__c` / 12, rounded half up to cents, while the tailnet's Orb enterprise subscription is active. Orb invoice lines cannot give it: an expansion is invoiced as a prorated amount.

## ADR-017: Stripe collects what Orb invoices

Status: Accepted

- **What syncs:** every Orb invoice with a positive total. Zero-total invoices (internal tailnets) never reach Stripe.
- **IDs:** the Stripe invoice ID is Orb's `external_sync_id`, and the Stripe customer ID is the Orb customer's `payment_provider_id`.
- **Metadata:** the Stripe invoice carries `orb_invoice_id` and `payment_source` (`card` for self-serve, `ach` for Enterprise).
- **Charges and invoice status follow Orb's history:**
  - A recorded payment failure gives a failed charge after finalization.
  - A paid Orb invoice gives one succeeded charge at its `paid_at`.
  - An Orb uncollectible credit note marks the Stripe invoice `uncollectible`.
- **Refunds:** the only new draw. A `payments.refund_rate` share of succeeded charges is refunded, fully or by half, 1 to 20 days later, from its own seeded stream.
- **Fees:**
  - Card: `card_fee_pct` plus `card_fee_fixed_cents`.
  - ACH: `ach_fee_pct`, capped at `ach_fee_cap_cents`.
  - Each fee is rounded half up to a cent.
- **Balance transactions:** settle on `created`'s local date plus `payout_lag_days` (`available_on`). Cash is reported by `available_on` month.

## ADR-018: How the planted defects look

Status: Accepted

Defects are injected into clean rows after the answer key is built, each from its own seeded stream, and each injected or affected row gets a `defect_manifest` row.

- **D01:** a Stripe customer is re-created partway through its history. Later invoices and charges point at the copy, which has the same email and no metadata, so identity resolution matches on email.
- **D03:** the internal tailnets are recorded, not injected.
- **D06:** an invoice is synced twice under a second ID with the same `orb_invoice_id` and no charge. Staging keeps the first sync per Orb invoice.
- **D09:** copies of succeeded charges and of opportunities are marked `_fivetran_deleted` or `is_deleted`.
- **D13:** complete test-mode bundles (customer, paid invoice, charge, balance transaction) with `livemode` false.
- **D05:** arrives with the close process.

## ADR-019: DuckDB is loaded by the generator

Status: Accepted

`make data` writes Parquet and then loads every file into `data/seats_to_cash.duckdb` as `raw_<source>.<table>` (`--no-load` skips it). The load replaces raw tables only, so dbt schemas in the same file survive a reload. Parquet is the deterministic artifact; the DuckDB file is not byte-compared.

## Dependency log

Installed (`pyproject.toml`, locked in `uv.lock`):

| Dependency | Purpose |
|---|---|
| NumPy, pandas, PyArrow | Simulation and Parquet |
| DuckDB | Local analytics warehouse and Parquet checks |
| Faker | Synthetic person and company name lists |
| free-email-domains | Builds the committed `seeds/free_email_domains.csv` |
| pydantic, PyYAML | Config loading and validation |
| dbt Core, dbt-duckdb | Transformations on DuckDB |
| pytest, Ruff, pre-commit | Tests, lint, and hooks (dev) |

Planned, added with the PLAN task that first needs them:

| Dependency | Purpose | Task |
|---|---|---|
| SQLFluff | SQL lint | c |
| lkml | LookML parse test | d |
| dbt-snowflake, snowflake-connector-python | Snowflake load and build | e |

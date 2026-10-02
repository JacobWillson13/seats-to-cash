# Task 1.5 design: Orb billing

Status: implemented in task 1.5; Finance policy choices remain Proposed in ADR-025. The three worked histories below run as deterministic pytest fixtures. All price IDs and amounts below come from the committed `seeds/price_book.csv`; the examples are illustrative customer histories, not generated rows. Governing rules: SPEC 2.1–2.6, 4.1–4.2, 6–7; SCHEMAS `raw_orb`; ADR-005, ADR-007–012, ADR-015, ADR-018–020, and ADR-023.

## Implemented module and recorded inputs

`generator/billing_orb.py` builds the Orb catalog, customer and subscription version logs, quantity changes, invoices, lines, metering events, credit notes, and daily revenue. Its `Term` and `Builder` types keep the timeline and line calculations together; splitting them into the three proposed helper modules added no useful boundary at this scale. `generator/tables.py` declares every column, key, type, and sort order. The renderer consumes `sim.transitions` for plan, migration, churn, failure, recovery, and dunning; `sim.seat_events` for held-seat history; `sim.mau` and daily activity for usage and add-ons; and immutable `sim.contract_events` for enterprise ACV, term, channel, discount, and services. It never redraws lifecycle outcomes. A named entity stream decides the independent Mullvad add-on attachment only.

A term retains its `price_id` after the committed price book withdraws it from sale. Enterprise contract invoices use the committed Enterprise custom-price ID, one contract unit, and the recorded ACV; the Premium list-price reference stays in the immutable contract fact for the ACV calculation. New terms use the version chosen by lifecycle at conversion or contract start. Orb `prices.external_price_id` maps to the committed seed; local prices come from that seed. Planned services may deliver after `end_date`; their invoice is issued at signing, with a service period through the planned delivery date.

## Source-table contracts

Task 1.5 writes only `raw_orb` Parquet in `data/raw/orb/`. Amounts are decimal strings in invoice currency; timestamps are UTC and exports stop by `extract_date` (SCHEMAS; ADR-018). Existing price-book IDs map to Orb `prices.external_price_id`, never to hardcoded amounts.

| Table | Contract and grain |
|---|---|
| `customers` | Version log by `(id, _exported_at)`; `external_customer_id = tailnet_id`, currency, payment provider, provider ID, metadata. Marketplace customers have no Stripe provider ID. |
| `plans` | One catalog row per version, plan, and currency; `external_plan_id` comes from the price book. |
| `prices` | One catalog row per price-book item and currency; model, unit amount, package size, cadence, and billing timing copy the seed. |
| `subscriptions` | Version log by `(id, _exported_at)`; customer, plan, status, term dates, net terms, channel, discount, and end reason. A migration ends the v3 subscription and starts a separate v4 subscription. |
| `subscription_quantity_changes` | Append-only ordered changes by effective date and recorded/export time, sourced from seat ledger or enterprise contract event. D12 lag belongs to later defect injection. |
| `invoices` | Version log by `(id, _exported_at)` for issued, paid, void, or external status. `invoice_date` is the issue timestamp's Pacific calendar date, while `service_period_start` assigns billings (ADR-009). Total equals subtotal plus zero tax; subtotal includes negative discount lines; `discount_total` is informational. |
| `invoice_line_items` | Append-only line by ID; `price_id`, `line_type`, inclusive `start_date`/`end_date`, quantity, unit and amount as decimal strings. A discount line has negative amount and `applies_to_line_id` pointing to one positive line. |
| `credit_notes` | Append-only by ID, linked to an invoice/customer with effective and export dates. Late notes appear after close and cause restatements (ADR-012). |
| `events` | One `user_active` metering event per distinct v3 active user, tailnet, and service month, with a deterministic idempotency key. |
| `daily_line_item_revenue` | One line/day for ratable recurring, proration, and linked discount amounts; v3 usage goes to its usage month and services to delivery day under default policy (SPEC 7, ADR-011). |

Customer, plan, price, subscription, invoice, line, and event foreign keys must resolve. A positive Stripe-channel Orb invoice will later have exactly one synced Stripe invoice before defect injection; marketplace `external` invoices never sync to Stripe (SPEC 4.6; ADR-015). Task 1.5 does not create Stripe rows.

## Cadence and calculations

| Terms | Invoice date | Service period and quantity |
|---|---|---|
| v3 Starter/Premium MAU | 1st of the next month | Prior calendar month; `max(0, distinct active users - free_units)` from the retained price-book row. First three free units are not invoice lines. |
| v3 Personal Plus | 1st of the service month | Current calendar month; one flat unit at retained v3 price until downgrade or churn. |
| v4 Standard/Premium seats | 1st of the service month | Current calendar month at seats held on the 1st. A mid-month held-seat addition is charged on the following invoice for days from add date through month end, inclusive; same-month removal takes effect next cycle. A full-seat login creates an auto seat and the same proration. |
| Enterprise direct or marketplace | Contract start and each annual anniversary, in advance; net 30 for direct | One year of recurring service at a time, with terms of 12, 24, or 36 months. Contract events set recurring ACV and separate one-time services. Marketplace invoices have `status = external` (SPEC 2.6; ADR-015). |
| Add-ons | Follow their price-book cadence and parent subscription | V4 tagged resources above the included 50 and Mullvad device packages of five; add-on units and discounts are separate lines. |

At a first-of-month voluntary migration, issue two separate invoices on that date: the final v3 MAU arrears invoice for the preceding month and the first v4 seat advance invoice for the current month. The v3 price and free-user allowance survive through the last v3 service day; the v4 price and held seats begin on migration day (SPEC 2.5). Billings count both service months separately; ARR uses only month-end run rate (ADR-007–009). A v3 tier upgrade or downgrade after 2026-04-08 retains v3 terms; only an explicit migration, reactivation, or enterprise renewal changes version.

Use `Decimal` local-currency prices, not floats. Compute each positive line from quantity × unit price × exact calendar-day fraction where relevant, then a separate linked discount line. Sum signed lines to `subtotal`; `discount_total` is the positive magnitude of discount lines; tax is zero; `total = subtotal` (SPEC 2.1, 4.6; ADR-020). ADR-025 provisionally selects half-up rounding per line and puts any daily-allocation residual on the last day. The worked examples use exact cent results, so no rounding convention changes their totals. FX never changes local invoices; reporting converts with committed FX rates (ADR-010, ADR-020).

Mutable Orb customers, subscriptions, and invoices append a new version with strictly increasing `_exported_at`, one latest row per key at extract time, and no export later than `extract_date`. As-of reconstruction chooses the latest version at or before the cutoff; a September issued invoice can still be seen at September close if voided in October (SPEC 8.1; ADR-012, ADR-018). Export lag and status changes must not make an earlier version disappear.

Payment state is a downstream rendering of lifecycle facts. A `PAYMENT_FAILED` transition on an eligible first-of-month invoice opportunity marks the linked invoice unpaid and supplies the later Stripe failure. `PAYMENT_RECOVERED` sets the retry and paid version on its recorded day; `DUNNING_EXPIRED` sets the involuntary churn/uncollectible outcome. Voluntary churn and reactivation dates likewise come from the transition log. Personal Plus follows its recorded dunning episodes. The billing and Stripe stages must share a deterministic invoice-to-transition link and cannot make fresh failure, recovery, or dunning draws. The current lifecycle executes first-of-month failure before voluntary migration, so one tailnet cannot both fail and migrate that day; a future change to that ordering requires an explicit invoice reference on the event. Stripe payment timing and fees are task 1.6, not implemented here.

## Worked examples

The service dates in these examples are inclusive. Every line shows the source price ID, quantity, local unit price, fraction, and signed amount. All customers bill in USD, tax is $0.00, and no credit notes or add-ons occur. IDs below are example labels. Invoice dates are separate from service months (SPEC 2.1–2.3, 2.5; ADR-007, ADR-009, ADR-020).

### 1. V4 Standard adds a seat on 2026-06-16

The tailnet holds four seats at 2026-06-01, adds one held seat on June 16, and holds five thereafter. `v4_standard` is $8.00 per seat-month. The June addition covers June 16–30: 15 of 30 days, so `1 × $8.00 × 15/30 = $4.00`. The next invoice carries that completed-month proration. There is no discount (`discount_total = $0.00`).

| Invoice date / ID | Line ID and type | Exact service period | Price ID | Quantity × unit × fraction | Amount |
|---|---|---|---|---|---:|
| 2026-06-01 / S-JUN | S1 fixed | 2026-06-01–2026-06-30 | `v4_standard` | 4 × $8.00 × 30/30 | $32.00 |
| 2026-07-01 / S-JUL | S2 fixed | 2026-07-01–2026-07-31 | `v4_standard` | 5 × $8.00 × 31/31 | $40.00 |
| 2026-07-01 / S-JUL | S3 proration | 2026-06-16–2026-06-30 | `v4_standard` | 1 × $8.00 × 15/30 | $4.00 |
| 2026-08-01 / S-AUG | S4 fixed | 2026-08-01–2026-08-31 | `v4_standard` | 5 × $8.00 × 31/31 | $40.00 |

| Invoice | Subtotal | Discount total | Tax | Total |
|---|---:|---:|---:|---:|
| S-JUN | $32.00 | $0.00 | $0.00 | $32.00 |
| S-JUL | $44.00 | $0.00 | $0.00 | $44.00 |
| S-AUG | $40.00 | $0.00 | $0.00 | $40.00 |

S-JUL has both a July advance line and a June service line. The proration belongs to June service, regardless of its July invoice date. No rounding residual exists.

### 2. V3 Starter migrates voluntarily on 2026-05-01

This nonprofit tailnet had seven distinct active users in March, eight in April, and eight held seats on May 1. The committed `v3_starter` row is $6.00 per active user-month with three free users. The committed `v4_standard` row is $8.00 per seat-month with no free users. `disc_nonprofit` is 50%, applied as a separate negative line to each positive base-plan line. The May 1 migration creates two invoices on the same date (SPEC 2.5).

| Invoice date / ID | Line ID and type | Exact service period | Price ID | Quantity × unit × fraction | Amount | Applies to |
|---|---|---|---|---|---:|---|
| 2026-04-01 / M-APR | M1 usage | 2026-03-01–2026-03-31 | `v3_starter` | (7 − 3) = 4 × $6.00 × 31/31 | $24.00 | — |
| 2026-04-01 / M-APR | M2 discount | 2026-03-01–2026-03-31 | `disc_nonprofit` | 50% × $24.00 | −$12.00 | M1 |
| 2026-05-01 / M-MAY-OLD | M3 usage | 2026-04-01–2026-04-30 | `v3_starter` | (8 − 3) = 5 × $6.00 × 30/30 | $30.00 | — |
| 2026-05-01 / M-MAY-OLD | M4 discount | 2026-04-01–2026-04-30 | `disc_nonprofit` | 50% × $30.00 | −$15.00 | M3 |
| 2026-05-01 / M-MAY-NEW | M5 fixed | 2026-05-01–2026-05-31 | `v4_standard` | 8 × $8.00 × 31/31 | $64.00 | — |
| 2026-05-01 / M-MAY-NEW | M6 discount | 2026-05-01–2026-05-31 | `disc_nonprofit` | 50% × $64.00 | −$32.00 | M5 |
| 2026-06-01 / M-JUN | M7 fixed | 2026-06-01–2026-06-30 | `v4_standard` | 8 × $8.00 × 30/30 | $64.00 | — |
| 2026-06-01 / M-JUN | M8 discount | 2026-06-01–2026-06-30 | `disc_nonprofit` | 50% × $64.00 | −$32.00 | M7 |

| Invoice | Subtotal, signed lines | Discount total | Tax | Total |
|---|---:|---:|---:|---:|
| M-APR | $12.00 | $12.00 | $0.00 | $12.00 |
| M-MAY-OLD | $15.00 | $15.00 | $0.00 | $15.00 |
| M-MAY-NEW | $32.00 | $32.00 | $0.00 | $32.00 |
| M-JUN | $32.00 | $32.00 | $0.00 | $32.00 |

The two May 1 invoice totals add to $47.00 but cover different service months. May month-end run-rate is $32.00, not $47.00. All discount and base amounts are exact cents after rounding.

### 3. V3 Premium remains on legacy MAU pricing

This tailnet does not migrate. It has nine distinct active users in March, ten in April, eight in May, and eight in June. `v3_premium` remains $18.00 per active user-month with three free users, even though v4 Premium is now seat-based at the same unit price. There is no discount (`discount_total = $0.00`).

| Invoice date / ID | Line ID and type | Exact service period | Price ID | Quantity × unit × fraction | Amount |
|---|---|---|---|---|---:|
| 2026-04-01 / P-APR | P1 usage | 2026-03-01–2026-03-31 | `v3_premium` | (9 − 3) = 6 × $18.00 × 31/31 | $108.00 |
| 2026-05-01 / P-MAY | P2 usage | 2026-04-01–2026-04-30 | `v3_premium` | (10 − 3) = 7 × $18.00 × 30/30 | $126.00 |
| 2026-06-01 / P-JUN | P3 usage | 2026-05-01–2026-05-31 | `v3_premium` | (8 − 3) = 5 × $18.00 × 31/31 | $90.00 |
| 2026-07-01 / P-JUL | P4 usage | 2026-06-01–2026-06-30 | `v3_premium` | (8 − 3) = 5 × $18.00 × 30/30 | $90.00 |

Each invoice has one line, subtotal equal to the amount, $0.00 tax, and total equal to subtotal: P-APR $108.00, P-MAY $126.00, P-JUN $90.00, P-JUL $90.00. The May 1 invoice is for April usage even though the v4 catalog began April 8. No v4 seat invoice or migration line is emitted. All amounts have exact cents.

## Proposed Finance policies applied in code

ADR-025 records these as Proposed pending Finance ratification. The generator applies them now so its output is testable.

- A mid-month v4 conversion or reactivation issues one immediate invoice for the inclusive remaining calendar days. A mid-month v4 tier change uses the old tier price through month end and the new tier at the next first-of-month invoice.
- Half-up rounding applies once per invoice line. Nonprofit and education discounts apply to base recurring, usage, and seat-proration lines, with linked negative lines; add-ons and services are excluded. Daily revenue allocation places any residual on the last service day.
- Personal Plus reactivation after retirement, if introduced later, restores the retained v3 price until a Product-approved retirement path exists. The current lifecycle does not generate this event.
- Successful direct invoices receive a paid version the next day; a recorded recovery pays the linked failed invoice on its recovery date. If the recorded dunning episode expires, an `adjustment` credit note with reason `uncollectible` is dated at churn. Lifecycle ordering keeps failure and migration from competing for a single day's invoice.
- Enterprise expansions issue an immediate supplementary invoice for the remaining contract-year days; the next anniversary uses the latest recorded ACV. Multi-year contracts invoice one contract year at a time. Marketplace invoices use the same cadence with `status = external` and no sync ID.
- Mullvad attachment is stable per tailnet. V3 usage-month add-ons use that month's measured devices; advance invoices use the previous month's device count, avoiding future-state reads. The first advance month has no measured prior-month device quantity. The interim channel-billings validation report converts local lines to USD at service-start FX; source invoices remain in customer currency.


# Orb billing design

Status: implemented in `generator/billing_orb.py`. It implements the provisional invoice policy in ADR-011 (Proposed, Finance-owned). `generator/tables.py` defines the ten Orb source contracts listed below. Billing consumes recorded lifecycle transitions, seat events, MAU facts, and immutable enterprise contract facts. It does not independently redraw churn, migration, payment failure, recovery, or dunning.

Governing rules: SPEC sections 2, 3, and 4; SCHEMAS `raw_orb`; ADR-003, ADR-005, ADR-008, ADR-011, and ADR-012. Every amount comes from `unit_amount_usd` in `seeds/price_book.csv`. USD is the only currency.

## Output tables

| Table | Grain |
|---|---|
| customers | One Orb customer per product tailnet, created at signup. Free Personal tailnets have a customer but never a subscription or invoice. |
| plans, prices | The price-book catalog, one plan per plan code and version and one price per price-book row. |
| subscriptions | One versioned subscription term per paid-plan period. |
| subscription_quantity_changes | Seat-quantity changes on v4 terms and contract seat counts on enterprise terms. |
| invoices | Versioned issue/payment states; issue date is distinct from service period. |
| invoice_line_items | Append-only signed line with inclusive service dates and a price ID. |
| credit_notes | Append-only adjustment linked to an unpaid invoice and involuntary churn. |
| events | One `user_active` usage event per v3 tailnet user and month. |
| daily_line_item_revenue | Each line's amount spread over its service days. |

The marts use customers, subscriptions, invoices, invoice_line_items, and credit_notes. dbt stages the others too (ADR-012).

The billing stage uses `sim.transitions` for plan starts, migration, churn, and recorded payment outcomes. `sim.seat_events` reconstructs invoice-time held seats and next-invoice additions. `sim.mau` supplies distinct v3 active users. `sim.contract_events` supplies enterprise ACV, dates, seats, and discount.

Orb price IDs are `op_<price_id>_usd`, where `<price_id>` is the price-book ID (for example `op_v4_standard_usd` for `v4_standard`).

## Cadence and calculations

| Plan | Invoice date | Billed service period |
|---|---|---|
| Starter/Premium v3 | First of following month | Prior month distinct active users less three free units. A zero usage line still produces an invoice. In the month a trial converts, the line starts on the subscription start and counts only users active from then (ADR-024). |
| Standard/Premium v4 | First of service month | Seats held at invoice time for the full calendar month. Mid-month seat additions appear on the next invoice for inclusive remaining days. |
| Enterprise | Contract start and each anniversary | One contract year per invoice, in advance, net 30. ACV uses recorded contracted seats, discount, Premium USD list price, and the minimum ACV. A multiyear term is never billed upfront. A mid-term expansion is invoiced on its date, prorated to the next anniversary. |

At a first-of-month migration, the final legacy arrears invoice and first v4 advance invoice share the migration date. Invoice subtotal is the sum of rounded lines; tax is zero and total equals subtotal. Nonprofit discount is a separate negative line linked to a positive base-plan line. Half-up rounding applies per line. Daily revenue allocates any residual cent to the last service day. An unpaid invoice at recorded involuntary churn receives an adjustment credit note dated at churn with reason `uncollectible`.

Invoice issue dates do not determine billings month: the service-period start does. Successful status versions and all payment failure, recovery, and dunning dates follow recorded simulation events.

## Worked examples

All amounts are USD and tax is $0.00. Price IDs below are price-book IDs; the Orb line carries `op_<price_id>_usd`. Dates are inclusive.

### 1. V4 Standard adds a seat on 2026-06-16

Four seats are held on June 1; one more is added June 16. The June addition is billed July 1 for 15/30 of June.

| Invoice date | Type | Service period | Price ID | Calculation | Amount |
|---|---|---|---|---|---:|
| Jun 1 | fixed | Jun 1–30 | `v4_standard` | 4 × $8 × 30/30 | $32.00 |
| Jul 1 | fixed | Jul 1–31 | `v4_standard` | 5 × $8 × 31/31 | $40.00 |
| Jul 1 | proration | Jun 16–30 | `v4_standard` | 1 × $8 × 15/30 | $4.00 |
| Aug 1 | fixed | Aug 1–31 | `v4_standard` | 5 × $8 × 31/31 | $40.00 |

Totals: Jun $32.00; Jul $44.00; Aug $40.00. No discount applies.

### 2. V3 Starter migrates on 2026-05-01

Seven active users in March and eight in April; eight seats on May 1. Nonprofit discount is 50% and links to each base line.

| Invoice date | Type | Service period | Price ID | Quantity/calculation | Amount |
|---|---|---|---|---|---:|
| Apr 1 | usage | Mar 1–31 | `v3_starter` | (7−3) × $6 | $24.00 |
| Apr 1 | discount | Mar 1–31 | `disc_nonprofit` | 50% of $24 | −$12.00 |
| May 1 | usage | Apr 1–30 | `v3_starter` | (8−3) × $6 | $30.00 |
| May 1 | discount | Apr 1–30 | `disc_nonprofit` | 50% of $30 | −$15.00 |
| May 1 | fixed | May 1–31 | `v4_standard` | 8 × $8 | $64.00 |
| May 1 | discount | May 1–31 | `disc_nonprofit` | 50% of $64 | −$32.00 |
| Jun 1 | fixed | Jun 1–30 | `v4_standard` | 8 × $8 | $64.00 |
| Jun 1 | discount | Jun 1–30 | `disc_nonprofit` | 50% of $64 | −$32.00 |

Invoice totals: Apr $12.00; May old $15.00 and May new $32.00; Jun $32.00. The two May 1 invoices cover separate service months.

### 3. V3 Premium retains legacy pricing

Nine, ten, eight, and eight active users in March through June. The legacy price remains $18 with three free users.

| Invoice date | Type | Service period | Price ID | Calculation | Amount |
|---|---|---|---|---|---:|
| Apr 1 | usage | Mar 1–31 | `v3_premium` | (9−3) × $18 | $108.00 |
| May 1 | usage | Apr 1–30 | `v3_premium` | (10−3) × $18 | $126.00 |
| Jun 1 | usage | May 1–31 | `v3_premium` | (8−3) × $18 | $90.00 |
| Jul 1 | usage | Jun 1–30 | `v3_premium` | (8−3) × $18 | $90.00 |

Each invoice has one usage line; subtotal and total equal that line amount.

These histories are deterministic pytest fixtures in `tests/generator/test_orb_billing.py`. Finance policy beyond the specified rules remains documented in ADR-009 and ADR-011.

## Test coverage

| Rule | Test |
|---|---|
| The three worked examples | `test_design_example_*` |
| Lines sum to subtotal; total = subtotal; tax 0; USD only | `test_all_orb_contracts_references_and_amounts` |
| Daily revenue sums to each line; residual on the last day | same, and `test_rounding_and_daily_last_day_residual` |
| Free Personal tailnets have no subscription | `test_lifecycle_cadence_and_no_trial_invoices` |
| No subscription or invoice line covers a trial day | `test_trials_are_never_invoiced` |
| Each credit note writes off its own unpaid, failed invoice in full at dunning expiry | `test_each_uncollectible_credit_note_writes_off_its_unpaid_invoice` |
| An enterprise year signed on 2024-02-29 renews on 2025-02-28; its daily revenue covers leap day | `test_annual_invoice_signed_on_leap_day_renews_on_february_28` |
| A 366-day service year spanning 2024-02-29 recognizes every day (dbt) | unit test `annual_invoice_spanning_leap_day` |
| Every active v3 and v4 month has exactly one invoice; migration month has two invoices on one date | `test_every_active_v3_and_v4_month_has_its_required_invoice` |
| Enterprise invoices one contract year per anniversary | `test_default_enterprise_annual_cadence_and_runtime` |
| One `uncollectible` credit note per involuntary churn | `test_all_orb_contracts_references_and_amounts` |

The trial test found and fixed one gap: a v3 usage line in a trial's conversion month used to cover the whole calendar month, including trial-period activity (ADR-024).

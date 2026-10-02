# Orb billing design

Status: implemented. The generator uses `generator/billing_orb.py`; `generator/tables.py` defines the five in-scope Orb source contracts. Billing consumes recorded lifecycle transitions, seat events, MAU facts, and immutable enterprise contract facts. It does not independently redraw churn, migration, payment failure, recovery, or dunning.

Governing rules: SPEC sections 2, 3, and 4; SCHEMAS `raw_orb`; ADR-003, ADR-005, ADR-008, and ADR-011. Every price ID and amount comes from `seeds/price_book.csv`. USD is the only supported currency.

## Inputs and output tables

| Table | Grain |
|---|---|
| customers | One Orb customer per product tailnet. |
| subscriptions | One versioned subscription term per paid-plan period. |
| invoices | Versioned issue/payment states; issue date is distinct from service period. |
| invoice_line_items | Append-only signed line with inclusive service dates and a price-book ID. |
| credit_notes | Append-only adjustment linked to an unpaid invoice and involuntary churn. |

The billing stage uses `sim.transitions` for plan starts, migration, churn, and recorded payment outcomes. `sim.seat_events` reconstructs invoice-time held seats and next-invoice additions. `sim.mau` supplies distinct v3 active users. `sim.contract_events` supplies enterprise ACV, dates, seats, and discount. Activity supplies device measures only where the selected billing policy needs them.

## Cadence and calculations

| Plan | Invoice date | Billed service period |
|---|---|---|
| Starter/Premium v3 | First of following month | Prior month distinct active users less three free units. A zero usage line still produces an invoice. |
| Standard/Premium v4 | First of service month | Seats held at invoice time for the full calendar month. Mid-month seat additions appear on the next invoice for inclusive remaining days. |
| Enterprise | Contract start and each anniversary | One contract year per invoice, in advance, net 30. ACV uses recorded contracted seats, discount, Premium USD list price, and minimum ACV floor. A multiyear term is never billed upfront. |

At a first-of-month migration, the final legacy arrears invoice and first v4 advance invoice share the migration date. Invoice subtotal is the sum of rounded lines; tax is zero and total equals subtotal. Nonprofit discount is a separate negative line linked to a positive base-plan line. Half-up rounding applies per line. Daily revenue allocates any residual cent to the last service day. An unpaid invoice at recorded involuntary churn receives an adjustment credit note dated at churn with reason `uncollectible`.

Invoice issue dates do not determine billings month: the service-period start does. Successful status versions and all payment failure, recovery, and dunning dates follow recorded simulation events.

## Worked examples

All amounts are USD and tax is $0.00. Line price IDs are the committed USD IDs. Dates are inclusive.

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

These histories are deterministic pytest fixtures. Finance policy beyond the specified rules remains documented in ADR-009 and ADR-011.

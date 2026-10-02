# seats-to-cash specification

Version: focused demo scope, October 2026. Owner: Jacob Willson.

## 1. Purpose and story

Wirefern is a fictional mesh networking company. This project shows one finance story: how monthly recurring revenue and annual recurring revenue change when legacy active-user plans move to seat pricing, and how those numbers tie through invoice, revenue, cash, and month-end close. All generated identities and business data are synthetic.

The demo runs locally on DuckDB and can run on Snowflake. Raw sources resemble Fivetran and Orb exports. dbt stages the sources, builds finance marts, and audits the ARR answer key and six planted defects. Hightouch sends a small account-signal model to Salesforce.

Simulation dates are 2023-01-01 through 2026-09-30. 2023 is opening-book burn-in; finance reporting begins 2024-01-01. Load dates may extend through 2026-10-31 for late September records. The committed calendar sets each period close on the fifth weekday of the next month.

## 2. Plans and billing rules

Every list price comes from `seeds/price_book.csv`; the committed USD amounts are the billing authority.

| Plan | Version | Basis | Price and rule |
|---|---|---|---|
| Personal | v3/v4 | Free | Never billed. |
| Starter | v3 | Active users, arrears | $6 per distinct active user-month after three free users. |
| Premium | v3 | Active users, arrears | $18 per distinct active user-month after three free users. |
| Standard | v4 | Seats, advance | $8 per seat-month. |
| Premium | v4 | Seats, advance | $18 per seat-month. |
| Enterprise | v3/v4 | Contract, annual advance | Custom ACV from contracted seats, Premium list price, and recorded discount. |

The v4 price boundary is 2026-04-08. A trial converts on the price version current on its conversion date. Existing v3 subscriptions retain their price until migration. Voluntary migrations occur on the first of a month. The migration month has two invoices on the same day: v3 arrears for the prior service month and v4 advance for the current month. There is no forced migration inside this simulation window.

For v4 seats, the first-of-month invoice covers the seats held at invoice time and the full calendar month. A mid-month seat addition is billed on the next invoice for remaining days, including the add date, over actual month days. A removal changes the next cycle only. An auto seat is an ordinary held-seat increase. Occupied seats begin at first login; invitations do not occupy seats; departures vacate seats without automatically reducing held seats. Held seats cannot be below occupied seats.

Trials and free Personal plans receive no invoices. Enterprise invoices cover one contract year at a time, on signing and each anniversary, with net 30 terms. Contracts longer than one year are not billed upfront. An involuntary churn with an unpaid invoice creates an adjustment credit note with reason `uncollectible`. Tax is zero. Each line is rounded half up to cents; invoice subtotals sum rounded lines. Daily allocation puts the residual on the final service day.

Nonprofit discount remains in scope at 50%, as a separate negative line linked to its discounted line. Internal Wirefern tailnets are free through the 100% internal discount. The only invoice currency is USD.

## 3. Sources, answer key, and defects

`raw_app` contains tailnets, users, seat events, plan changes, device registrations, daily and monthly activity, and feature usage. Orb supplies customers, subscriptions, invoices, invoice lines, and credit notes. Stripe supplies customer, invoice, charge, refund, and balance transaction. Salesforce supplies enterprise account and opportunity. Finance supplies a small `manual_adjustments.csv`, intended to become a Google Sheet synced by Fivetran.

The generator writes clean answer-key tables before injecting source defects: `truth_mrr_monthly`, `truth_revenue_monthly`, `truth_identity`, and `defect_manifest`. dbt audit models are the only SQL allowed to read truth.

Six defects are planted: D01 duplicate Stripe customer, D03 internal tailnets, D05 late refunds and credit notes, D06 duplicate Stripe invoice sync, D09 soft deletes, and D13 Stripe test-mode rows. No other defect codes are generated.

## 4. Metrics and finance definitions

MRR is the monthly run rate at month end, in USD. For v3 Starter and Premium, quantity is distinct active users less the three free users; monthly run rate applies the retained monthly price. For v4 Standard and Premium, quantity is seats held at month end. Enterprise MRR is contracted ACV divided by 12. ARR is 12 times MRR. Free plans have zero MRR.

ARR movements compare consecutive month-end states and classify new, expansion, contraction, churn, reactivation, and repricing. For a price or plan migration with unchanged quantity, the price-volume decomposition isolates repricing from expansion or contraction. The monthly ARR waterfall must close exactly.

Billings are grouped by service-period start month, not invoice issue month. Revenue recognizes v3 monthly usage in its service month, v4 seat consideration over the covered days, and enterprise consideration over its contract service period. The deferred-revenue rollforward is opening balance plus billings less revenue equals closing balance. Cash is successful Stripe charges less refunds and fees, tied to Stripe balance transactions. Finance adjustments are separately identified and approved.

Refunds default to reversing revenue when issued; late credit notes restate the issue month only when the selected policy says so.

## 5. dbt and close outputs

Staging models cast and normalize each in-scope source and apply the requested `as_of_ts`. Append-only rows use their load timestamp; entity rows use their creation timestamp; existing `raw_app` version logs retain their as-of version logic. Intermediate models include `int_identity`, `int_invoice_lines`, and `int_subscription_terms_monthly`.

Marts are `dim_customer`, `fct_mrr_monthly`, `fct_arr_movements`, `fct_revenue_monthly`, `fct_deferred_revenue_rollforward`, and `fct_billings_revenue_cash`. Audits include `audit_mrr_vs_truth` and `audit_defect_scorecard`. Required reconciliations are the ARR waterfall, deferred revenue rollforward, Orb-to-deduped-Stripe invoices, and Stripe charges less refunds and fees to balance-transaction net.

A close builds all close metrics as of the calendar date and appends them to `fct_close_ledger`. Later source rows produce `fct_restatements` with a reason. Migration exposure estimates current legacy MRR, projected v4 MRR, delta, and risk tier. `fct_account_signals` supplies Salesforce account ID, tailnet ID, ARR, held seats, utilization, migration risk, and sync eligibility.

## 6. Demo workflow

The fresh-clone path runs generation, DuckDB loading, dbt build, close history, and local dashboard queries. The Snowflake build is optional when credentials are available. Salesforce account signals are sent through Hightouch. The project is complete when the README reports measured results and every local acceptance command passes.

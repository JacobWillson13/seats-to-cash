# SPEC: seats-to-cash

Status: v1, October 2026. Owner: Jacob Willson.

## 1. Purpose

A work sample showing production-grade analytics engineering for a product-led SaaS finance team. The audience is an analytics engineering hiring panel and the Finance stakeholders they support. Everything in the repo should help answer one of three questions:

1. **ARR:** What is ARR, and how much of 2026 growth is repricing rather than real expansion?
2. **Close:** Do bookings, billings, revenue, and cash tie out at month-end, and what changed after the books closed?
3. **Growth and risk:** Where does paid growth come from, and which accounts are exposed when legacy pricing ends?

Success: a reviewer clones the repo, runs `make demo`, and within 10 minutes sees correct numbers, the tests that prove them, and the judgment calls behind them.

## 2. The company: Wirefern

Wirefern sells a mesh VPN. Individuals use it free, teams pay per seat, and enterprises sign annual contracts through sales. Its current pricing mechanics mirror the public pricing page of a well-known mesh VPN company as of October 2026 (see References). Legacy price points are illustrative. All customer data is synthetic.

Simulation: `sim_start_date` 2023-01-01 through `end_date` 2026-09-30. 2023 is a burn-in year that gives the company an opening book and deferred revenue an opening balance (ADR-019). All raw data is emitted from 2023; marts report from `reporting_start_date` 2024-01-01. Business events stop at `end_date`, but load timestamps can run to `extract_date` 2026-10-31, so September can still receive late rows.

### 2.1 Pricing versions

Every price lives in `seeds/price_book.csv`. Summary:

**v3 (legacy), sold 2023-01-01 through 2026-04-07**

| Plan | Basis | Price | Notes |
|---|---|---|---|
| Personal | free | $0 | up to 3 users |
| Personal Plus | flat | $5/month | up to 6 users (illustrative) |
| Starter | monthly active user | $6/active user/month | first 3 active users free (illustrative) |
| Premium | monthly active user | $18/active user/month | first 3 active users free (illustrative) |
| Enterprise | contract | custom | annual, sales-led |

**v4 (current), effective 2026-04-08**

| Plan | Basis | Price | Notes |
|---|---|---|---|
| Personal | free | $0 | up to 6 users |
| Standard | seat | $8/seat/month | replaces Starter |
| Premium | seat | $18/seat/month | same price, now per seat |
| Enterprise | contract | custom | annual, pay by invoice |

Add-ons: tagged resources beyond the 50 included at $1/resource/month (v4); Mullvad at $5/month per 5 devices (all versions).
Discounts: nonprofit and education at 50% (illustrative), emitted as a separate negative invoice line (`line_type = discount`) that points at the line it discounts. Internal tailnets (D03) get `disc_internal` at 100%.
Currencies: self-serve list prices are fixed per currency (USD, EUR, and GBP columns in the price book, ADR-020). Customers are billed in their own currency; exchange rates affect only USD reporting. Tax is out of scope and always 0.
Channels: self-serve (card through Stripe), sales (Enterprise, invoiced, ACH through Stripe), AWS Marketplace, Azure Marketplace.

### 2.2 Seat mechanics (v4)

- A tailnet holds N seats. An invoice is issued on the 1st of each month for the seats held at that moment, in advance, covering the calendar month.
- A user occupies a seat on first login or first device authentication, not on invite. Users pending approval occupy nothing.
- A user vacates a seat when removed, suspended, or deprovisioned. Seats are reusable within the month at no extra charge.
- Adding seats mid-month creates a prorated charge (days remaining including the add date, divided by days in the month), billed as a proration line on the next invoice.
- Removing seats mid-month changes nothing this month; the lower count bills next month.
- Seats held can never drop below seats occupied.
- If a user logs in while every seat is occupied, the seat count increases by one automatically (an "auto seat"), prorated like any other add.

### 2.3 v3 legacy mechanics

- Starter and Premium bill monthly in arrears on distinct active users in the prior month, minus 3 free users, floored at 0.
- Personal Plus bills a flat fee monthly in advance.

### 2.4 Signup routing and trials

- A tailnet created with a public email domain (gmail.com, outlook.com, and so on) is personal and lands on the free Personal plan. Classification uses `seeds/free_email_domains.csv`.
- A tailnet created with a custom domain is business and starts a 14-day trial with no user limit. At trial end it converts to a paid plan or falls back to Personal.
- Trials get Premium entitlements for the price version current at trial start (`seeds/plan_entitlements.csv`).
- The price version is set at conversion: a trial that converts on or after 2026-04-08 converts to v4, even if it started earlier.

### 2.5 The v4 transition (2026-04-08)

- New signups from 2026-04-08 see only v4 plans.
- Personal Plus is retired for new customers. Existing Personal Plus customers may keep it or move to free Personal; `personal.plus_retirement_downgrade_share` of them move, spread over the `personal.plus_retirement_window_days` days after 2026-04-08. Moving to free Personal is churn of that MRR.
- Self-serve legacy Starter and Premium customers may stay on legacy terms until the 2027-04-08 deadline, then must migrate (Starter to Standard, legacy Premium to Premium). Forced migrations take effect 2027-05-01, the first billing cycle after the deadline, which is outside the data window.
- Migration is one-way. The legacy "first 3 users free" perk does not carry over.
- Before the deadline, some legacy customers migrate voluntarily (hazard in config).
- Migrations take effect on the 1st of a month. In the migration month the customer receives two invoices on the same day: the final v3 arrears invoice for the prior month and the first v4 advance invoice for the current month. Billings spike; ARR must not.
- Legacy Enterprise contracts move to v4 terms at their next renewal.
- Reactivated customers return to the same tier on the price version current at reactivation.

### 2.6 Enterprise

- Sales-led through Salesforce. Terms are 12, 24, or 36 months, invoiced annually in advance, net 30, collected by ACH through Stripe.
- Contract value: ACV = contracted seats x 12 x the Premium seat list price in the contract currency x (1 - discount), with the discount drawn from `enterprise.discount_range` and a floor of `enterprise.min_acv_usd`. USD amounts in config convert to the contract currency at the contract-start rate.
- A business tailnet whose seats reach `enterprise.lead_seat_threshold` becomes a lead; `enterprise.lead_to_close` of leads close after a lag drawn from `enterprise.lead_to_close_lag_days`.
- At term end a contract renews with probability `enterprise.renewal_rate`, at a price uplift averaging `enterprise.renewal_uplift_mean`; otherwise it churns. Mid-term expansions arrive at `enterprise.expansion_monthly` and add on average `enterprise.expansion_seat_pct_mean` of contracted seats.
- Some contracts include one-time professional services (amount drawn from `enterprise.services_amount_usd`), recognized at delivery.
- Some enterprises run multiple tailnets under one Salesforce account.
- About a quarter of enterprise contracts are bought through AWS or Azure Marketplace. These never touch Stripe: the marketplace collects and pays out net of its fee through a monthly disbursement report.

## 3. Systems and data flow

```
product app DB (Postgres)  --Fivetran-->  raw_app
Orb (billing engine)       --export--->   raw_orb
Stripe (payments)          --Fivetran-->  raw_stripe
Salesforce (CRM)           --Fivetran-->  raw_salesforce
Marketplace reports, Finance Google Sheet  -->  raw_finance
ECB FX rates  --scripts/fetch_fx.py-->  seeds/fx_rates.csv (dbt seed)
Generator answer key       ---------->    raw_truth   (audit only)

raw_* -> dbt: staging -> intermediate -> marts -> Evidence report
                                              -> Hightouch -> Salesforce, Slack
```

Assumed system roles (ADR-005):
- The product DB is the source of truth for users, seats, and usage.
- Orb is the billing engine: subscriptions, metering, invoices, credit notes.
- Stripe collects payment. Orb invoices sync to Stripe with metadata `orb_invoice_id` and `payment_source = orb`.
- Salesforce holds accounts and opportunities for sales-led deals.

Identity keys:
- `tailnet_id` (app) = Orb `external_customer_id`
- Orb `payment_provider_id` = Stripe `customer.id`. It changes over time (D01); the `raw_orb.customers` version log keeps the history.
- Salesforce `account.tailnet_id__c` = `tailnet_id` (often missing or wrong, see D02)
- Marketplace `buyer_account_id` links to Salesforce through the opportunity reference (often missing, see D07)

## 4. Generator

### 4.1 Shape

Python package `generator/`. It reads `config/simulation.yml` and the seeds (`price_book.csv`, `plan_entitlements.csv`, `free_email_domains.csv`, `fx_rates.csv`, and `close_calendar.csv`, which places D05 rows), simulates day by day from `sim_start_date` to `end_date`, and writes Parquet to `data/raw/<source>/<table>.parquet`, with `<source>` in {app, orb, stripe, salesforce, finance}, and to `data/answer_key/<table>.parquet`. It also writes `data/raw/finance/manual_adjustments.csv` as the export for the Google Sheet step (SETUP 5). `generator/load.py` loads the Parquet into DuckDB schemas `raw_app`, `raw_orb`, `raw_stripe`, `raw_salesforce`, `raw_finance`, `raw_truth` (and later into Snowflake).

Mutable entities are emitted as version logs, one row per version; everything else is append-only (ADR-018). `generator/tables.py` is the source of truth for every raw table's columns, types, and sort keys.

Generation order: simulate clean, write the answer key from the clean state, then inject defects into the source tables only.

Modules:

| Module | Responsibility |
|---|---|
| `__main__.py` | CLI (`--config`, `--seed`, `--out`, `--no-defects`); runs the stages in order |
| `config.py` | pydantic models for the config, with cross-checks against the price book and other duplicated values |
| `pricebook.py` | price book loader: `list_price(plan_code, date)` for new sales, `price(price_id)` for existing subscriptions |
| `reference.py` | other seeds: free email domains, FX rates, plan entitlements, close calendar |
| `rng.py` | named, order-independent RNG substreams from one root `SeedSequence` |
| `ids.py` | deterministic vendor-style IDs |
| `clock.py` | simulation calendar, month boundaries, reporting tz helpers, proration fractions |
| `world.py` | in-memory simulation state passed between stages |
| `population.py` | people, companies, `.example` domains, signup schedule (Faker, seeded) |
| `lifecycle.py` | tailnet state machine and the planted mechanisms |
| `seats.py` | users, approvals, logins, seat ledger, auto seats |
| `activity.py` | daily active users, devices, feature usage, device registrations |
| `billing_orb.py` | subscriptions, quantity changes, invoices, lines, credit notes, usage events, daily revenue |
| `payments_stripe.py` | customers, synced invoices, charges, failures, refunds, balance transactions, payouts |
| `crm_salesforce.py` | users, products, accounts, opportunities, line items |
| `finance.py` | marketplace disbursements, manual adjustments |
| `defects.py` | defect injection and manifest |
| `truth.py` | answer key |
| `tables.py` | every raw and truth table: columns, types, primary and sort keys |
| `emit.py` | Parquet writer with stable sort order and fixed schemas |
| `load.py` | DuckDB and Snowflake loaders |

### 4.2 Lifecycle state machine (per tailnet)

States: `personal_free`, `personal_plus` (v3 only), `business_trial`, `starter` (v3), `standard` (v4), `premium` (v3 per active user or v4 per seat; the price version is an attribute), `enterprise`, `past_due`, `churned`.

Self-serve paid means `starter`, `standard`, or `premium`. Config keys are under `config/simulation.yml`; "x" means the hazard is multiplied when the condition holds.

| From | To | Trigger | Config keys |
|---|---|---|---|
| (signup) | `personal_free` | creator signs up with a public email domain | `population.personal_tailnets`, `population.signup_growth_monthly` |
| (signup) | `business_trial` | creator signs up with a custom domain | `population.business_tailnets`, `population.signup_growth_monthly`, `trial.length_days` |
| (signup) | self-serve paid, 100% discount | internal signup on wirefern.example (D03) | `population.internal_tailnets`; price book `disc_internal` |
| `personal_free` | `personal_plus` | monthly hazard, before `v4_effective_date` only | `personal.plus_upgrade_monthly` |
| `personal_plus` | `personal_free` | monthly hazard | `personal.plus_downgrade_monthly` |
| `personal_plus` | `personal_free` | Personal Plus retirement, spread over a window after `v4_effective_date` | `personal.plus_retirement_downgrade_share`, `personal.plus_retirement_window_days` |
| `business_trial` | `starter` (v3) or `standard` (v4) | trial end converts; version set by conversion date | `trial.base_conversion` x `trial.bring_to_work_multiplier` if the creator ran a personal tailnet first, x (1 - `trial.premium_share_at_conversion`) |
| `business_trial` | `premium` | trial end converts | as above, x `trial.premium_share_at_conversion` |
| `business_trial` | `personal_free` | trial end, no conversion | 1 - conversion probability |
| `standard` | `premium` | monthly hazard | `upgrades.standard_to_premium_monthly` x `upgrades.gated_feature_multiplier` after a gated attempt |
| `starter` | `premium` (v3) | monthly hazard | `upgrades.starter_to_premium_monthly` x `upgrades.gated_feature_multiplier` after a gated attempt |
| `premium` | `standard` (v4) or `starter` (v3) | monthly hazard; same price version | `upgrades.premium_to_standard_monthly` |
| `starter`, `premium` (v3) | `standard`, `premium` (v4) | voluntary migration on the 1st of a month after `v4_effective_date` | `migration.voluntary_monthly_hazard` x `migration.high_uplift_voluntary_multiplier` if uplift > `migration.high_uplift_threshold` |
| `starter`, `premium` (v3) | `standard`, `premium` (v4) | forced migration, effective 2027-05-01 (outside the window) | `legacy_forced_migration_date` |
| self-serve paid, `personal_plus` | `past_due` | failed payment on an invoice | `churn.payment_failure_rate` (per invoice) |
| `past_due` | previous state | payment recovered within dunning | `churn.dunning_recovery_rate`, `churn.dunning_days` |
| `past_due` | `churned` (involuntary) | dunning window ends unpaid | 1 - `churn.dunning_recovery_rate`, `churn.dunning_days` |
| self-serve paid | `churned` (voluntary) | monthly hazard | `churn.voluntary_monthly` x `seats.low_utilization_hazard_multiplier` under low utilization (`seats.low_utilization_threshold`, `seats.low_utilization_days`) x `migration.high_uplift_churn_multiplier` for high-uplift legacy customers from `v4_effective_date` |
| `churned` | previous tier (reactivation) | monthly hazard; price version current at reactivation | `churn.reactivation_monthly` |
| self-serve paid (business) | `enterprise` | seats reach the lead threshold, then Closed Won after a lag | `enterprise.lead_seat_threshold`, `enterprise.lead_to_close`, `enterprise.lead_to_close_lag_days`, `enterprise.term_months`, `enterprise.discount_range`, `enterprise.min_acv_usd`, `enterprise.services_attach_rate`, `enterprise.services_amount_usd`, `enterprise.marketplace_share`, `enterprise.multi_tailnet_share` |
| `enterprise` | `enterprise` (renewal; legacy terms move to v4) | term end | `enterprise.renewal_rate`, `enterprise.renewal_uplift_mean` |
| `enterprise` | `churned` | term end without renewal | 1 - `enterprise.renewal_rate` |
| `enterprise` | `enterprise` (expansion) | monthly hazard, mid-term | `enterprise.expansion_monthly`, `enterprise.expansion_seat_pct_mean` |

Seat movements within a state are not transitions: user growth (`seats.monthly_user_growth`), seat removal (`seats.removal_monthly`, x `seats.low_utilization_hazard_multiplier` under low utilization), headroom (`seats.headroom_seats_mean`), and auto seats (`seats.auto_seat_daily_prob_when_full`). A business tailnet with `crm.account_seat_threshold` or more seats gets a Salesforce account without changing state.

### 4.3 Planted mechanisms

These are real causal effects in the simulation. The analysis and the PQL score should recover them, and the README should say they were planted.

- **Utilization drives contraction:** tailnets under 60% seat utilization for 60+ days get 3x the seat-removal and voluntary churn hazard.
- **Gated features drive upgrades:** attempts to use features the current plan doesn't include (per `seeds/plan_entitlements.csv`; on Standard that means flow logs, log streaming, and just-in-time access) multiply the Standard-to-Premium and Starter-to-Premium hazards by 4.
- **Bring-to-work converts better:** business tailnets whose creator previously ran a personal tailnet convert from trial at 1.8x the base rate and add seats faster.
- **Repricing response:** legacy customers whose projected v4 bill is more than 40% above their v3 bill migrate voluntarily at half the base rate, and from 2026-04-08 their voluntary churn hazard is 1.5x: they leave instead of waiting for the deadline. Applying it from the announcement rather than at the forced migration keeps the effect inside the data window.

### 4.4 Bring-to-work linkage

People are simulated with a personal email and, if employed, a work email. The app DB never stores a person ID. The observable links are:
- `device_registrations.machine_key_hash`: the same machine registered to a personal tailnet and later to a business tailnet (account switching on one device). Strong signal.
- Email local-part match (`jane.doe@gmail.com` and `jane.doe@acme.example`). Weak signal, with false positives on common names.

The answer key records the true origin so precision and recall can be measured.

### 4.5 Scale defaults

| Entity | Default |
|---|---|
| personal tailnets | 25,000 |
| business tailnets (trials) | 3,000 |
| paying tailnets, ever | about 1,000 |
| enterprise accounts | about 60 |
| currencies | USD 85%, EUR 10%, GBP 5% |

Personal tailnets get monthly activity rollups only, to keep row counts small. Business tailnets get daily activity. Targets: under 2 GB of Parquet and under 5 minutes of generation time. `config/ci.yml` is a 10% overlay of `simulation.yml` for CI (task 1.2).

### 4.6 Generator invariants (pytest; must pass before load)

- Seats held >= seats occupied on every tailnet-day.
- Before defect injection, every Orb invoice with total > 0 on the Stripe channel has exactly one Stripe invoice.
- Orb invoice lines, including negative discount lines, sum to the invoice subtotal; total = subtotal + tax; tax is 0. `discount_total` is informational and equals minus the sum of discount lines.
- Version logs: per key, version timestamps strictly increase, exactly one version is active, and no load timestamp exceeds `extract_date`.
- Every charge belongs to a Stripe customer; every refund belongs to a charge; refunds never exceed the charge.
- Answer-key run-rate MRR for v4 seat tailnets equals seats held x list price x (1 - discount) + recurring add-ons at month-end.
- Two runs with the same seed produce identical file hashes.

## 5. Complexities and defects

**Complexities** are legitimate business behavior the models must handle correctly: proration, next-cycle seat removals, auto seats, annual prepay, multi-year terms, services, discounts, add-ons, legacy MAU billing with free users, the v4 migration, FX, marketplace fees, failed payments and recovery, reactivation, trials, Personal Plus retirement, and multiple tailnets per enterprise.

**Defects** are data problems the pipeline must detect and clean. Each is injected at the rate in `config/simulation.yml` and recorded in `raw_truth.defect_manifest` with the affected keys. A rate applies to its denominator, the natural population of the table it hits. The expected count is rate x denominator; PLAN 1.9's "within 10%" check is relative error against that count, with a floor of plus or minus 3 rows. D03 is the exception: it is generated in the population rather than injected, its count is `population.internal_tailnets`, the manifest lists the internal tailnet ids, and `--no-defects` sets the count to 0.

In version-logged tables (ADR-018), a defect that edits or deletes a row does so by appending a version.

| ID | Defect | Where | Denominator | Expected handling | Detecting test |
|---|---|---|---|---|---|
| D01 | Duplicate Stripe customer: card replaced, new customer created, Orb points to the new one, old one keeps history | raw_stripe.customer, raw_orb.customers (new version) | paying tailnets with a Stripe customer | identity spine maps both to the tailnet through Orb customer history or Stripe invoice metadata | each Stripe customer maps to exactly one tailnet |
| D02 | Salesforce account with missing (15%) or mistyped (3%) `tailnet_id__c` | raw_salesforce.account | Salesforce accounts linked to a tailnet | fallback match on website domain; unmatched queue | relationships test (warn) plus unmatched count |
| D03 | Internal tailnets on wirefern.example with a 100% discount | raw_app.tailnets | none: a count (`population.internal_tailnets`) | excluded from all finance marts | no internal tailnet in fct_mrr_monthly |
| D04 | Invoices issued at 23:00 to 23:59 Pacific on the last day of the prior month for next month's service | raw_orb.invoices | Orb invoices issued on the 1st | billings assigned by service period, not issue date | unit test on month assignment |
| D05 | Rows whose business date falls in a closed period but sync after that period's close date: refunds, credit notes, backdated manual adjustments, and late Salesforce changes (a Closed Won opportunity in a closed period whose amount or close_date is edited after the close date) | raw_stripe.refund, raw_orb.credit_notes, raw_finance.manual_adjustments, raw_salesforce.opportunity (new version) | per table, rows whose business date falls in a period that closes before `extract_date`; for opportunities, Closed Won opportunities with close_date in such a period | restatement log entries with reasons, never silent overwrites | restatements reference every late row |
| D06 | Orb invoice synced to Stripe twice after a retry | raw_stripe.invoice | Stripe invoices synced from Orb | dedupe on metadata `orb_invoice_id`, keep the non-void copy | unique orb_invoice_id among non-void Stripe invoices |
| D07 | Marketplace disbursement with a blank or mistyped opportunity reference | raw_finance.marketplace_disbursements | disbursement lines | match on buyer mapping, amount, and month; unmatched queue | match-rate test with threshold |
| D08 | Closed Won amount includes one-time services or a multi-year total | raw_salesforce.opportunity | Closed Won opportunities with services or a term over 12 months | bookings ARR from recurring line items only | CRM ARR vs billed ARR variance report |
| D09 | Soft-deleted rows (`_fivetran_deleted`, `is_deleted`) | Fivetran entity tables; never activity rollups (`tailnet_activity_daily`, `tailnet_activity_monthly`, `feature_usage_daily`) | keys per entity table | excluded in staging | no deleted keys downstream |
| D10 | Manual adjustment missing an approver, or keyed by account name instead of tailnet_id | raw_finance.manual_adjustments | manual adjustment rows (each subtype at its own rate) | name resolution; unapproved rows held out | approval and resolution tests |
| D11 | Stripe charge with no invoice (manual charge by support) | raw_stripe.charge | Stripe charges | classified non-recurring | orphan charge test |
| D12 | Orb seat quantity lags app DB seats by 1 to 5 days | raw_orb.subscription_quantity_changes | Orb seat quantity changes | billing vs product seat mismatch report | mismatch test (warn) |
| D13 | Stripe test-mode rows (`livemode = false`) | raw_stripe tables | rows per raw_stripe table | excluded in staging | no test-mode rows downstream |

## 6. Metric definitions

These are the contract. Mart column names match the bold names.

- **customer:** a billing account, meaning one paying tailnet. Enterprise rollups use `parent_account_id` (the Salesforce account). Enterprise logos count at the parent.
- **mrr_runrate_usd:** contracted recurring revenue at month-end; what the customer would pay next month if nothing changed.
  - v4 seat plans: seats held at month-end x list price x (1 - discount) + recurring add-ons
  - v3 MAU plans: max(0, active users in the month - 3) x list price x (1 - discount)
  - Personal Plus: the flat fee
  - Enterprise and marketplace: recurring annual contract value / 12 (services excluded)
  - Excludes proration, one-time charges, tax, and credits.
- **arr_usd:** mrr_runrate_usd x 12.
- **mrr_billed_usd:** recurring and usage revenue recognized in the month, including proration. It explains the gap between contracted and invoiced amounts.
- **movement_type:** each customer-month's ARR change decomposes into:
  - `new`: first month ever with ARR > 0
  - `reactivation`: ARR > 0 after one or more months at 0
  - `churn`: ARR goes to 0
  - `repricing`: change from price version, billing basis, or a lost legacy perk, holding quantity constant (6.1)
  - `expansion` / `contraction`: remaining change from quantity, tier, add-ons, or discount
  - `fx`: change from exchange rates on non-USD customers
- **NRR / GRR:** trailing 12 months on the cohort with ARR > 0 at the start of the window.
- **seat_utilization:** average occupied seats / seats held over the month.
- **bookings_arr_usd:** recurring ARR from Closed Won opportunities (new, expansion, renewal uplift) plus self-serve new and expansion ARR. Services and multi-year totals excluded.
- **billings_usd:** invoice totals excluding tax, assigned to the month of the service period start in reporting tz.
- **revenue_usd:** recognized revenue under section 7.
- **cash_usd:** Stripe charges net of refunds and fees by balance transaction date, plus marketplace net disbursements by disbursement date.
- **deferred_revenue_usd:** billed but not yet recognized.
- **pql_score:** the transparent points model in 8.4.

### 6.1 Repricing decomposition

For a customer whose terms change between month t-1 and month t (price version, billing basis, or legacy perk):

```
mrr_prev                = mrr_runrate at t-1 under the old terms
mrr_curr                = mrr_runrate at t under the new terms
mrr_curr_at_prev_terms  = month-t quantities priced under the t-1 terms
                          (MAU basis uses month-t active users; seat basis uses month-t seats held)
repricing               = mrr_curr - mrr_curr_at_prev_terms
volume                  = mrr_curr_at_prev_terms - mrr_prev   (expansion if > 0, contraction if < 0)
```

If terms don't change, repricing is 0. One customer-month can produce both a repricing row and an expansion or contraction row. Test: per customer-month, movements sum exactly to the ARR change.

## 7. Revenue recognition

Policy decisions belong to Finance. The defaults below are dbt vars, documented in ADR-011.

- Recurring and proration lines: ratably by day over the line's service period.
- v3 MAU usage lines (billed in arrears): recognized in the usage month.
- One-time services: at delivery (the line's service end date).
- Discounts: reduce the related line ratably.
- Credit notes and refunds: var `refund_treatment`, either `reverse_when_issued` (default) or `restate_original_period`.
- Marketplace: var `marketplace_revenue`, either `gross` (default; the fee is a cost) or `net`.
- Mullvad add-on: var `mullvad_treatment`, either `gross` (default) or `net` using `mullvad_net_rate` (illustrative 0.3).
- Deferred revenue rollforward per month: opening + billings - recognized +/- adjustments = closing. It must tie exactly.

## 8. dbt project

### 8.1 Layers

| Layer | Materialization | Purpose |
|---|---|---|
| staging | view | 1:1 with raw tables: rename, cast, convert money, filter deleted and test-mode rows, apply `as_of_ts` |
| intermediate | view or ephemeral | joins and business logic |
| marts | table | contracted, tested outputs |
| audit | table, group `audit`, access private | answer-key comparisons and the scorecard |
| close | incremental | the close ledger |

Staging reconstructs what the warehouse held at `var('as_of_ts')` (far-future default). That's how `make close` reproduces the books as they looked at close. Two macros do this, and no staging model filters on load timestamps any other way:
- `as_of_filter(column)`: append-only tables keep rows whose load timestamp (`_fivetran_synced`, `_exported_at`, or `_loaded_at`) is `<= as_of_ts`.
- `as_of_latest(pk, version_column)`: version-logged tables (ADR-018) keep, per primary key, the latest version whose version timestamp (`_fivetran_start` for Fivetran, `_exported_at` for Orb) is `<= as_of_ts`. Deleted flags are applied after the version is picked. `_fivetran_active` and `_fivetran_end` describe the log at extract time and are never used for as-of logic.

Filtering a versioned table on its load timestamp alone is wrong: an invoice issued in September and voided in October would vanish from the September close instead of showing as issued.

Marts report from `var('reporting_start_date')`. 2023 rows feed opening balances only.

### 8.2 Model inventory

Staging: one model per table in SCHEMAS.md.

Intermediate:
- `int_identity_spine`: tailnet_id to orb_customer_id, every stripe_customer_id, salesforce_account_id, parent_account_id, and marketplace buyer ids, with `match_method` and `match_confidence`.
- `int_unmatched_identities`: the review queue.
- `int_seat_ledger_daily`: tailnet x day: seats held, occupied, auto seats added, Orb billed quantity, mismatch flag (D12).
- `int_invoice_lines_unified`: Orb lines, marketplace lines, and approved manual adjustments in one schema, with `line_class` in (recurring, proration, usage, addon, one_time, discount, credit, tax).
- `int_subscription_terms_monthly`: tailnet x month: plan, price version, basis, quantity, list price, discount, currency, channel.
- `int_revenue_schedule`: line x day recognized amounts.
- `int_person_links`: bring-to-work candidate links with method and confidence.

Marts:
- `dim_customer`, `dim_plan_version`, `dim_date`
- `fct_mrr_monthly` (tailnet x month)
- `fct_arr_movements` (tailnet x month x movement_type)
- `fct_revenue_daily` (tailnet x day x revenue_type)
- `fct_deferred_revenue_rollforward` (month, plus tailnet x month)
- `fct_bookings_to_cash` (month x channel)
- `fct_close_ledger` (period x metric x run) and `fct_restatements`
- `fct_pricing_migration_exposure` (legacy tailnet)
- `fct_plg_funnel` and `fct_bring_to_work` (business tailnet)
- `fct_account_signals` (Salesforce account; the Hightouch source)
- `close_summary` (one row per close run; the Slack sync source)

Audit (group `audit`, access private):
- `audit_mrr_vs_truth`, `audit_revenue_vs_truth`, `audit_identity_vs_truth`, `audit_bring_to_work_vs_truth`
- `audit_defect_scorecard`: per defect code, injected count, detected count (manifest keys joined to stored test failures), and handled count (mart matches truth for the affected keys)

### 8.3 Tests

Generic: unique, not_null, relationships, and accepted_values on every primary key and enum.

Reconciliation (singular tests in `tests/reconciliation/`, severity error):
- ARR waterfall closes per month and per customer-month
- deferred revenue rollforward ties
- Orb invoice total equals the deduped Stripe invoice total for synced invoices
- Stripe charges minus refunds minus fees equals balance transaction net
- recognized revenue over a completed contract equals billings for that contract
- seats held >= seats occupied
- AR rollforward ties (billings minus cash)

Unit tests (dbt `unit_tests:`):
- proration in a 31-day and a 28-day month
- next-cycle seat removal
- auto seat
- annual invoice spanning 2024-02-29
- repricing cases: Starter to Standard with lost free users; legacy Premium MAU to Premium seats; no change
- month assignment for a 23:30 Pacific invoice (D04)
- as-of read of a version log: an invoice issued in September and voided in October shows as issued at the September close
- discount lines: a 50% nonprofit discount line reduces the line it applies to
- marketplace gross vs net

Fence check: `scripts/check_truth_fence.py` parses `target/manifest.json` and fails if any node outside `models/audit/` depends on `source('truth', ...)`.

### 8.4 PQL score (transparent, no ML)

Points on business tailnets during trial or their first 60 days:
- active users >= 5: +20
- SCIM configured: +15
- Premium-gated feature attempted: +20
- devices per user >= 3: +10
- bring-to-work origin: +15
- active on 7 or more trial days: +20

Report conversion rate by score band and top-decile lift against the answer key.

### 8.5 Pricing migration exposure

For tailnets still on v3 at the end of the data window:
- current v3 run-rate MRR
- projected v4 MRR = seats needed x v4 price, with `var('migration_seat_assumption')` set to `max_users_90d` (default) or `current_users`
- delta in dollars and percent, the 2027-04-08 deadline, and the 2027-05-01 forced migration effective date
- risk tier: High if delta > `var('migration_high_uplift_threshold')` (40%) and utilization proxy < `var('migration_low_utilization_threshold')` (60%); Medium if delta > the uplift threshold; Low otherwise
- portfolio summary: projected ARR change by month and account counts by tier

### 8.6 Close process

- `seeds/close_calendar.csv`: period and close_date, the 5th business day of the following month (weekends only, no holidays). Committed, built by `scripts/build_close_calendar.py`. The generator reads it to place D05 rows.
- `make close PERIOD=YYYY-MM` sets `as_of_ts` to the period's close date, builds the marts, runs reconciliation tests (fail hard), and appends period metrics to `fct_close_ledger` with a run id.
- Closing an already-closed period is refused unless `FORCE=1`.
- `make close-history` replays 2026-04 through 2026-09.
- `fct_restatements`: for each closed period, current value minus closed value by metric and customer, with `reason` attributed from late rows (late refund, late credit note, manual adjustment, late Salesforce change).
- `close_summary` feeds the Slack sync.

### 8.7 dbt vars

Every policy choice and run parameter. Defaults live in `dbt_project.yml`. Vars marked "duplicates config" also appear in `config/simulation.yml`, and config validation checks that the two match.

| Var | Default | Owner | Used by |
|---|---|---|---|
| `as_of_ts` | `9999-12-31 23:59:59` | Analytics engineering | staging as-of macros (8.1); `make close` sets it |
| `reporting_tz` | `America/Los_Angeles` (duplicates config) | Finance (ADR-009) | month and day assignment |
| `reporting_start_date` | `2024-01-01` (duplicates config) | Analytics engineering (ADR-019) | first month the marts report |
| `refund_treatment` | `reverse_when_issued` | Finance and the Controller (ADR-011) | revenue recognition (7) |
| `marketplace_revenue` | `gross` | Finance and the Controller (ADR-011) | revenue recognition (7) |
| `mullvad_treatment` | `gross` | Finance and the Controller (ADR-011) | revenue recognition (7) |
| `mullvad_net_rate` | `0.3` | Finance and the Controller (ADR-011) | revenue recognition when `mullvad_treatment = net` |
| `migration_seat_assumption` | `max_users_90d` | Finance (FP&A) | pricing migration exposure (8.5) |
| `migration_high_uplift_threshold` | `0.40` | Finance (FP&A) | migration risk tier (8.5) |
| `migration_low_utilization_threshold` | `0.60` | Finance (FP&A) | migration risk tier (8.5) |

## 9. Deliverables

1. Evidence report: static, on GitHub Pages, with an optional Funnel mirror. Five pages:
   - ARR: trend, waterfall with repricing, NRR and GRR, logos by plan
   - Revenue and close: billings vs revenue vs cash, deferred revenue, restatements
   - Pricing migration: legacy exposure, projected ARR change, risk tiers
   - Growth: funnel by cohort, bring-to-work share and lag, PQL lift
   - Data quality: defect scorecard, truth match rates, test counts
   Every page footer: "Synthetic data. Pricing mechanics modeled on public information."
2. dbt docs site on GitHub Pages.
3. LookML in `lookml/`: views for fct_mrr_monthly, fct_arr_movements, and dim_customer; one explore, `arr`; parsed with `lkml` in CI. Not tested on a live Looker instance, and the README says so.
4. Hightouch syncs: `fct_account_signals` to Salesforce Account (upsert on `tailnet_id__c`), and `close_summary` to Slack.
5. Legacy refactor: `legacy/legacy_arr_report.sql` and `docs/LEGACY_REFACTOR.md`.
6. README with real numbers, DECISIONS.md, and a 4-minute Loom.

## 10. Out of scope

Real company data, tax calculation, sales commissions, forecasting models, ML churn prediction, a live Looker instance, and a real Orb account.

## References

- Pricing and seat mechanics: https://tailscale.com/pricing (FAQ sections on seats, overages, legacy plans)
- Pricing v4 announcement: https://tailscale.com/blog/pricing-v4
- Orb and Stripe invoice sync: https://docs.withorb.com/integrations-and-exports/stripe
- Orb data exports: https://withorb.com/blog/data-exports
- Fivetran Stripe dbt package: https://github.com/fivetran/dbt_stripe
- Stripe test clocks: https://docs.stripe.com/billing/testing/test-clocks/api-advanced-usage
- dbt Fusion supported features: https://docs.getdbt.com/docs/fusion/supported-features
- dbt MRR modeling playbook: https://www.getdbt.com/blog/modeling-subscription-revenue

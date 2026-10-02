# seats-to-cash

A finance data stack for a fictional product-led networking company, Wirefern, built as an analytics engineering work sample. It answers one question end to end: **how much of ARR growth is real expansion, and how much is repricing as legacy active-user plans move to seat plans**, and do billings, revenue, and cash tie out along the way.

**All data is synthetic.** Pricing mechanics are modeled on Tailscale's public pricing page as of October 2026. I'm not affiliated with Tailscale and used no Tailscale data. Pre-April 2026 (v3) prices are illustrative.

## Results (default run, seed 42)

| | |
|---|---|
| ARR, Dec 2025 → Sep 2026 | $994,742.52 → **$1,641,205.80** (+$646,463.28, +65%) |
| Jan–Sep 2026 movements | new $431,443.68 · expansion $490,297.90 · **repricing $103,315.46** · contraction −$110,976.00 · churn −$301,373.76 · reactivation $33,756.00 |
| Repricing split | $22,392.00 from 44 tailnets migrating v3 → v4 · $80,923.46 from enterprise renewal uplifts |
| Jan–Sep 2026 billings / revenue / net cash | $1,132,596.21 / $983,440.66 / $1,108,245.80 (fees $14,578.97, refunds $3,726.38, credit notes $7,429.00) |
| Deferred revenue, 30 Sep 2026 | $478,489.70 |
| MRR vs. answer key | **14,924 / 14,924** tailnet-months match to the cent |
| Revenue vs. answer key | **15,247 / 15,247** tailnet-months match to the cent |
| Identity vs. answer key | 28,070 / 28,070 tailnets resolve to the true Stripe customer and Salesforce account |
| Planted defects handled | D01 13/13 · D03 40/40 · D06 70/70 · D09 103/103 · D13 80/80 |
| Reconciliations | ARR waterfall closes every month; deferred-revenue rollforward ties; Orb invoices = deduplicated Stripe invoices; Stripe charges − refunds − fees = balance-transaction net |
| `make demo` from a fresh clone | 56 s on a cloud container: 32 raw and answer-key tables, 107 dbt nodes (models, seeds, data tests, unit tests), all passing |

What the numbers say: most 2026 growth is new logos and seat expansion. Migration repricing is real but small so far ($22k of ARR), because only customers who chose to move to v4 have moved; the larger price effect this year is enterprise renewal uplift.

## Run it

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
make setup
make demo     # generate seed-42 data, load DuckDB, dbt build + tests, print the dashboard
```

Or step by step: `make data` (generate and load `data/seats_to_cash.duckdb`), `make build` (dbt build and the answer-key fence), `make dashboard` (run `analyses/dashboard/*.sql`), `make test` (every pytest suite). `make data CONFIG=config/ci.yml` builds a 10% dataset in about 10 seconds. `make snowflake` loads the same data into Snowflake and builds there; see [docs/SETUP.md](docs/SETUP.md).

## What's here

- **Plans:** free Personal; v3 Starter and Premium billed in arrears per active user after three free users; v4 Standard and Premium billed per seat in advance, with proration and auto seats; annual Enterprise contracts from product-led and direct-sales sources; a nonprofit discount. USD only.
- **Synthetic sources in vendor shapes**, all in [docs/SCHEMAS.md](docs/SCHEMAS.md):
  - the product database (`raw_app`);
  - an Orb billing export (`raw_orb`);
  - Stripe collections synced from Orb (`raw_stripe`);
  - enterprise Salesforce (`raw_salesforce`).
- **An answer key and six planted defects.** The generator writes true MRR, revenue, and identity before injecting defects: duplicate Stripe customers, internal tailnets, duplicate invoice syncs, soft deletes, and test-mode rows. Audit models score the marts against the key, and only those audit models may read it (`scripts/check_truth_fence.py`).
- **Repricing as its own ARR movement.** When a tailnet changes price version, the quantity change at the old per-unit price is expansion or contraction, and the remainder is repricing, so the waterfall closes exactly (ADR-007).
- **dbt on DuckDB and Snowflake:**
  - staging for every landed table;
  - identity resolution (`int_identity`);
  - marts: `fct_mrr_monthly`, `fct_arr_movements`, `fct_arr_waterfall`, `fct_revenue_monthly`, `fct_deferred_revenue_rollforward`, `fct_billings_revenue_cash`, and `dim_customer`;
  - reconciliation tests;
  - unit tests for proration and repricing.
- **Dashboard SQL** in [analyses/dashboard/](analyses/dashboard/): ARR trend, ARR waterfall by movement type, billings vs. revenue vs. cash, deferred revenue, and the defect scorecard.

## How it's built

```
generator (Python, seeded, offline)  ->  Parquet  ->  DuckDB raw_* schemas  (or Snowflake via write_pandas)
    raw_app · raw_orb · raw_stripe · raw_salesforce · raw_truth (answer key)
        -> dbt: staging -> intermediate -> marts, plus audit models against the answer key
        -> analyses/dashboard/*.sql
```

The simulation runs day by day from 2023-01-01 to 2026-09-30, with each day a Los Angeles business date (ADR-014). Billing facts come from recorded lifecycle events, never redrawn. The same seed writes byte-identical Parquet.

## Decisions

Every judgment call is in [docs/DECISIONS.md](docs/DECISIONS.md), including the policies that belong to Finance rather than to analytics engineering: revenue and refund timing (ADR-009, ADR-015) and the provisional invoice policy (ADR-011).

## Status

Tier 1 of [docs/PLAN.md](docs/PLAN.md) is complete. Next: migration exposure and Salesforce account signals, LookML, the month-end close with late refunds and credit notes (D05) and restatements, and CI. [docs/STATUS.md](docs/STATUS.md) records where the repo stands.

## Author

Jacob Willson

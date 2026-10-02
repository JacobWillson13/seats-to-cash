# seats-to-cash

A finance data stack for a fictional product-led networking company, Wirefern, built as an analytics engineering work sample.

**All data is synthetic.** Pricing mechanics are modeled on Tailscale's public pricing page as of October 2026. I'm not affiliated with Tailscale and used no Tailscale data. Pre-April 2026 (v3) prices are illustrative.

**Status:** work in progress. The synthetic source generator for the product database, Orb billing, and enterprise Salesforce is built and tested. Stripe, Finance adjustments, the answer key, defect injection, the DuckDB load, and everything from dbt onward are still to come. `docs/PLAN.md` lists the remaining tasks in order, and `docs/STATUS.md` records where the repo stands. Results go in this README once they are measured.

## The questions

1. **ARR:** What is ARR, and how much of 2026 growth is repricing rather than real expansion, as legacy active-user plans move to seat plans?
2. **Close:** Do billings, revenue, and cash tie out at month-end, and what changed after the books closed?
3. **Migration risk:** Which accounts are exposed when legacy pricing ends, and which enterprise accounts should Sales see in Salesforce?

## What's here

- **Plans:** free Personal; v3 Starter and Premium billed in arrears per active user after three free users; v4 Standard and Premium billed per seat in advance, with proration and auto seats; annual Enterprise contracts from product-led and direct-sales sources; a nonprofit discount. USD only.
- **Synthetic sources in vendor shapes:** a Fivetran-landed product database (`raw_app`), an Orb billing export (`raw_orb`), and enterprise Salesforce (`raw_salesforce`). Stripe (`raw_stripe`) and a Finance manual-adjustments sheet (`raw_finance`) are next. Every table is documented in [docs/SCHEMAS.md](docs/SCHEMAS.md).
- **Billing rules as tests:** worked invoice histories in [docs/BILLING_DESIGN.md](docs/BILLING_DESIGN.md) are pytest fixtures run against the production invoice code.
- **Deterministic generation:** the same seed and config write byte-identical Parquet, offline.

Planned (see PLAN): a hidden answer key and six planted defects so the models can be scored; dbt finance marts with repricing as its own ARR movement; month-end close with restatements; migration exposure; account signals synced to Salesforce through Hightouch; LookML; dashboard SQL; and an optional Snowflake build.

## Run it

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
make setup
make test-gen
make data CONFIG=config/ci.yml   # small dataset in data/
make data SEED=42                # full dataset
```

See [docs/SETUP.md](docs/SETUP.md).

## How it's built

```
product DB, Orb, Salesforce (built); Stripe, Finance sheet (next)   synthetic, vendor-shaped
        -> DuckDB (dev) / Snowflake (optional)
        -> dbt: staging -> intermediate -> marts, plus audit models against the answer key
        -> close ledger and restatements, LookML views, dashboard SQL
        -> Hightouch -> Salesforce Account fields
```

## Decisions

Every judgment call is in [docs/DECISIONS.md](docs/DECISIONS.md), including the policies that belong to Finance rather than to analytics engineering (revenue and refund timing in ADR-009, the provisional invoice policy in ADR-011).

## Author

Jacob Willson

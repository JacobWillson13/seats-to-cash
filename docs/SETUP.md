# Setup

Local generation and dbt run on Python 3.12 with `uv`. Cloud steps are conditional on having the relevant accounts and credentials; credentials stay in `.env`, never in git.

## Local toolchain

```bash
make setup                       # uv sync, dbt deps once dbt exists, pre-commit install
make test-gen
make lint
make data CONFIG=config/ci.yml   # small dataset; `make data SEED=42` for the full one
make build                       # dbt seed, run, and test on DuckDB, then the truth fence
```

`make data` writes Parquet under `data/` and loads it into `data/seats_to_cash.duckdb`; `make build` builds every dbt model into that file (`DUCKDB_PATH` overrides the path). `make test` runs every pytest suite.

The committed seeds in `seeds/` are ready to use. Generation does not rebuild seeds or need network access; only `make seeds` rebuilds them, and it needs the network.

## Snowflake

Create an XSMALL warehouse with auto-suspend, a raw database, an analytics database, and a transform role. Use key-pair authentication for dbt. Put `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_PRIVATE_KEY_PATH` in `.env` (see `.env.example`); `profiles.yml` reads those values through `env_var()`. `make snowflake` (PLAN task e) loads Parquet using `write_pandas` and runs `dbt build --target snowflake`; the owner runs it locally. Suspend the warehouse after testing.

## Salesforce enterprise sync

Create a Salesforce Developer Edition org. Add Account fields `Tailnet_ID__c` (unique external ID), `ARR__c` (currency), `Seats_Held__c` (number), `Seat_Utilization__c` (percent), `Migration_Risk_Tier__c` (picklist), and `Sync_Eligible__c` (checkbox). The generated Salesforce source is enterprise-only: accounts, opportunities, leads for direct-sales accounts, and the single owning sales user (`docs/SCHEMAS.md`).

## Hightouch

Connect Hightouch to Snowflake with a read-only service user and connect Salesforce through OAuth. Configure one manual upsert to Account using `Tailnet_ID__c` as the match key and `fct_account_signals` as the model. Map ARR, held seats, seat utilization, migration risk tier, and sync eligibility. Limit syncs to eligible accounts.

## Finance Google Sheet and Fivetran

The generator will write `data/raw/finance/manual_adjustments.csv` (PLAN task b). Import it into a Google Sheet with a header row and named range. Configure Fivetran Google Sheets to load that range into Snowflake `raw_finance.manual_adjustments`. DuckDB continues to load the local CSV.

# Setup

Local generation and dbt run on Python 3.12 with `uv`. Cloud steps are conditional on having the relevant accounts and credentials; credentials stay in `.env`, never in git.

## Local toolchain

```bash
uv sync
uv run pre-commit install
make test-gen
make lint
make data CONFIG=config/ci.yml
make build
```

Committed USD price and entitlement seeds are ready to use. Generation does not rebuild seeds or need network access. `make demo` is the DuckDB path and is the final README command.

## Snowflake

Create an XSMALL warehouse with auto-suspend, a raw database, an analytics database, and a transform role. Use key-pair authentication for dbt. Put `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_PRIVATE_KEY_PATH` in `.env`; `profiles.yml` reads those values through `env_var()`. The optional final task loads Parquet using `write_pandas` and runs `dbt build --target snowflake`. Suspend the warehouse after testing.

## Salesforce enterprise sync

Create a Salesforce Developer Edition org. Add Account fields `Tailnet_ID__c` (unique external ID), `ARR__c` (currency), `Seats_Held__c` (number), `Seat_Utilization__c` (percent), `Migration_Risk_Tier__c` (picklist), and `Sync_Eligible__c` (checkbox). Enterprise accounts and opportunities are the only Salesforce source rows in this project.

## Hightouch

Connect Hightouch to Snowflake with a read-only service user and connect Salesforce through OAuth. Configure one manual upsert to Account using `Tailnet_ID__c` as the match key and `fct_account_signals` as the model. Map ARR, held seats, seat utilization, migration risk tier, and sync eligibility. Limit syncs to eligible accounts.

## Finance Google Sheet and Fivetran

The generator writes `data/raw/finance/manual_adjustments.csv`. Import it into a Google Sheet with a header row and named range. Configure Fivetran Google Sheets to load that range into Snowflake `raw_finance.manual_adjustments`. DuckDB continues to load the local CSV.

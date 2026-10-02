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

## Snowflake (`make snowflake`, run locally)

`make snowflake` loads the Parquet that `make data` wrote under `data/` into Snowflake with `write_pandas`, then runs `dbt build --target snowflake`. It needs a Snowflake account and key-pair credentials in `.env`; nothing else changes.

1. **Generate the data** with `make data SEED=42`, or `make data CONFIG=config/ci.yml` for a quick run.
2. **Create a key pair** for the dbt user:
   ```bash
   mkdir -p ~/.snowflake
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/.snowflake/seats_to_cash_rsa.p8 -nocrypt
   openssl rsa -in ~/.snowflake/seats_to_cash_rsa.p8 -pubout -out ~/.snowflake/seats_to_cash_rsa.pub
   ```
3. **Create the warehouse, role, database, and user.** Run this once as `ACCOUNTADMIN`, pasting the public key body without its header and footer lines:
   ```sql
   create warehouse if not exists TRANSFORMING warehouse_size = xsmall auto_suspend = 60 initially_suspended = true;
   create role if not exists TRANSFORMER;
   create database if not exists SEATS_TO_CASH;
   grant usage on warehouse TRANSFORMING to role TRANSFORMER;
   grant ownership on database SEATS_TO_CASH to role TRANSFORMER;
   create user if not exists DBT_TRANSFORMER default_role = TRANSFORMER default_warehouse = TRANSFORMING
     rsa_public_key = '<public key body>';
   grant role TRANSFORMER to user DBT_TRANSFORMER;
   ```
4. **Fill in `.env`:** `cp .env.example .env`, then set:
   - `SNOWFLAKE_ACCOUNT`: the account identifier, for example `ab12345.us-east-1` or `orgname-accountname`.
   - `SNOWFLAKE_PRIVATE_KEY_PATH`: an absolute path, because dbt does not expand `~`.
   - The user, role, warehouse, and database, if they differ from the defaults. `.env` is git-ignored.
5. **Install the Snowflake group:** `uv sync --group snowflake`.
6. **Check the plan without connecting:** `uv run --group snowflake python scripts/snowflake_load.py --dry-run` lists each `SEATS_TO_CASH.RAW_<SOURCE>.<TABLE>` it will replace.
7. **Run `make snowflake`.** The loader creates the `RAW_*` schemas and replaces each raw table, with upper-case names and logical types. dbt then builds seeds, staging, intermediate, marts, and audits into the `STAGING`, `INTERMEDIATE`, `MARTS`, `AUDIT`, and `SEEDS` schemas, and runs every test.
8. **Suspend the warehouse** afterwards: `alter warehouse TRANSFORMING suspend;`.

Raw schemas live in the same database as the dbt schemas (ADR-021). The dashboard queries in `analyses/dashboard/` are written in Snowflake syntax against the `MARTS` and `AUDIT` schemas.

## Salesforce enterprise sync

Create a Salesforce Developer Edition org. Add Account fields `Tailnet_ID__c` (unique external ID), `ARR__c` (currency), `Seats_Held__c` (number), `Seat_Utilization__c` (percent), `Migration_Risk_Tier__c` (picklist), and `Sync_Eligible__c` (checkbox). The generated Salesforce source is enterprise-only: accounts, opportunities, leads for direct-sales accounts, and the single owning sales user (`docs/SCHEMAS.md`).

## Hightouch

Connect Hightouch to Snowflake with a read-only service user and connect Salesforce through OAuth. Configure one manual upsert to Account using `Tailnet_ID__c` as the match key and `fct_account_signals` as the model. Map ARR, held seats, seat utilization, migration risk tier, and sync eligibility. Limit syncs to eligible accounts.

## Finance Google Sheet and Fivetran

The generator will write `data/raw/finance/manual_adjustments.csv` (PLAN task b). Import it into a Google Sheet with a header row and named range. Configure Fivetran Google Sheets to load that range into Snowflake `raw_finance.manual_adjustments`. DuckDB continues to load the local CSV.

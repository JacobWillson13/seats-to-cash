-- seats-to-cash: Snowflake setup, run once as ACCOUNTADMIN.
-- Reference copy with key placeholders. Don't re-run as-is.
use role accountadmin;

-- Warehouse
create warehouse if not exists TRANSFORMING
  warehouse_size = xsmall auto_suspend = 60 auto_resume = true initially_suspended = true;

-- Loader and dbt: TRANSFORMER creates and owns SEATS_TO_CASH
create role if not exists TRANSFORMER;
grant usage, operate on warehouse TRANSFORMING to role TRANSFORMER;
grant create database on account to role TRANSFORMER;
grant role TRANSFORMER to role SYSADMIN;

create user if not exists DBT_TRANSFORMER
  type = service default_role = TRANSFORMER default_warehouse = TRANSFORMING;
alter user DBT_TRANSFORMER set rsa_public_key = '<dbt public key>';
grant role TRANSFORMER to user DBT_TRANSFORMER;

-- Hightouch: read-only. Run after the first make snowflake creates SEATS_TO_CASH.
create role if not exists REPORTER;
grant usage on warehouse TRANSFORMING to role REPORTER;
grant usage on database SEATS_TO_CASH to role REPORTER;
grant usage on all schemas in database SEATS_TO_CASH to role REPORTER;
grant usage on future schemas in database SEATS_TO_CASH to role REPORTER;
grant select on all tables in database SEATS_TO_CASH to role REPORTER;
grant select on future tables in database SEATS_TO_CASH to role REPORTER;
grant select on all views in database SEATS_TO_CASH to role REPORTER;
grant select on future views in database SEATS_TO_CASH to role REPORTER;

create user if not exists HIGHTOUCH_READER
  type = service default_role = REPORTER default_warehouse = TRANSFORMING;
alter user HIGHTOUCH_READER set rsa_public_key = '<hightouch public key>';
grant role REPORTER to user HIGHTOUCH_READER;

-- Streamlit app
create schema if not exists SEATS_TO_CASH.APPS;

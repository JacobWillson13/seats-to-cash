# CLAUDE.md

Instructions for coding agents. `AGENTS.md` is a symlink to this file.

## Project

seats-to-cash is a focused synthetic finance demo for Wirefern. Its story is ARR growth and the split between repricing and real expansion as v3 active-user plans move to v4 seat plans. DuckDB is the local warehouse; Snowflake is the optional cloud target. dbt builds the finance marts and close outputs. Hightouch syncs eligible account signals to Salesforce.

## Read order

1. `docs/SPEC.md`
2. `docs/SCHEMAS.md`
3. `docs/PLAN.md`
4. `docs/DECISIONS.md`
5. `docs/SETUP.md`

## Scope

In scope: Personal free; Starter/Premium v3 MAU arrears; Standard/Premium v4 seat advance with proration and auto seats; annual Enterprise from PLG and direct-sales sources; nonprofit discount; USD only; raw_app, raw_orb, raw_stripe, enterprise raw_salesforce, and Finance manual adjustments; defects D01/D03/D05/D06/D09/D13; truth_mrr_monthly, truth_revenue_monthly, truth_identity, defect_manifest, and truth_enterprise_contracts; DuckDB/dbt/Snowflake, closes, Hightouch to Salesforce, LookML, and dashboard SQL.

Features set the scope boundary, not raw tables (ADR-012). Keep every raw table the generator writes and tests, document it in `docs/SCHEMAS.md`, and stage it in dbt; marts use only what the story needs. Features outside this list keep their code but are disabled in config; validation rejects nonzero values for them (ADR-012). Mention them only in config comments and `docs/SCHEMAS.md`.

## Hard rules

- Synthetic people and companies only; use `.example` for invented business domains.
- The answer key is restricted to audit models and generator/tests. Run `scripts/check_truth_fence.py` after dbt work.
- Deterministic generation: simulation clock only, explicit NumPy RNG streams, stable ordering, fixed Parquet options. Never use wall-clock time, stdlib random, unseeded RNG, or hash-dependent output order.
- `seeds/price_book.csv` is the single price authority. No hardcoded plan IDs or prices in Python/SQL.
- USD only. Stripe minor units are integer cents; Orb amounts are decimal strings; marts use `numeric(18,2)` USD.
- Reporting timezone is America/Los_Angeles. Billings month uses service-period start; revenue uses recognition date; cash uses settlement date; ARR uses month-end state.
- Preserve raw_app version logs. Other entity source staging uses `as_of_ts` on creation time; append-only staging uses load time.
- No credentials in git. `profiles.yml` reads secrets from `.env`. Keep `.env`, private keys, `data/`, `target/`, and generated build outputs ignored.
- Add dependencies to the DECISIONS dependency log.

## Commands

| Command | Purpose | Available |
|---|---|---|
| `make setup` | Install locked dependencies and hooks | now |
| `make data SEED=42` | Generate source Parquet and load the DuckDB raw schemas | now |
| `make test-gen` | Generator invariants, fixtures, determinism, and offline checks | now |
| `make lint` | Ruff checks and formatting | now |
| `make seeds` | Rebuild the committed email-domain and close-calendar seeds | now |
| `make build` | dbt build on DuckDB, then the truth-fence check | now |
| `make test` | Every pytest suite | now |
| `make close PERIOD=2026-09` | Build and append one as-of close (`FORCE=1` replaces; `TARGET=snowflake`) | now |
| `make close-history` | Replay April–September 2026 closes, then rebuild (`TARGET=snowflake`) | now |
| `make dashboard` | Run `analyses/dashboard/*.sql` on DuckDB | now |
| `make dashboard-snowflake` | Compile the dashboard SQL for Snowflake and print the file paths | now |
| `make snowflake-compile` | Compile the whole dbt project for Snowflake without connecting | now |
| `make snowflake` | Snowflake load and dbt build, run locally or from the `snowflake` workflow by the owner | now |
| `make demo` | Fresh-clone DuckDB demo | now |

## Workflow

Work on `main`, unless the session assigns a branch; then work and push there. Read the next remaining task in PLAN and its acceptance criteria. Make one task's changes, run required checks, commit, run `git pull --rebase origin main`, then push. Never force-push. Use the repository commit style `<area>: <change>`.

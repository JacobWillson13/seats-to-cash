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

In scope: Personal free; Starter/Premium v3 MAU arrears; Standard/Premium v4 seat advance; annual Enterprise; nonprofit discount; raw_app, five Orb tables, five Stripe tables, enterprise Salesforce accounts/opportunities, Finance manual adjustments; defects D01/D03/D05/D06/D09/D13; truth_mrr_monthly, truth_revenue_monthly, truth_identity, defect_manifest; DuckDB/dbt/Snowflake, closes, Hightouch to Salesforce, LookML, and dashboard SQL.

Treat this scope as the project boundary; tests and documentation should describe these sources and outputs.

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

| Command | Purpose |
|---|---|
| `make setup` | Install locked dependencies and hooks |
| `make data SEED=42` | Generate source Parquet and load DuckDB raw schemas |
| `make test-gen` | Generator invariants, fixtures, determinism, and offline checks |
| `make lint` | Ruff checks and formatting |
| `make build` | dbt build on DuckDB |
| `make close PERIOD=2026-09` | Build and append one as-of close |
| `make close-history` | Replay April–September 2026 closes |
| `make snowflake` | Optional Snowflake load and dbt build |
| `make demo` | Fresh-clone DuckDB demo |

## Workflow

Work on `main`. Read the next remaining task in PLAN and its acceptance criteria. Make one task's changes, run required checks, commit, run `git pull --rebase origin main`, then push. Never force-push. Add a STATUS update after each completion tag. Use the repository commit style `<area>: <change>`.

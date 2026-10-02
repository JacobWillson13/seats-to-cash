# CLAUDE.md

Context and rules for coding agents working in this repo. Read this first, every session.

## What this is

seats-to-cash is a work sample for an Analytics Engineer application. It simulates a fictional product-led networking company, **Wirefern**, whose pricing mechanics mirror a real company's public pricing page, and builds a production-style finance data stack on top of it:

- synthetic source data landed in the same shapes Fivetran and Orb produce
- a dbt project (DuckDB for dev, Snowflake for the final run)
- reconciliation and month-end close tooling
- reverse ETL to Salesforce and Slack through Hightouch
- a static BI report (Evidence) plus LookML as code

The demo exists to prove three things to a hiring panel:

1. ARR is modeled correctly, including separating repricing from real expansion.
2. Bookings, billings, revenue, and cash tie out at month-end, with an audit trail for anything that changes after close.
3. The test suite catches planted data defects, measured against a hidden answer key.

## Read order

1. `docs/SPEC.md`: what we're building and every business rule.
2. `docs/SCHEMAS.md`: raw table contracts for every source.
3. `docs/PLAN.md`: task list, acceptance criteria, cut order. Work from here.
4. `docs/DECISIONS.md`: modeling decisions. Follow them; propose changes there instead of silently deviating.
5. `docs/SETUP.md`: accounts, environment, and commands.

Config and shared data: `config/simulation.yml` (generator parameters) and `seeds/price_book.csv` (every price, read by both the generator and dbt).

## Hard rules

- **Synthetic only.** No real company names, people, logos, or customer data. The company is Wirefern; its domain is wirefern.com. Faker output must use fake domains.
- **The answer key is fenced.** Nothing outside `models/audit/` may read `source('truth', ...)` or `data/answer_key/`. `scripts/check_truth_fence.py` enforces this in CI. If a mart needs a fact, derive it from raw sources.
- **Deterministic generator.** The same `SEED` and config produce byte-identical Parquet. Never call `datetime.now()`, never use unseeded randomness, and never let output order depend on dict or set hashing. Use the simulation clock and pass `numpy.random.default_rng(seed)` explicitly.
- **The price book is the single source of truth** for prices: `seeds/price_book.csv`. Never hardcode a price, plan code, or price ID in SQL or Python.
- **Policy choices are dbt vars**, never hardcoded. See SPEC section 7. Defaults live in `dbt_project.yml`.
- **Cross-database SQL.** Every model must run on DuckDB and Snowflake. Use dbt cross-database macros (`dbt.date_trunc`, `dbt.dateadd`, `dbt.datediff`, `dbt.safe_cast`, `dbt.type_*`) and `dbt_utils` instead of dialect-specific functions. If a dialect difference is unavoidable, write a dispatched macro in `macros/`.
- **Money:** raw Stripe amounts are integer minor units (cents); raw Orb amounts are decimal strings; marts use `numeric(18,2)` USD plus original-currency columns. Convert in staging, once.
- **Time:** raw timestamps are UTC. The reporting timezone is `America/Los_Angeles` (var `reporting_tz`). Month assignment rules are in DECISIONS ADR-009. Never bucket by an issue or created timestamp without checking that ADR.
- **No secrets in git.** Credentials come from `.env` through `env_var()` in `profiles.yml`. `.env`, `*.p8`, `data/`, `target/`, and `reports/build/` are gitignored.
- **New dependencies** get a one-line note in the dependency log at the bottom of DECISIONS.md.

## Conventions

- Python 3.12, managed with uv. The generator is a package in `generator/`; entry point `python -m generator`.
- dbt naming: `stg_<source>__<entity>`, `int_<purpose>`, `fct_<process>`, `dim_<entity>`, `audit_<check>`. One model per file.
- SQL style: lowercase keywords, CTEs named for what they hold, a final `select * from final`, no `select *` directly from a source. SQLFluff with `.sqlfluff` is the arbiter.
- Every mart has a description, column descriptions, a model contract, primary-key tests, and at least one business-rule test.
- Any logic involving dates, proration, classification, or money math gets dbt `unit_tests:`.
- Tests that detect planted defects set `store_failures: true` so the defect scorecard can join to them.
- Commit messages: `<area>: <what changed>`, for example `gen: add orb proration lines` or `dbt: arr movements with repricing`.

## Commands (Makefile targets built during the plan)

| Command | Does |
|---|---|
| `make setup` | uv sync, dbt deps, pre-commit install |
| `make data SEED=42` | run the generator, write Parquet, load DuckDB raw schemas |
| `make test-gen` | pytest invariants on generator output |
| `make build` | `dbt build` on DuckDB (models and tests) |
| `make docs` | `dbt docs generate --static` |
| `make scorecard` | build audit models and print the defect scorecard |
| `make close PERIOD=2026-09` | as-of build for a period, reconcile, append to the close ledger |
| `make close-history` | replay closes for 2026-04 through 2026-09 |
| `make report` | build the Evidence static site into `reports/build` |
| `make snowflake` | load raw to Snowflake, `dbt build --target snowflake`, parity check |
| `make demo` | setup, data, build, scorecard, report: the fresh-clone path, under 5 minutes |

## How to work a task

1. Pick the next unchecked task in `docs/PLAN.md` and read its acceptance criteria before writing code.
2. Make the smallest change that satisfies it. Don't start the next task in the same change.
3. Run `make build` (plus `make test-gen` for generator work). Everything green before you call it done.
4. Check the box in PLAN.md and add a one-line note under the task if anything surprised you.
5. If you chose between reasonable alternatives, add or update an ADR in DECISIONS.md.

If a rule here conflicts with a task, stop and say so instead of picking one.

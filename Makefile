# seats-to-cash. Targets are added as PLAN tasks land; see CLAUDE.md for the full list.

SEED ?= 42
CLOSE_PERIODS := 2026-04 2026-05 2026-06 2026-07 2026-08 2026-09
CONFIG ?= config/simulation.yml
DBT := uv run dbt
DBT_ARGS := --profiles-dir .

.PHONY: setup seeds data test-gen test lint build fence snowflake dashboard demo close close-history

setup:  ## uv sync, dbt deps (once dbt_project.yml exists), pre-commit install
	uv sync
	@if [ -f dbt_project.yml ]; then $(DBT) deps $(DBT_ARGS); else echo "setup: no dbt_project.yml yet, skipping dbt deps"; fi
	uv run pre-commit install

seeds:  ## rebuild the committed seeds (needs the network for ECB rates; commit the result)
	uv run python scripts/build_free_email_domains.py
	uv run python scripts/build_close_calendar.py
	uv run python scripts/fetch_fx.py

data:  ## generate source Parquet and load the DuckDB raw schemas
	uv run python -m generator --config $(CONFIG) --seed $(SEED)

test-gen:  ## pytest invariants on generator code and output
	uv run pytest tests/generator

test:  ## every pytest suite (generator and project checks)
	uv run pytest tests

lint:  ## ruff on everything
	uv run ruff check .
	uv run ruff format --check .

build:  ## dbt seed, run, and test on DuckDB, then the truth-fence check
	$(DBT) build $(DBT_ARGS)
	uv run python scripts/check_truth_fence.py

fence:  ## only models/audit may read the answer key
	uv run python scripts/check_truth_fence.py

snowflake:  ## load data/ into Snowflake with write_pandas, then dbt build --target snowflake (reads .env)
	uv run --group snowflake python scripts/snowflake_load.py
	set -a; [ -f .env ] && . ./.env; set +a; \
		uv run --group snowflake dbt build --target snowflake $(DBT_ARGS)

dashboard:  ## compile analyses/dashboard and run each query on the local DuckDB build
	$(DBT) compile --select "path:analyses" $(DBT_ARGS)
	uv run python scripts/run_dashboard.py

demo:  ## fresh-clone DuckDB demo: generate, load, build and test, then print the dashboard
	$(MAKE) data SEED=$(SEED)
	$(MAKE) build
	$(MAKE) dashboard

close:  ## post one as-of close to the ledger: make close PERIOD=2026-09 [FORCE=1]
	@test -n "$(PERIOD)" || (echo "close: set PERIOD=YYYY-MM" && exit 2)
	uv run python scripts/close.py --period $(PERIOD) $(if $(FORCE),--force)

close-history:  ## replay the April-September 2026 closes, then rebuild so restatements show
	for period in $(CLOSE_PERIODS); do \
		uv run python scripts/close.py --period $$period $(if $(FORCE),--force) || exit $$?; \
	done
	$(MAKE) build

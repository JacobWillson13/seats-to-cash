# seats-to-cash. Targets are added as PLAN tasks land; see CLAUDE.md for the full list.

SEED ?= 42
CLOSE_PERIODS := 2026-04 2026-05 2026-06 2026-07 2026-08 2026-09
TARGET ?= duckdb
# Snowflake commands read .env and need the optional snowflake dependency group (ADR-021).
SNOWFLAKE_ENV := set -a; [ -f .env ] && . ./.env; set +a;
CLOSE := uv run $(if $(filter snowflake,$(TARGET)),--group snowflake) python scripts/close.py --target $(TARGET)
CONFIG ?= config/simulation.yml
DBT := uv run dbt
DBT_ARGS := --profiles-dir .

.PHONY: setup seeds data test-gen test lint build fence snowflake dashboard dashboard-snowflake demo close close-history

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
	$(SNOWFLAKE_ENV) uv run --group snowflake dbt build --target snowflake $(DBT_ARGS)

dashboard:  ## compile analyses/dashboard and run each query on the local DuckDB build
	$(DBT) compile --select "path:analyses" $(DBT_ARGS)
	uv run python scripts/run_dashboard.py

demo:  ## fresh-clone DuckDB demo: generate, load, build and test, then print the dashboard
	$(MAKE) data SEED=$(SEED)
	$(MAKE) build
	$(MAKE) close-history FORCE=1
	$(MAKE) dashboard

close:  ## post one as-of close: make close PERIOD=2026-09 [FORCE=1] [TARGET=snowflake]
	@test -n "$(PERIOD)" || (echo "close: set PERIOD=YYYY-MM" && exit 2)
	$(CLOSE) --period $(PERIOD) $(if $(FORCE),--force)

close-history:  ## replay the Apr-Sep 2026 closes, then rebuild: [FORCE=1] [TARGET=snowflake]
	for period in $(CLOSE_PERIODS); do \
		$(CLOSE) --period $$period $(if $(FORCE),--force) || exit $$?; \
	done
ifeq ($(TARGET),snowflake)
	$(SNOWFLAKE_ENV) uv run --group snowflake dbt build --target snowflake $(DBT_ARGS)
else
	$(MAKE) build
endif

dashboard-snowflake:  ## compile analyses/dashboard for Snowflake (no connection) and print the files
	$(SNOWFLAKE_ENV) uv run --group snowflake dbt compile --target snowflake \
		--select "path:analyses/dashboard" --no-introspect --no-populate-cache \
		--target-path target/snowflake --quiet $(DBT_ARGS)
	@find $(CURDIR)/target/snowflake/compiled/seats_to_cash/analyses/dashboard -name '*.sql' | sort

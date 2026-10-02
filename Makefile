# seats-to-cash. Targets are added as PLAN tasks land; see CLAUDE.md for the full list.

SEED ?= 42
CONFIG ?= config/simulation.yml
DBT := uv run dbt
DBT_ARGS := --profiles-dir .

.PHONY: setup seeds data test-gen test lint build fence

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

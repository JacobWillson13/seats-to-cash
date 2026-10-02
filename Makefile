# seats-to-cash. Targets are added as PLAN tasks land; see CLAUDE.md for the full list.

SEED ?= 42
CONFIG ?= config/simulation.yml
DBT := uv run dbt --profiles-dir .

.PHONY: setup data test-gen lint

setup:  ## uv sync, dbt deps (once dbt_project.yml exists), pre-commit install
	uv sync
	@if [ -f dbt_project.yml ]; then $(DBT) deps; else echo "setup: no dbt_project.yml yet, skipping dbt deps"; fi
	uv run pre-commit install

data:  ## run the generator and write Parquet (the DuckDB load arrives with PLAN 1.11)
	uv run python -m generator --config $(CONFIG) --seed $(SEED)

test-gen:  ## pytest invariants on generator code and output
	uv run pytest tests/generator

lint:  ## ruff on everything
	uv run ruff check .
	uv run ruff format --check .

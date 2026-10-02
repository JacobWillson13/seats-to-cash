"""Run the compiled dashboard queries (analyses/dashboard/) against DuckDB and print them.

Run `dbt compile` first (`make dashboard` does both). The queries are written for Snowflake but
stay portable, so the same compiled SQL runs on the local DuckDB build.
Usage: uv run python scripts/run_dashboard.py [--rows 12] [--database data/seats_to_cash.duckdb]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
COMPILED = ROOT / "target/compiled/seats_to_cash/analyses/dashboard"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database", default=os.environ.get("DUCKDB_PATH", str(ROOT / "data/seats_to_cash.duckdb"))
    )
    parser.add_argument("--rows", type=int, default=12, help="last N rows of each query")
    args = parser.parse_args(argv)
    queries = sorted(COMPILED.glob("*.sql"))
    if not queries:
        print("dashboard: no compiled queries; run `dbt compile` first", file=sys.stderr)
        return 1
    with duckdb.connect(args.database, read_only=True) as con:
        for path in queries:
            result = con.sql(path.read_text())
            rows = result.fetchall()
            print(f"\n== {path.stem} ({len(rows)} rows; last {min(args.rows, len(rows))}) ==")
            print(" | ".join(result.columns))
            for row in rows[-args.rows :]:
                print(" | ".join("" if v is None else str(v) for v in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())

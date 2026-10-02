"""Load generated Parquet into DuckDB: data/raw/<source>/ -> raw_<source>, answer key -> raw_truth.

Each load replaces the raw tables and leaves every other schema (dbt's) alone.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def load(out_dir: Path, database: Path) -> dict[str, int]:
    database.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    files = sorted((out_dir / "raw").glob("*/*.parquet")) + sorted(
        (out_dir / "answer_key").glob("*/*.parquet")
    )
    with duckdb.connect(str(database)) as con:
        for path in files:
            schema = f"raw_{path.parent.name}"
            table = path.stem
            con.execute(f"create schema if not exists {schema}")
            con.execute(
                f"create or replace table {schema}.{table} as select * from read_parquet(?)",
                [str(path)],
            )
            counts[f"{schema}.{table}"] = con.execute(
                f"select count(*) from {schema}.{table}"
            ).fetchone()[0]
    return counts

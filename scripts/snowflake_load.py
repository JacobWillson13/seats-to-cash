"""Load the generated Parquet into Snowflake with write_pandas (`make snowflake`, ADR-021).

Reads `.env` for SNOWFLAKE_ACCOUNT and SNOWFLAKE_PRIVATE_KEY_PATH (required) and, optionally,
SNOWFLAKE_USER, SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, and
SNOWFLAKE_PRIVATE_KEY_PASSPHRASE. Every file under data/raw/<source>/ becomes
<DATABASE>.RAW_<SOURCE>.<TABLE>, and the answer key becomes RAW_TRUTH. Table and column names
are upper case, so unquoted dbt SQL resolves them. Existing raw tables are replaced.

Usage: uv run --group snowflake python scripts/snowflake_load.py [--data-dir data] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_PRIVATE_KEY_PATH")
DEFAULTS = {
    "SNOWFLAKE_USER": "DBT_TRANSFORMER",
    "SNOWFLAKE_ROLE": "TRANSFORMER",
    "SNOWFLAKE_WAREHOUSE": "TRANSFORMING",
    "SNOWFLAKE_DATABASE": "SEATS_TO_CASH",
}


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines from .env, without overriding variables already set."""
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    return {**values, **{k: v for k, v in os.environ.items() if k.startswith("SNOWFLAKE_")}}


def settings(env: dict[str, str]) -> dict[str, str]:
    missing = [key for key in REQUIRED if not env.get(key)]
    if missing:
        raise SystemExit(f"snowflake: set {', '.join(missing)} in .env (see .env.example)")
    return {**DEFAULTS, **{k: v for k, v in env.items() if v}}


def tables(data_dir: Path) -> list[tuple[str, str, Path]]:
    found = [
        (f"RAW_{p.parent.name.upper()}", p.stem.upper(), p)
        for p in sorted((data_dir / "raw").glob("*/*.parquet"))
    ]
    found += [
        ("RAW_TRUTH", p.stem.upper(), p)
        for p in sorted((data_dir / "answer_key").glob("*/*.parquet"))
    ]
    if not found:
        raise SystemExit(f"snowflake: no Parquet under {data_dir}; run `make data` first")
    return found


def private_key(path: str, passphrase: str | None) -> bytes:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(
        Path(path).expanduser().read_bytes(),
        password=passphrase.encode() if passphrase else None,
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--dry-run", action="store_true", help="list what would load, then exit")
    args = parser.parse_args(argv)

    cfg = settings(read_env(args.env_file))
    plan = tables(args.data_dir)
    database = cfg["SNOWFLAKE_DATABASE"].upper()
    if args.dry_run:
        for schema, table, path in plan:
            print(f"  {database}.{schema}.{table:<34} <- {path.relative_to(args.data_dir)}")
        return 0

    import pyarrow.parquet as pq
    import snowflake.connector
    from snowflake.connector.pandas_tools import write_pandas

    con = snowflake.connector.connect(
        account=cfg["SNOWFLAKE_ACCOUNT"],
        user=cfg["SNOWFLAKE_USER"],
        private_key=private_key(
            cfg["SNOWFLAKE_PRIVATE_KEY_PATH"], cfg.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        ),
        role=cfg["SNOWFLAKE_ROLE"],
        warehouse=cfg["SNOWFLAKE_WAREHOUSE"],
    )
    try:
        cur = con.cursor()
        cur.execute(f"create database if not exists {database}")
        cur.execute(f"use database {database}")
        for schema in sorted({schema for schema, _, _ in plan}):
            cur.execute(f"create schema if not exists {database}.{schema}")
        for schema, table, path in plan:
            frame = pq.read_table(path).to_pandas()
            frame.columns = [c.upper() for c in frame.columns]
            ok, _, rows, _ = write_pandas(
                con,
                frame,
                table_name=table,
                database=database,
                schema=schema,
                auto_create_table=True,
                overwrite=True,
                quote_identifiers=True,
                use_logical_type=True,
            )
            if not ok:
                raise SystemExit(f"snowflake: load failed for {schema}.{table}")
            print(f"  {database}.{schema}.{table:<34} {rows:>10,} rows")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

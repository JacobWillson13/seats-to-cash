"""Close one period: build the close metrics as of its close date and append them to the ledger.

`make close PERIOD=2026-09 [TARGET=snowflake]` (ADR-023, ADR-025):
1. Read the period's close date from seeds/close_calendar.csv. The as-of timestamp is the end
   of that day in the reporting time zone, in UTC; no wall clock is involved.
2. Refuse if the ledger already has the period, unless --force (FORCE=1) replaces it.
3. dbt-build everything upstream of fct_close_metrics with var as_of_ts into the asof_* schemas
   of the chosen target, so the current build is untouched.
4. Append the period's metrics to finance_close.close_ledger on that target. Posted rows
   never change.

The DuckDB target uses data/seats_to_cash.duckdb (or DUCKDB_PATH). The Snowflake target reads
.env exactly as `make snowflake` does and connects with the same key pair.

Usage: uv run python scripts/close.py --period 2026-09 [--force] [--target duckdb|snowflake]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEDGER_COLUMNS = (
    "period varchar, metric varchar, value_usd numeric(18, 2), as_of_ts timestamp, close_date date"
)
LEDGER_DDL = (
    "create schema if not exists finance_close",
    f"create table if not exists finance_close.close_ledger ({LEDGER_COLUMNS})",
)


def close_date(period: str) -> dt.date:
    with (ROOT / "seeds/close_calendar.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            if row["period"] == period:
                return dt.date.fromisoformat(row["close_date"])
    raise SystemExit(f"close: no close date for period {period!r} in seeds/close_calendar.csv")


def as_of_utc(day: dt.date, tz: str) -> str:
    """The end of `day` in the reporting time zone, as a naive UTC timestamp string."""
    local_end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0), ZoneInfo(tz))
    utc = local_end.astimezone(dt.UTC).replace(tzinfo=None) - dt.timedelta(microseconds=1)
    return utc.isoformat(sep=" ")


def reporting_tz() -> str:
    project = yaml.safe_load((ROOT / "dbt_project.yml").read_text())
    return project["vars"]["reporting_tz"]


class Ledger:
    """The append-only ledger on one warehouse, through a DB-API connection."""

    target = ""
    placeholder = "?"

    def __init__(self, connection):
        self.con = connection
        # One cursor for every statement: in DuckDB each cursor is its own connection, so a
        # transaction must begin and commit on the same one.
        self.cur = connection.cursor()

    def _run(self, sql: str, params=()):
        self.cur.execute(sql.replace("?", self.placeholder), params)
        return self.cur

    def posted(self, period: str) -> int:
        for statement in LEDGER_DDL:
            self._run(statement)
        return self._run(
            "select count(*) from finance_close.close_ledger where period = ?", (period,)
        ).fetchone()[0]

    def post(self, period: str, as_of: str, closed: dt.date, *, replace: bool) -> list:
        rows = self._run(
            "select metric, value_usd from asof_marts.fct_close_metrics where period = ? "
            "order by metric",
            (period,),
        ).fetchall()
        if not rows:
            raise SystemExit(f"close: the as-of build has no metrics for {period}")
        self._run("begin")
        try:
            if replace:
                self._run("delete from finance_close.close_ledger where period = ?", (period,))
            for metric, value in rows:
                self._run(
                    "insert into finance_close.close_ledger "
                    "(period, metric, value_usd, as_of_ts, close_date) "
                    "values (?, ?, ?, cast(? as timestamp), cast(? as date))",
                    (period, metric, value, as_of, closed.isoformat()),
                )
            self._run("commit")
        except Exception:
            self._run("rollback")
            raise
        return rows

    def close(self) -> None:
        self.con.close()


class DuckDBLedger(Ledger):
    target = "duckdb"

    def __init__(self, database: str):
        import duckdb

        self.database = database
        super().__init__(duckdb.connect(database))


class SnowflakeLedger(Ledger):
    target = "snowflake"
    placeholder = "%s"

    def __init__(self, cfg: dict[str, str]):
        import snowflake.connector
        from snowflake_load import private_key

        super().__init__(
            snowflake.connector.connect(
                account=cfg["SNOWFLAKE_ACCOUNT"],
                user=cfg["SNOWFLAKE_USER"],
                private_key=private_key(
                    cfg["SNOWFLAKE_PRIVATE_KEY_PATH"], cfg.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
                ),
                role=cfg["SNOWFLAKE_ROLE"],
                warehouse=cfg["SNOWFLAKE_WAREHOUSE"],
                database=cfg["SNOWFLAKE_DATABASE"],
            )
        )


def snowflake_settings(env_file: Path) -> dict[str, str]:
    """`.env` settings, exported so profiles.yml's env_var() sees them in the dbt run."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from snowflake_load import read_env, settings

    cfg = settings(read_env(env_file))
    os.environ.update({k: v for k, v in cfg.items() if k.startswith("SNOWFLAKE_")})
    return cfg


def dbt_args(as_of: str, target: str) -> list[str]:
    return [
        "build",
        "--target", target,
        "--select", "+fct_close_metrics",
        "--indirect-selection", "cautious",
        "--vars", json.dumps({"as_of_ts": as_of}),
        "--profiles-dir", str(ROOT),
        "--project-dir", str(ROOT),
    ]  # fmt: skip


def build_as_of(as_of: str, target: str) -> None:
    from dbt.cli.main import dbtRunner

    if not dbtRunner().invoke(dbt_args(as_of, target)).success:
        raise SystemExit("close: the as-of dbt build failed; nothing was posted")


def open_ledger(args) -> Ledger:
    if args.target == "snowflake":
        return SnowflakeLedger(snowflake_settings(args.env_file))
    os.environ["DUCKDB_PATH"] = args.database
    return DuckDBLedger(args.database)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--period", required=True, help="YYYY-MM")
    parser.add_argument("--force", action="store_true", help="replace an already posted close")
    parser.add_argument("--target", choices=("duckdb", "snowflake"), default="duckdb")
    parser.add_argument(
        "--database",
        default=os.environ.get("DUCKDB_PATH", str(ROOT / "data/seats_to_cash.duckdb")),
        help="DuckDB file (duckdb target only)",
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env", help="snowflake target")
    args = parser.parse_args(argv)

    closed = close_date(args.period)
    as_of = as_of_utc(closed, reporting_tz())
    ledger = open_ledger(args)
    try:
        already = ledger.posted(args.period)
    finally:
        ledger.close()  # release the DuckDB file lock before dbt runs
    if already and not args.force:
        print(
            f"close: {args.period} is already closed on {args.target}; "
            "re-run with FORCE=1 to replace it",
            file=sys.stderr,
        )
        return 2
    print(f"close: {args.period} on {args.target} as of {closed} (data loaded by {as_of} UTC)")
    build_as_of(as_of, args.target)
    ledger = open_ledger(args)
    try:
        rows = ledger.post(args.period, as_of, closed, replace=args.force)
    finally:
        ledger.close()
    for metric, value in rows:
        print(f"  {metric:<24} {value:>16,.2f}")
    print(f"close: posted {len(rows)} metrics for {args.period} to finance_close.close_ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())

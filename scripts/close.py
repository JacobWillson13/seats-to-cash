"""Close one period: build the close metrics as of its close date and append them to the ledger.

`make close PERIOD=2026-09` (ADR-023):
1. Read the period's close date from seeds/close_calendar.csv. The as-of timestamp is the end
   of that day in the reporting time zone, in UTC; no wall clock is involved.
2. Refuse if the ledger already has the period, unless --force (FORCE=1) replaces it.
3. dbt-build everything upstream of fct_close_metrics with var as_of_ts into the asof_* schemas,
   so the current build is untouched.
4. Append the period's metrics to finance_close.close_ledger. Posted rows never change.

Usage: uv run python scripts/close.py --period 2026-09 [--force] [--database PATH]
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

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DDL = (
    "create schema if not exists finance_close",
    "create table if not exists finance_close.close_ledger (period varchar, metric varchar, "
    "value_usd numeric(18, 2), as_of_ts timestamp, close_date date)",
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


def posted(database: str, period: str) -> int:
    with duckdb.connect(database) as con:
        for statement in LEDGER_DDL:
            con.execute(statement)
        return con.execute(
            "select count(*) from finance_close.close_ledger where period = ?", [period]
        ).fetchone()[0]


def build_as_of(as_of: str, database: str) -> None:
    from dbt.cli.main import dbtRunner

    os.environ["DUCKDB_PATH"] = database
    result = dbtRunner().invoke(
        [
            "build",
            "--select",
            "+fct_close_metrics",
            "--indirect-selection",
            "cautious",
            "--vars",
            json.dumps({"as_of_ts": as_of}),
            "--profiles-dir",
            str(ROOT),
            "--project-dir",
            str(ROOT),
        ]  # fmt: skip
    )
    if not result.success:
        raise SystemExit("close: the as-of dbt build failed; nothing was posted")


def post(database: str, period: str, as_of: str, closed: dt.date, *, replace: bool) -> list:
    with duckdb.connect(database) as con:
        rows = con.execute(
            "select metric, value_usd from asof_marts.fct_close_metrics where period = ? "
            "order by metric",
            [period],
        ).fetchall()
        if not rows:
            raise SystemExit(f"close: the as-of build has no metrics for {period}")
        con.execute("begin transaction")
        if replace:
            con.execute("delete from finance_close.close_ledger where period = ?", [period])
        con.executemany(
            "insert into finance_close.close_ledger values (?, ?, ?, cast(? as timestamp), ?)",
            [(period, metric, value, as_of, closed) for metric, value in rows],
        )
        con.execute("commit")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--period", required=True, help="YYYY-MM")
    parser.add_argument("--force", action="store_true", help="replace an already posted close")
    parser.add_argument(
        "--database",
        default=os.environ.get("DUCKDB_PATH", str(ROOT / "data/seats_to_cash.duckdb")),
    )
    args = parser.parse_args(argv)

    closed = close_date(args.period)
    as_of = as_of_utc(closed, reporting_tz())
    if posted(args.database, args.period) and not args.force:
        print(
            f"close: {args.period} is already closed; re-run with FORCE=1 to replace it",
            file=sys.stderr,
        )
        return 2
    print(f"close: {args.period} as of {closed} (data loaded by {as_of} UTC)")
    build_as_of(as_of, args.database)
    rows = post(args.database, args.period, as_of, closed, replace=args.force)
    for metric, value in rows:
        print(f"  {metric:<24} {value:>16,.2f}")
    print(f"close: posted {len(rows)} metrics for {args.period} to finance_close.close_ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build seeds/close_calendar.csv: each period closes on the 5th business day of the next month.

Business days are Monday to Friday, with no holidays (SPEC 8.6). Periods run from the month of
sim_start_date through the month of end_date. Run once; the CSV is committed.
Usage: uv run python scripts/build_close_calendar.py [--config ...] [--out ...]
"""

import argparse
import csv
import datetime as dt
from pathlib import Path

from generator.clock import first_of_next_month, months_between, nth_weekday_of_month
from generator.config import load_config

CLOSE_BUSINESS_DAY = 5


def close_calendar(start: dt.date, end: dt.date) -> list[tuple[str, dt.date]]:
    rows = []
    for period in months_between(start, end):
        period_start = dt.date.fromisoformat(f"{period}-01")
        close = nth_weekday_of_month(first_of_next_month(period_start), CLOSE_BUSINESS_DAY)
        rows.append((period, close))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("config/simulation.yml"))
    parser.add_argument("--out", type=Path, default=Path("seeds/close_calendar.csv"))
    args = parser.parse_args(argv)

    config = load_config(args.config)
    rows = close_calendar(config.sim_start_date, config.end_date)
    with args.out.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["period", "close_date"])
        writer.writerows((period, close.isoformat()) for period, close in rows)
    print(f"wrote {len(rows)} periods ({rows[0][0]} .. {rows[-1][0]}) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

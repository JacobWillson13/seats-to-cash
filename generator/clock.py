"""Simulation calendar helpers. All dates come from config, never the wall clock."""

from __future__ import annotations

import datetime as dt


def first_of_next_month(d: dt.date) -> dt.date:
    return dt.date(d.year + d.month // 12, d.month % 12 + 1, 1)


def months_between(start: dt.date, end: dt.date) -> list[str]:
    """Every period ('YYYY-MM') from start's month through end's month, inclusive."""
    months, d = [], start.replace(day=1)
    while d <= end:
        months.append(f"{d.year:04d}-{d.month:02d}")
        d = first_of_next_month(d)
    return months


def nth_weekday_of_month(first: dt.date, n: int) -> dt.date:
    """The nth Monday-to-Friday day of the month starting at `first` (no holidays)."""
    d, count = first, 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
        d += dt.timedelta(days=1)

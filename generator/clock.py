"""Simulation calendar helpers. All dates come from config, never the wall clock."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np

DAYS_PER_MONTH = 365.25 / 12
SECONDS_PER_DAY = 86_400
US_PER_SECOND = 1_000_000
US_PER_DAY = SECONDS_PER_DAY * US_PER_SECOND

# Time-of-day windows (seconds of the local business day in the reporting time zone) that
# order same-day business events consistently:
# departures, then admin seat actions, then logins, then lifecycle transitions.
PHASE_DEPARTURES = (0, 21_600)
PHASE_ADMIN = (21_600, 32_400)
PHASE_LOGINS = (32_400, 64_800)
PHASE_LIFECYCLE = (64_800, 86_400)
OFFSET_PAD = 800  # days of UTC offsets kept before and after the simulation window


def first_of_next_month(d: dt.date) -> dt.date:
    return dt.date(d.year + d.month // 12, d.month % 12 + 1, 1)


def add_months(d: dt.date, months: int) -> dt.date:
    """Same day of month `months` later, clamped to the month's last day."""
    year, month = divmod(d.month - 1 + months, 12)
    first = dt.date(d.year + year, month + 1, 1)
    last = (first_of_next_month(first) - dt.timedelta(days=1)).day
    return first.replace(day=min(d.day, last))


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


def daily_probability(monthly: float | np.ndarray, multiplier: float | np.ndarray = 1.0):
    """Daily event probability for a monthly hazard, with the multiplier on the hazard rate.

    Hazard ratios between groups equal the multiplier exactly, so planted ratios are
    recoverable from events per exposure-day.
    """
    with np.errstate(divide="ignore"):
        rate = -np.log1p(-np.asarray(monthly, dtype=float)) * multiplier / DAYS_PER_MONTH
    return -np.expm1(-rate)


@dataclass(frozen=True)
class Calendar:
    """Day index 0 is sim_start_date; the last day is end_date.

    A day index is a business date in the reporting time zone (ADR-014): timestamps convert a
    (day, second-of-day) pair from local time to UTC, so every event's local date is its day.
    """

    start: dt.date
    end: dt.date
    tz: str = "America/Los_Angeles"

    def __post_init__(self):
        n = (self.end - self.start).days + 1
        dates = [self.start + dt.timedelta(days=i) for i in range(n)]
        months = months_between(self.start, self.end)
        month_of = np.array(
            [months.index(f"{d.year:04d}-{d.month:02d}") for d in dates], dtype=np.int32
        )
        object.__setattr__(self, "n_days", n)
        object.__setattr__(self, "dates", dates)
        object.__setattr__(self, "months", months)
        object.__setattr__(self, "month_of", month_of)
        object.__setattr__(self, "weekday", np.array([d.weekday() for d in dates], np.int8))
        object.__setattr__(
            self, "month_start", np.searchsorted(month_of, np.arange(len(months)), "left")
        )
        object.__setattr__(
            self, "month_end", np.searchsorted(month_of, np.arange(len(months)), "right") - 1
        )
        # UTC offset (seconds) of local noon for each day from OFFSET_PAD days before the start
        # through OFFSET_PAD days after the end; DST changes happen overnight, so noon is safe.
        zone = ZoneInfo(self.tz)
        offsets = [
            int(
                dt.datetime.combine(self.start + dt.timedelta(days=i), dt.time(12), zone)
                .utcoffset()
                .total_seconds()
            )
            for i in range(-OFFSET_PAD, n + OFFSET_PAD)
        ]
        object.__setattr__(self, "_offsets", np.array(offsets, np.int64))

    def day(self, d: dt.date) -> int:
        return (d - self.start).days

    def utc_offset(self, day) -> np.ndarray:
        """Local UTC offset in seconds for day indices (clamped to the padded table)."""
        idx = np.clip(np.asarray(day, np.int64) + OFFSET_PAD, 0, self._offsets.size - 1)
        return self._offsets[idx]

    def epoch_us(self, day, second=0):
        """Microseconds since 1970-01-01 UTC for a local day index and second of that day."""
        base = (self.start - dt.date(1970, 1, 1)).days
        day = np.asarray(day, np.int64)
        local = (day + base) * US_PER_DAY + np.asarray(second, np.int64) * US_PER_SECOND
        return local - self.utc_offset(day) * US_PER_SECOND

    def epoch_days(self, day):
        return np.asarray(day, np.int64) + (self.start - dt.date(1970, 1, 1)).days

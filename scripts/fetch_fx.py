"""Build seeds/fx_rates.csv: USD per unit of EUR and GBP for every day of the simulation.

Source: ECB euro reference rates (EUR base), converted to USD per unit. Covers sim_start_date
through end_date, one row per calendar day and currency:
- `ecb`: a published ECB rate for that day.
- `ecb_carried_forward`: a weekend or ECB holiday, carrying the last published rate.
The committed seed holds only these two sources. If ECB data is unreachable or doesn't reach
end_date, the script fails rather than inventing rates.

`--offline` writes a seeded random walk labeled `simulated`, for scratch builds without the
network. It refuses to overwrite the committed seed.
Usage: uv run python scripts/fetch_fx.py [--config ...] [--out ...] [--offline]
"""

import argparse
import csv
import datetime as dt
import io
import math
import sys
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

import numpy as np

from generator.config import load_config

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
COMMITTED_SEED = Path(__file__).resolve().parents[1] / "seeds" / "fx_rates.csv"
CURRENCIES = ("EUR", "GBP")
QUANTUM = Decimal("0.000001")
# Offline random walk: illustrative starting rates and daily log volatility.
OFFLINE_START = {"EUR": Decimal("1.070000"), "GBP": Decimal("1.210000")}
OFFLINE_DAILY_VOL = 0.004
OFFLINE_RNG_STREAM = 0xF1  # keeps the walk independent of generator streams

Rates = dict[str, Decimal]
Row = tuple[dt.date, str, Decimal, str]


def fetch_ecb() -> dict[dt.date, Rates]:
    """Published ECB days -> USD per unit, by currency."""
    with urllib.request.urlopen(ECB_URL, timeout=60) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        text = archive.read(archive.namelist()[0]).decode("utf-8")
    published: dict[dt.date, Rates] = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        usd, gbp = row.get("USD", ""), row.get("GBP", "")
        if not usd or not gbp or "N/A" in (usd, gbp):
            continue
        usd_per_eur = Decimal(usd)
        published[dt.date.fromisoformat(row["Date"])] = {
            "EUR": usd_per_eur.quantize(QUANTUM),
            "GBP": (usd_per_eur / Decimal(gbp)).quantize(QUANTUM),
        }
    return published


def _days(start: dt.date, end: dt.date):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def ecb_daily_rates(published: dict[dt.date, Rates], start: dt.date, end: dt.date) -> list[Row]:
    earlier = [d for d in published if d <= start]
    if not earlier:
        raise ValueError(f"ECB data starts after {start}")
    if max(published) < end:
        raise ValueError(f"ECB data ends {max(published)}, before end_date {end}")
    current = published[max(earlier)]
    rows: list[Row] = []
    for day in _days(start, end):
        source = "ecb_carried_forward"
        if day in published:
            current, source = published[day], "ecb"
        rows.extend((day, c, current[c], source) for c in CURRENCIES)
    return rows


def simulated_daily_rates(start: dt.date, end: dt.date, seed: int) -> list[Row]:
    rng = np.random.default_rng([seed, OFFLINE_RNG_STREAM])
    current = dict(OFFLINE_START)
    rows: list[Row] = []
    for day in _days(start, end):
        if day.weekday() < 5 and day != start:  # markets move on weekdays; weekends carry
            for currency in CURRENCIES:
                step = Decimal(repr(math.exp(rng.normal(0.0, OFFLINE_DAILY_VOL))))
                current[currency] = (current[currency] * step).quantize(QUANTUM)
        rows.extend((day, c, current[c], "simulated") for c in CURRENCIES)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("config/simulation.yml"))
    parser.add_argument("--out", type=Path, default=COMMITTED_SEED)
    parser.add_argument("--offline", action="store_true", help="simulated walk, no network")
    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.offline:
        if args.out.resolve() == COMMITTED_SEED:
            print(
                "fetch_fx: --offline rates are simulated and must not be committed; "
                "pass --out to a scratch path",
                file=sys.stderr,
            )
            return 2
        rows = simulated_daily_rates(config.sim_start_date, config.end_date, config.seed)
    else:
        try:
            rows = ecb_daily_rates(fetch_ecb(), config.sim_start_date, config.end_date)
        except (urllib.error.URLError, TimeoutError, zipfile.BadZipFile, ValueError) as exc:
            print(f"fetch_fx: cannot build ECB rates: {exc}", file=sys.stderr)
            return 1

    with args.out.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["rate_date", "currency", "usd_per_unit", "source"])
        writer.writerows((d.isoformat(), c, f"{r:.6f}", s) for d, c, r, s in rows)
    sources = Counter(s for *_, s in rows)
    print(f"wrote {len(rows)} rows to {args.out}: {dict(sorted(sources.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

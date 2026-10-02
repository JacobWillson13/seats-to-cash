"""Build seeds/fx_rates.csv: USD per unit of EUR and GBP for every day the simulation needs.

Source: ECB euro reference rates (EUR base), converted to USD per unit. Covers sim_start_date
through extract_date, one row per calendar day and currency:
- `ecb`: a published ECB rate for that day.
- `ecb_carried_forward`: a weekend or ECB holiday, carrying the last published rate.
- `simulated`: no ECB data (offline, or past the last published date). A seeded random walk,
  so the demo never needs the network.
Run once; the CSV is committed.
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
CURRENCIES = ("EUR", "GBP")
QUANTUM = Decimal("0.000001")
# Fallback random walk: illustrative starting rates and daily log volatility.
FALLBACK_START = {"EUR": Decimal("1.070000"), "GBP": Decimal("1.210000")}
FALLBACK_DAILY_VOL = 0.004
FALLBACK_RNG_STREAM = 0xF1  # keeps the walk independent of generator streams

Rates = dict[str, Decimal]


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


def daily_rates(
    published: dict[dt.date, Rates], start: dt.date, end: dt.date, seed: int
) -> list[tuple[dt.date, str, Decimal, str]]:
    rng = np.random.default_rng([seed, FALLBACK_RNG_STREAM])
    last_published = max(published) if published else None
    earlier = [d for d in published if d <= start]
    current = dict(published[max(earlier)]) if earlier else dict(FALLBACK_START)

    rows = []
    day = start
    while day <= end:
        if day in published:
            current, source = dict(published[day]), "ecb"
        elif earlier and last_published is not None and day <= last_published:
            source = "ecb_carried_forward"
        else:
            source = "simulated"
            if day.weekday() < 5:  # markets move on weekdays; weekends carry
                for currency in CURRENCIES:
                    step = Decimal(repr(math.exp(rng.normal(0.0, FALLBACK_DAILY_VOL))))
                    current[currency] = (current[currency] * step).quantize(QUANTUM)
        rows.extend((day, c, current[c], source) for c in CURRENCIES)
        day += dt.timedelta(days=1)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("config/simulation.yml"))
    parser.add_argument("--out", type=Path, default=Path("seeds/fx_rates.csv"))
    parser.add_argument("--offline", action="store_true", help="skip the ECB download")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    published: dict[dt.date, Rates] = {}
    if not args.offline:
        try:
            published = fetch_ecb()
        except (urllib.error.URLError, TimeoutError, zipfile.BadZipFile, KeyError) as exc:
            print(
                f"fetch_fx: ECB download failed ({exc}); using the simulated walk", file=sys.stderr
            )

    rows = daily_rates(published, config.sim_start_date, config.extract_date, config.seed)
    with args.out.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["rate_date", "currency", "usd_per_unit", "source"])
        writer.writerows((d.isoformat(), c, f"{r:.6f}", s) for d, c, r, s in rows)

    sources = Counter(s for *_, s in rows)
    latest = f"; last ECB date {max(published)}" if published else ""
    print(f"wrote {len(rows)} rows to {args.out}: {dict(sorted(sources.items()))}{latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

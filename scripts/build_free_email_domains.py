"""Build seeds/free_email_domains.csv from the free-email-domains package (SPEC 2.4).

A signup on one of these domains is a personal tailnet. Run once; the CSV is committed.
Usage: uv run python scripts/build_free_email_domains.py [--out seeds/free_email_domains.csv]
"""

import argparse
import csv
from pathlib import Path

from free_email_domains import whitelist


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("seeds/free_email_domains.csv"))
    args = parser.parse_args(argv)

    domains = sorted({d.strip().lower() for d in whitelist if d.strip()})
    if reserved := [d for d in domains if d.endswith(".example")]:
        raise SystemExit(f"free email list contains reserved .example domains: {reserved}")
    with args.out.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["domain"])
        writer.writerows([d] for d in domains)
    print(f"wrote {len(domains)} domains to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fail if any dbt model outside models/audit/ (or any macro or analysis) reads the answer key.

The answer key is the `truth` source (schema raw_truth). Only audit models may read it.
Usage: uv run python scripts/check_truth_fence.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(
    r"source\(\s*['\"]truth['\"]|raw_truth|truth_(mrr|revenue|identity)|defect_manifest"
)
SCANNED = ("models", "macros", "analyses")


def violations(root: Path = ROOT) -> list[str]:
    found = []
    for folder in SCANNED:
        for path in sorted((root / folder).rglob("*.sql")):
            relative = path.relative_to(root)
            if relative.parts[:2] == ("models", "audit"):
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if PATTERN.search(line):
                    found.append(f"{relative}:{number}: {line.strip()}")
    return found


def main() -> int:
    found = violations()
    if found:
        print("truth fence: answer key referenced outside models/audit/:", file=sys.stderr)
        print("\n".join(found), file=sys.stderr)
        return 1
    print("truth fence: ok (only models/audit/ reads the answer key)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command-line entry point: `python -m generator`."""

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m generator",
        description=(
            "Generate the Wirefern synthetic dataset: raw source tables in vendor shapes "
            "under data/raw/ and the answer key under data/answer_key/."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/simulation.yml"),
        help="simulation config (default: %(default)s)",
    )
    parser.add_argument("--seed", type=int, help="override the seed in the config")
    parser.add_argument("--out", type=Path, help="output directory (default: output.data_dir)")
    parser.add_argument(
        "--no-defects",
        action="store_true",
        help="skip defect injection and internal tailnets, for a clean debugging dataset",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print("generator: simulation stages are not implemented yet (PLAN 1.3+)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

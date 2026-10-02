"""Command-line entry point: `python -m generator`."""

import argparse
import sys
from pathlib import Path

from generator.config import ConfigError, cross_check, load_config
from generator.pricebook import PriceBookError
from generator.reference import SeedError, Seeds


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
    parser.add_argument("--seeds", type=Path, default=Path("seeds"), help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=_non_negative_int, help="override the seed in the config")
    parser.add_argument("--out", type=Path, help="output directory (default: output.data_dir)")
    parser.add_argument(
        "--no-defects",
        action="store_true",
        help="skip defect injection and internal tailnets, for a clean debugging dataset",
    )
    parser.add_argument(
        "--check", action="store_true", help="validate the config and seeds, then exit"
    )
    return parser


def _non_negative_int(value: str) -> int:
    seed = int(value)
    if seed < 0:
        raise argparse.ArgumentTypeError("seed must be a non-negative integer")
    return seed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        seeds = Seeds.load(args.seeds)
        cross_check(config, seeds)
    except (ConfigError, PriceBookError, SeedError) as exc:
        print(f"generator: {exc}", file=sys.stderr)
        return 2
    if args.seed is not None:
        config = config.model_copy(update={"seed": args.seed})

    if args.check:
        print(
            f"generator: {args.config} is valid (seed {config.seed}, "
            f"{config.sim_start_date} .. {config.end_date}, {len(seeds.price_book)} prices)"
        )
        return 0
    print("generator: simulation stages are not implemented yet (PLAN 1.3+)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

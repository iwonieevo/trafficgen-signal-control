"""Generate hourly vehicle counts for one junction and write them as CSV."""

import argparse
import sys
from pathlib import Path

from trafficgen import TrafficConfig, build_generators, load_config

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "traffic.toml"


def parse_args() -> argparse.Namespace:
    """Parse the command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="TOML config file")
    parser.add_argument("--junction", required=True, help="junction id from the config")
    parser.add_argument("--start", required=True, help="first hour, e.g. 2017-04-03T00:00")
    parser.add_argument("--end", required=True, help="hour after the last one (exclusive)")
    parser.add_argument("--seed", type=int, default=None, help="seed for reproducible output")
    parser.add_argument("--scale", type=float, default=1.0, help="multiplier of the volume")
    parser.add_argument("--output", type=Path, default=None, help="CSV file (default: stdout)")
    return parser.parse_args()


def main() -> None:
    """Fit the junction model from the config and write the generated counts."""
    args = parse_args()
    config = load_config(args.config)
    selected = [j for j in config.junctions if j.id == args.junction]
    if not selected:
        known = ", ".join(j.id for j in config.junctions)
        sys.exit(f"Unknown junction {args.junction!r}. Available: {known}")

    subset = TrafficConfig(junctions=tuple(selected), country=config.country)
    model = build_generators(subset)[args.junction]
    counts = model.sample(args.start, args.end, seed=args.seed, scale=args.scale)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    counts.rename_axis("datetime").to_csv(args.output if args.output else sys.stdout)


if __name__ == "__main__":
    main()

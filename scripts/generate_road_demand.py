"""Generate hourly flows on every road and turn of a network and write them as CSV files."""

import argparse
import sys
import warnings
from pathlib import Path

from trafficgen import (
    RoadDemand,
    RoadDemandWarning,
    build_road_demand_generator,
    load_network_config,
)

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "network_single.toml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="network TOML config")
    parser.add_argument("--start", required=True, help="first hour, e.g. 2017-04-03T00:00")
    parser.add_argument("--end", required=True, help="hour after the last one (exclusive)")
    parser.add_argument("--seed", type=int, default=None, help="seed for reproducible output")
    parser.add_argument(
        "--scale", type=float, default=None, help="multiplier of the volume (default: config)"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="directory for the CSV files"
    )
    return parser.parse_args()


def write_output_tables(demand: RoadDemand, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths = []
    for table_name, table in demand.output_tables.items():
        path = output_dir / f"{table_name}.csv"
        table.to_csv(path, index=False, lineterminator="\n")
        written_paths.append(path)
    return written_paths


def main() -> None:
    args = parse_args()
    try:
        config = load_network_config(args.config)
    except ValueError as error:
        sys.exit(str(error))

    generator = build_road_demand_generator(config)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RoadDemandWarning)
        demand = generator.sample(args.start, args.end, seed=args.seed, scale=args.scale)

    for path in write_output_tables(demand, args.output_dir):
        print(f"wrote {path}")
    for message in demand.warnings:
        print(f"warning: {message}", file=sys.stderr)


if __name__ == "__main__":
    main()

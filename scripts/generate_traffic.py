"""Generate traffic for a scenario: junction counts, network flows and SUMO input in one step.

Everything is written to one run directory, by default ``runs/<run>`` next to the config.
The run can then be started with: uv run python scripts/run_sumo.py <run>/sumo/run.sumocfg
Instead of generating counts for a time range, counts can be read from a CSV file.
"""

import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

from trafficgen import (
    FlowWarning,
    GeneratedTraffic,
    generate_traffic,
    load_junction_counts,
    traffic_from_counts,
)
from trafficgen.pipeline import random_seed


def parse_args() -> argparse.Namespace:
    """Parse the command line arguments.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="TOML config file")
    parser.add_argument("--start", help="first hour, e.g. 2017-04-03T00:00")
    parser.add_argument("--end", help="hour after the last one (exclusive)")
    parser.add_argument(
        "--counts", type=Path, help="CSV file of counts per junction, instead of --start/--end"
    )
    parser.add_argument("--seed", type=int, default=None, help="seed (default: random)")
    parser.add_argument(
        "--scale", type=float, default=None, help="multiplier of the volume (default: config)"
    )
    parser.add_argument("--run", help="name of the run directory (default: from the options)")
    parser.add_argument(
        "--output-dir", type=Path, help="run directory (default: runs/<run> next to the config)"
    )
    args = parser.parse_args()
    if args.counts is None and (args.start is None or args.end is None):
        parser.error("give --start and --end, or --counts")
    if args.counts is not None and (args.start or args.end or args.scale is not None):
        parser.error("--counts cannot be combined with --start, --end or --scale")
    return args


def run_name(args: argparse.Namespace, seed: int) -> str:
    """Name a run after its time range or counts file, and its seed.

    Args:
        args: The parsed arguments.
        seed: Seed of the run.

    Returns:
        A name that is valid as a directory name on every platform.
    """
    if args.counts is not None:
        return f"{args.counts.stem}-seed{seed}"
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    return f"{start:%Y-%m-%dT%H}-{end:%Y-%m-%dT%H}-seed{seed}"


def main() -> None:
    """Generate the traffic and print where it was written and how to run it.

    Raises:
        SystemExit: If the config or the counts are invalid, or SUMO is missing or fails.
    """
    args = parse_args()
    seed = random_seed() if args.seed is None else args.seed
    output_dir = args.output_dir or args.config.parent / "runs" / (args.run or run_name(args, seed))
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", FlowWarning)
            if args.counts is not None:
                run = traffic_from_counts(
                    args.config, load_junction_counts(args.counts), output_dir, seed=seed
                )
            else:
                run = generate_traffic(
                    args.config, args.start, args.end, output_dir, seed=seed, scale=args.scale
                )
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        sys.exit(str(error))

    for warning in caught:
        print(f"warning: {warning.message}", file=sys.stderr)
    print_summary(run)


def print_summary(run: GeneratedTraffic) -> None:
    """Print what was generated and the command that runs it.

    Args:
        run: The generated run.
    """
    hours = len(run.counts)
    print(f"wrote {run.output_dir}")
    print(f"{hours} hours, {run.sumo.vehicles} vehicles, seed {run.seed}")
    print(f"{len(run.flows.adjusted_hours)} hours use shares other than the preferred ones")
    print(f"run it with: uv run python scripts/run_sumo.py {run.sumo.config_file.as_posix()}")


if __name__ == "__main__":
    main()

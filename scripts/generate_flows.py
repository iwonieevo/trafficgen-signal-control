"""Spread hourly junction counts over the roads and turns of a network and write the flows.

The counts are read from a CSV file with a ``datetime`` column and one column per junction,
for example the output of scripts/generate_counts.py. The result is deterministic: the
counts are used exactly as given. Five tables are written as CSV files, and warnings go to
stderr.
"""

import argparse
import sys
import warnings
from pathlib import Path

from trafficgen import FlowSolver, FlowWarning, load_junction_counts, load_network_config


def parse_args() -> argparse.Namespace:
    """Parse the command line arguments.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="TOML config file")
    parser.add_argument(
        "--counts", type=Path, required=True, help="CSV file with the counts of every junction"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="directory for the CSV files"
    )
    return parser.parse_args()


def main() -> None:
    """Read the network and the counts, compute the flows and write them.

    Raises:
        SystemExit: If the config or the counts are invalid.
    """
    args = parse_args()
    try:
        config = load_network_config(args.config)
        counts = load_junction_counts(args.counts)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FlowWarning)
            flows = FlowSolver(config).solve(counts)
    except ValueError as error:
        sys.exit(str(error))

    for path in flows.write_tables(args.output_dir):
        print(f"wrote {path}")
    if len(flows.adjusted_hours):
        print(
            f"{len(flows.adjusted_hours)} hours use shares other than the preferred ones "
            "to meet the junction totals"
        )
    for message in flows.warnings:
        print(f"warning: {message}", file=sys.stderr)


if __name__ == "__main__":
    main()

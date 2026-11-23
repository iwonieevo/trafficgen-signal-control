"""Generate hourly vehicle counts for the junctions of a config and write them as CSV.

The output has a ``datetime`` column and one column per junction, the input format of
scripts/generate_flows.py.
"""

import argparse
import sys
from pathlib import Path

from trafficgen import fit_count_models, load_counts_config, sample_junctions

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "grid_2x2.toml"


def parse_args() -> argparse.Namespace:
    """Parse the command line arguments.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="TOML config file")
    parser.add_argument(
        "--junction",
        action="append",
        default=None,
        help="junction id from the config; repeat for several (default: all)",
    )
    parser.add_argument("--start", required=True, help="first hour, e.g. 2017-04-03T00:00")
    parser.add_argument("--end", required=True, help="hour after the last one (exclusive)")
    parser.add_argument("--seed", type=int, default=None, help="seed for reproducible output")
    parser.add_argument(
        "--scale", type=float, default=None, help="multiplier of the volume (default: config)"
    )
    parser.add_argument("--output", type=Path, default=None, help="CSV file (default: stdout)")
    return parser.parse_args()


def main() -> None:
    """Fit the junction models from the config and write the generated counts.

    All junctions of the config are always sampled together, so the counts of a junction
    do not depend on which junctions ``--junction`` selects.

    Raises:
        SystemExit: If the config is invalid or a junction is unknown.
    """
    args = parse_args()
    try:
        config = load_counts_config(args.config)
    except ValueError as error:
        sys.exit(str(error))
    selected = args.junction or config.junction_ids
    unknown = [junction for junction in selected if junction not in config.junction_ids]
    if unknown:
        known = ", ".join(config.junction_ids)
        sys.exit(f"Unknown junction {unknown[0]!r}. Available: {known}")

    scale = config.settings.scale if args.scale is None else args.scale
    models = fit_count_models(config)
    counts = sample_junctions(models, args.start, args.end, seed=args.seed, scale=scale)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    # A fixed line ending: on Windows, text mode stdout would otherwise turn \r\n into \r\r\n.
    target = args.output if args.output else sys.stdout
    counts[selected].to_csv(target, lineterminator="\n")


if __name__ == "__main__":
    main()

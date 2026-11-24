"""The whole traffic generation in one call: junction counts, network flows and SUMO input.

Everything of a run is written to one directory, by convention
``scenarios/<name>/runs/<run>/``:

- ``counts.csv``: hourly counts per junction.
- ``flows/``: the tables of the network flows.
- ``sumo/``: the SUMO input, with ``run.sumocfg`` ready to start.
- ``run.json``: the config, the seed and the other settings of the run.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from trafficgen.counts.config import fit_count_models, load_counts_config
from trafficgen.counts.sampling import sample_junctions
from trafficgen.flows.config import load_network_config
from trafficgen.flows.network import NetworkConfig
from trafficgen.flows.result import NetworkFlows
from trafficgen.flows.solver import FlowSolver
from trafficgen.simulation.config import SumoConfig, load_sumo_config
from trafficgen.simulation.feed import (
    SUMO_MAX_SEED,
    SumoInput,
    check_through_shares,
    write_sumo_input,
)
from trafficgen.timeutils import TimeLike


@dataclass(frozen=True)
class GeneratedTraffic:
    """Everything one run of the traffic generation produced.

    Attributes:
        counts: Hourly counts per junction, the index is the hour.
        flows: The network flows for the counts.
        sumo: The SUMO input. ``sumo.net_file`` and ``sumo.route_file`` are what a
            simulation or an RL environment loads, ``sumo.config_file`` runs both in SUMO.
        seed: Seed of the run. The same config, counts or time range, and seed give the
            same files.
        output_dir: Directory of the run.
    """

    counts: pd.DataFrame
    flows: NetworkFlows
    sumo: SumoInput
    seed: int
    output_dir: Path


def generate_traffic(
    config_path: str | Path,
    start: TimeLike,
    end: TimeLike,
    output_dir: str | Path,
    seed: int | None = None,
    scale: float | None = None,
) -> GeneratedTraffic:
    """Generate counts, flows and SUMO input for a time range.

    Args:
        config_path: TOML config with the sections of all three steps.
        start: First hour.
        end: Hour after the last one.
        output_dir: Directory of the run. It is created if needed.
        seed: Seed of the counts and of the routes. A random one is drawn if None, and
            returned in the result.
        scale: Multiplier of the volume. The ``scale`` of ``[counts]`` if None.

    Returns:
        The counts, the flows, the SUMO input and the seed.

    Raises:
        ValueError: If the config is invalid.
        RuntimeError: If ``jtrrouter`` fails.
        FileNotFoundError: If SUMO is not installed.
    """
    seed = random_seed() if seed is None else seed
    counts_config = load_counts_config(config_path)
    network, sumo_config = _load_network_and_sumo(config_path)
    scale = counts_config.settings.scale if scale is None else scale
    counts = sample_junctions(fit_count_models(counts_config), start, end, seed=seed, scale=scale)
    return _generate(
        network,
        sumo_config,
        counts,
        Path(output_dir),
        seed,
        {"config": config_path, "scale": scale},
    )


def traffic_from_counts(
    config_path: str | Path,
    counts: pd.DataFrame,
    output_dir: str | Path,
    seed: int | None = None,
) -> GeneratedTraffic:
    """Generate flows and SUMO input for given counts, from any source.

    Args:
        config_path: TOML config. The junction counts part is not read.
        counts: Hourly counts with one column per junction and the hours as index.
        output_dir: Directory of the run. It is created if needed.
        seed: Seed of the routes. A random one is drawn if None.

    Returns:
        The counts, the flows, the SUMO input and the seed.

    Raises:
        ValueError: If the config or the counts are invalid.
        RuntimeError: If ``jtrrouter`` fails.
        FileNotFoundError: If SUMO is not installed.
    """
    seed = random_seed() if seed is None else seed
    network, sumo_config = _load_network_and_sumo(config_path)
    return _generate(network, sumo_config, counts, Path(output_dir), seed, {"config": config_path})


def random_seed() -> int:
    """Draw a seed that SUMO accepts, for a run without a given seed."""
    return int(np.random.default_rng().integers(SUMO_MAX_SEED))


def _load_network_and_sumo(config_path: str | Path) -> tuple[NetworkConfig, SumoConfig]:
    """Read and check the network and SUMO parts before anything is generated.

    Raises:
        ValueError: If either part is invalid or a road has a through share below 1.
    """
    network = load_network_config(config_path)
    sumo_config = load_sumo_config(config_path)
    try:
        check_through_shares({road.id: road.through_share for road in network.roads})
    except ValueError as error:
        raise ValueError(f"{config_path}: {error}") from None
    return network, sumo_config


def _generate(
    network: NetworkConfig,
    sumo_config: SumoConfig,
    counts: pd.DataFrame,
    output_dir: Path,
    seed: int,
    settings: dict[str, object],
) -> GeneratedTraffic:
    """Compute the flows for the counts and write all files of the run."""
    flows = FlowSolver(network).solve(counts)
    output_dir.mkdir(parents=True, exist_ok=True)
    counts.to_csv(output_dir / "counts.csv", lineterminator="\n")
    flows.write_tables(output_dir / "flows")
    sumo = write_sumo_input(
        flows, sumo_config.net_file, output_dir / "sumo", seed, sumo_config.settings.departures
    )
    run = {
        "config": str(Path(str(settings["config"])).resolve()),
        "start": str(counts.index[0]),
        "end": str(counts.index[-1] + pd.Timedelta(hours=1)),
        "seed": seed,
        "scale": settings.get("scale"),
        "departures": sumo_config.settings.departures,
        "vehicles": sumo.vehicles,
    }
    (output_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    return GeneratedTraffic(counts=counts, flows=flows, sumo=sumo, seed=seed, output_dir=output_dir)

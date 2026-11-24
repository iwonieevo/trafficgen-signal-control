"""Turn the network flows into SUMO input: entry flows, turn shares and routes from jtrrouter."""

import subprocess
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from trafficgen.flows.result import NetworkFlows
from trafficgen.simulation.config import Departures
from trafficgen.simulation.files import (
    simulation_seconds,
    write_entry_flows,
    write_sumo_config,
    write_turn_ratios,
)
from trafficgen.simulation.tools import find_sumo_program
from trafficgen.timeutils import SECONDS_PER_HOUR

SUMO_MAX_SEED = 2**31 - 1


@dataclass(frozen=True)
class SumoInput:
    """The SUMO input of one run. Simulation second 0 is the start of the first hour.

    Attributes:
        net_file: SUMO network file, the one of the scenario.
        route_file: Vehicles with their departure times and routes, written by ``jtrrouter``.
            Load it with the network, for example in SUMO or an RL environment.
        config_file: SUMO config with the network and the route file, ready to run.
        flow_file: Entry flows per road and hour, the input of ``jtrrouter``.
        turn_file: Turn shares per hour, the input of ``jtrrouter``.
        end_s: End of the last hour, in simulation seconds. No vehicle departs later.
        vehicles: Number of vehicles in the route file.
    """

    net_file: Path
    route_file: Path
    config_file: Path
    flow_file: Path
    turn_file: Path
    end_s: int
    vehicles: int


def check_through_shares(through_share_by_road: Mapping[str, float]) -> None:
    """Check that every vehicle reaches the end of its road, which the SUMO input assumes.

    Args:
        through_share_by_road: The ``through_share`` of every road.

    Raises:
        ValueError: If a road has a through share below 1.
    """
    below_one = sorted(road for road, share in through_share_by_road.items() if share < 1)
    if below_one:
        raise ValueError(
            f"roads {below_one} have through_share < 1, which the SUMO input does not "
            "support: every vehicle there must reach the end of the road"
        )


def write_sumo_input(
    flows: NetworkFlows,
    net_file: str | Path,
    output_dir: str | Path,
    seed: int,
    departures: Departures = "poisson",
) -> SumoInput:
    """Write the SUMO input for network flows and build the routes with ``jtrrouter``.

    Vehicles enter on the entry roads at the rate of their entry flow and choose every turn
    with the used share of its hour. ``jtrrouter`` draws the departure times (for random
    departures) and the turns of every vehicle, so the route file is fixed for a seed.

    Args:
        flows: Network flows whose road ids are the edge ids of ``net_file``.
        net_file: SUMO network file.
        output_dir: Directory for the files. It is created if needed.
        seed: Seed of ``jtrrouter``.
        departures: ``poisson`` or ``uniform``, see ``SumoSettings``.

    Returns:
        The written files.

    Raises:
        ValueError: If a road has a through share below 1.
        RuntimeError: If ``jtrrouter`` fails, for example because a road is not in the
            network.
        FileNotFoundError: If SUMO is not installed.
    """
    roads = flows.roads
    check_through_shares(dict(zip(roads["road"], roads["through_share"], strict=True)))
    net_file, output_dir = Path(net_file), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    start = flows.junction_balance["datetime"].min()
    end_s = int(simulation_seconds(flows.junction_balance["datetime"], start).max())
    end_s += SECONDS_PER_HOUR

    flow_file = output_dir / "entry_flows.xml"
    turn_file = output_dir / "turn_ratios.xml"
    route_file = output_dir / "routes.rou.xml"
    config_file = output_dir / "run.sumocfg"
    write_entry_flows(flows.entry_flows, start, flow_file, departures)
    write_turn_ratios(flows.turn_flows, start, turn_file)
    exit_roads = roads.loc[roads["kind"] == "exit", "road"]
    _run_jtrrouter(net_file, flow_file, turn_file, list(exit_roads), route_file, seed)
    write_sumo_config(config_file, net_file, route_file)

    return SumoInput(
        net_file=net_file.resolve(),
        route_file=route_file,
        config_file=config_file,
        flow_file=flow_file,
        turn_file=turn_file,
        end_s=end_s,
        vehicles=sum(1 for _ in ElementTree.parse(route_file).getroot().iter("vehicle")),
    )


def _run_jtrrouter(
    net_file: Path,
    flow_file: Path,
    turn_file: Path,
    exit_roads: list[str],
    route_file: Path,
    seed: int,
) -> None:
    """Build one route per vehicle with ``jtrrouter``.

    Routes end on an exit road. Loops are allowed, because the turn shares allow a vehicle
    to come back to a road it has used before.

    Raises:
        RuntimeError: If ``jtrrouter`` fails. The message holds its output.
    """
    command = [
        find_sumo_program("jtrrouter"),
        "--net-file", str(net_file),
        "--route-files", str(flow_file),
        "--turn-ratio-files", str(turn_file),
        "--sink-edges", ",".join(exit_roads),
        "--allow-loops",
        "--seed", str(seed % SUMO_MAX_SEED),
        "--output-file", str(route_file),
        "--no-step-log",
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"jtrrouter failed:\n{result.stdout}{result.stderr}")

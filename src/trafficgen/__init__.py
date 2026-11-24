"""Generate road traffic from historical junction counts and feed it into SUMO.

The generator is built from parts that can be used on their own or together:

- ``trafficgen.counts``, junction counts: models fitted on historical data generate hourly
  vehicle counts per junction.
- ``trafficgen.flows``, network flows: hourly junction counts are spread over the roads and
  turns of a network, so that the traffic through every junction matches its count.
- ``trafficgen.simulation``, SUMO input: the network flows become vehicles with routes that
  SUMO can run.
- ``trafficgen.pipeline``: all three in one call, ``generate_traffic``.

Shared modules: ``trafficgen.config`` reads the config file, ``trafficgen.data`` the CSV
files, and ``trafficgen.timeutils`` holds time constants. The parts are described in
docs/traffic-generation.md.
"""

from trafficgen.counts.config import (
    CountsConfig,
    CountSettings,
    JunctionData,
    fit_count_models,
    load_counts_config,
)
from trafficgen.counts.models import HourlyCountModel, MeanProfileModel, StatisticalCountModel
from trafficgen.counts.sampling import sample_junctions
from trafficgen.data import load_counts, load_junction_counts
from trafficgen.flows.config import load_network_config
from trafficgen.flows.network import FlowSettings, NetworkConfig, RoadConfig, TurnConfig
from trafficgen.flows.result import FlowWarning, NetworkFlows
from trafficgen.flows.solver import FlowSolver
from trafficgen.pipeline import GeneratedTraffic, generate_traffic, traffic_from_counts
from trafficgen.simulation.config import SumoConfig, SumoSettings, load_sumo_config
from trafficgen.simulation.feed import SumoInput, write_sumo_input
from trafficgen.simulation.tools import find_sumo_program

__all__ = [
    "CountSettings",
    "CountsConfig",
    "FlowSettings",
    "FlowSolver",
    "FlowWarning",
    "GeneratedTraffic",
    "HourlyCountModel",
    "JunctionData",
    "MeanProfileModel",
    "NetworkConfig",
    "NetworkFlows",
    "RoadConfig",
    "StatisticalCountModel",
    "SumoConfig",
    "SumoInput",
    "SumoSettings",
    "TurnConfig",
    "find_sumo_program",
    "fit_count_models",
    "generate_traffic",
    "load_counts",
    "load_counts_config",
    "load_junction_counts",
    "load_network_config",
    "load_sumo_config",
    "sample_junctions",
    "traffic_from_counts",
    "write_sumo_input",
]

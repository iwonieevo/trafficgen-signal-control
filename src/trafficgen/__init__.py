"""Generate road traffic from historical junction counts.

The generator has two parts that can be used on their own or together:

- ``trafficgen.counts``, junction counts: models fitted on historical data generate hourly
  vehicle counts per junction.
- ``trafficgen.flows``, network flows: hourly junction counts are spread over the roads and
  turns of a network, so that the traffic through every junction matches its count.

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
from trafficgen.flows.config import (
    FlowSettings,
    NetworkConfig,
    RoadConfig,
    TurnConfig,
    load_network_config,
)
from trafficgen.flows.result import FlowWarning, NetworkFlows
from trafficgen.flows.solver import FlowSolver

__all__ = [
    "CountSettings",
    "CountsConfig",
    "FlowSettings",
    "FlowSolver",
    "FlowWarning",
    "HourlyCountModel",
    "JunctionData",
    "MeanProfileModel",
    "NetworkConfig",
    "NetworkFlows",
    "RoadConfig",
    "StatisticalCountModel",
    "TurnConfig",
    "fit_count_models",
    "load_counts",
    "load_counts_config",
    "load_junction_counts",
    "load_network_config",
    "sample_junctions",
]

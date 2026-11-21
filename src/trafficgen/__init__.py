"""Generate traffic from historical counts.

Layer 1 generates hourly vehicle counts per junction. Layer 2 turns them into flows on every
road and turn of a configured network.
"""

from trafficgen.balancing.network_balancing import NetworkBalancer
from trafficgen.balancing.result import RoadDemand, RoadDemandWarning
from trafficgen.config.junctions import JunctionConfig, TrafficConfig, build_generators, load_config
from trafficgen.config.network import (
    BalanceSettings,
    NetworkConfig,
    RoadConfig,
    TurnConfig,
    build_road_demand_generator,
    load_network_config,
)
from trafficgen.data import load_counts
from trafficgen.models.hourly_counts import (
    HourlyCountModel,
    MeanProfileModel,
    StatisticalCountModel,
)
from trafficgen.models.road_demand import RoadDemandModel

__all__ = [
    "BalanceSettings",
    "HourlyCountModel",
    "JunctionConfig",
    "MeanProfileModel",
    "NetworkConfig",
    "NetworkBalancer",
    "RoadConfig",
    "RoadDemand",
    "RoadDemandModel",
    "RoadDemandWarning",
    "StatisticalCountModel",
    "TrafficConfig",
    "TurnConfig",
    "build_generators",
    "build_road_demand_generator",
    "load_config",
    "load_counts",
    "load_network_config",
]

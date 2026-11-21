"""Layer 2 of the traffic generator: junctions, roads between them and turns.

The model and the config format are described in docs/layer2.md.
"""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Literal

import numpy as np

from trafficgen.config.junctions import JunctionConfig, parse_junctions
from trafficgen.config.network_validations import (
    validate_balance_settings,
    validate_network_config,
    warn_about_long_travel_times,
)
from trafficgen.config.toml_tables import parse_toml_table
from trafficgen.data import load_counts
from trafficgen.models.road_demand import RoadDemandModel

RoadKind = Literal["entry", "internal", "exit"]
DifferenceWeighting = Literal["absolute", "relative"]

KMH_PER_M_PER_S = 3.6
ROAD_TOML_KEYS = {"from": "from_junction", "to": "to_junction"}


@dataclass(frozen=True)
class RoadConfig:
    """One road of the network, in one direction. Its id should be the SUMO edge id.

    A road without ``from_junction`` enters the network and needs a ``weight``: its share of
    the entry flow of its junction. A road without ``to_junction`` leaves the network.
    ``through_share`` is the share of vehicles that reach the end of an internal road.
    """

    id: str
    from_junction: str | None = None
    to_junction: str | None = None
    weight: float | None = None
    length_m: float | None = None
    lanes: int | None = None
    speed_limit_kmh: float | None = None
    through_share: float = 1.0

    @property
    def kind(self) -> RoadKind:
        if self.from_junction is None:
            return "entry"
        if self.to_junction is None:
            return "exit"
        return "internal"

    @property
    def free_flow_time_s(self) -> float | None:
        if self.length_m is None or self.speed_limit_kmh is None:
            return None
        return self.length_m / (self.speed_limit_kmh / KMH_PER_M_PER_S)


@dataclass(frozen=True)
class TurnConfig:
    """One movement through a junction, taken by ``ratio`` of the vehicles on ``from_road``."""

    from_road: str
    to_road: str
    ratio: float


@dataclass(frozen=True)
class BalanceSettings:
    """How the junction counts are balanced and when warnings are raised.

    ``weighting="absolute"`` fits differences in vehicles, so large junctions dominate;
    ``"relative"`` fits differences relative to the requested count.
    """

    weighting: DifferenceWeighting = "absolute"
    tolerance_vph: float = 0.5
    max_travel_time_fraction: float = 0.1
    lane_capacity_vph: float = 1800.0

    def __post_init__(self) -> None:
        validate_balance_settings(self)


@dataclass(frozen=True)
class NetworkConfig:
    """Junctions with their data, the roads between them and the turns. Checked on creation."""

    junctions: tuple[JunctionConfig, ...]
    roads: tuple[RoadConfig, ...]
    turns: tuple[TurnConfig, ...]
    scale: float = 1.0
    balance: BalanceSettings = field(default_factory=BalanceSettings)

    def __post_init__(self) -> None:
        validate_network_config(self)
        warn_about_long_travel_times(self)

    @property
    def junction_ids(self) -> list[str]:
        return [junction.id for junction in self.junctions]

    @property
    def entry_junction_ids(self) -> list[str]:
        entered_junctions = {road.to_junction for road in self.roads if road.kind == "entry"}
        return [junction for junction in self.junction_ids if junction in entered_junctions]

    @cached_property
    def roads_by_id(self) -> dict[str, RoadConfig]:
        return {road.id: road for road in self.roads}

    def road_transfer_matrix(self) -> np.ndarray:
        """``A[r, q]``: share of vehicles at the end of road ``q`` that reach the end of ``r``."""
        road_index = {road.id: index for index, road in enumerate(self.roads)}
        matrix = np.zeros((len(self.roads), len(self.roads)))
        for turn in self.turns:
            to_road = self.roads_by_id[turn.to_road]
            matrix[road_index[turn.to_road], road_index[turn.from_road]] += (
                turn.ratio * to_road.through_share
            )
        return matrix

    def entry_weight_matrix(self) -> np.ndarray:
        """``B[r, j]``: share of vehicles entering at junction ``j`` that use road ``r``."""
        return self._road_junction_matrix(
            self.entry_junction_ids,
            lambda road, junction: (
                (road.weight or 0.0)
                if road.kind == "entry" and road.to_junction == junction
                else 0.0
            ),
        )

    def road_end_matrix(self) -> np.ndarray:
        """``C[j, r]``: 1 if road ``r`` ends at junction ``j``."""
        return self._road_junction_matrix(
            self.junction_ids, lambda road, junction: float(road.to_junction == junction)
        ).T

    def _road_junction_matrix(
        self, junction_ids: list[str], value: Callable[[RoadConfig, str], float]
    ) -> np.ndarray:
        return np.array(
            [[value(road, junction) for junction in junction_ids] for road in self.roads],
            dtype=float,
        ).reshape(len(self.roads), len(junction_ids))


def load_network_config(path: str | Path) -> NetworkConfig:
    path = Path(path)
    with path.open("rb") as file:
        config_tables = tomllib.load(file)
    junctions = parse_junctions(config_tables, path)
    try:
        return NetworkConfig(
            junctions=junctions,
            roads=tuple(_parse_road(table) for table in config_tables.get("roads", [])),
            turns=tuple(_parse_turn(table) for table in config_tables.get("turns", [])),
            scale=float(config_tables.get("scale", 1.0)),
            balance=parse_toml_table(config_tables.get("balance", {}), BalanceSettings, "balance"),
        )
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None


def build_road_demand_generator(config: NetworkConfig) -> RoadDemandModel:
    counts_by_junction = {junction.id: load_counts(junction.data) for junction in config.junctions}
    return RoadDemandModel(config).fit(counts_by_junction)


def _parse_road(road_table: dict) -> RoadConfig:
    table_name = f"road {road_table.get('id', '?')!r}"
    return parse_toml_table(road_table, RoadConfig, table_name, ROAD_TOML_KEYS)


def _parse_turn(turn_table: dict) -> TurnConfig:
    table_name = f"turn {turn_table.get('from_road', '?')!r} -> {turn_table.get('to_road', '?')!r}"
    return parse_toml_table(turn_table, TurnConfig, table_name)

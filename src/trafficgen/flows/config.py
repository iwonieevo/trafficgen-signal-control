"""The network flows part of the config: roads, turns and the solver settings.

Only the junction ids of ``[[junctions]]`` are read here, together with ``[flows]``,
``[[roads]]`` and ``[[turns]]``. The data of the junctions is left to
``trafficgen.counts.config``. The format is described in docs/network-flows.md.
"""

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Literal

import numpy as np

from trafficgen.config import junction_ids, parse_table, read_config
from trafficgen.flows.validation import validate_flow_settings, validate_network_config

RoadKind = Literal["entry", "internal", "exit"]

KMH_PER_M_PER_S = 3.6
ROAD_TOML_KEYS = {"from": "from_junction", "to": "to_junction"}


@dataclass(frozen=True)
class RoadConfig:
    """One road of the network, in one direction. Its id should be the SUMO edge id.

    Attributes:
        id: Unique name of the road.
        from_junction: Junction where the road starts. Without it, the road enters the
            network.
        to_junction: Junction where the road ends. Without it, the road leaves the network.
        preference: Only for entry roads: relative weight of the road among the entry roads
            of its junction. The share actually used is reported in the output.
        length_m: Length in metres. Only used for travel times.
        lanes: Number of lanes. Only used for the capacity warnings.
        speed_limit_kmh: Speed limit in km/h. Only used for travel times.
        through_share: Only for roads between two junctions: share of the vehicles that
            reach the end of the road, the rest leave it on the way, for example to park.
    """

    id: str
    from_junction: str | None = None
    to_junction: str | None = None
    preference: float | None = None
    length_m: float | None = None
    lanes: int | None = None
    speed_limit_kmh: float | None = None
    through_share: float = 1.0

    @property
    def kind(self) -> RoadKind:
        """Whether the road enters the network, leaves it, or joins two junctions."""
        if self.from_junction is None:
            return "entry"
        if self.to_junction is None:
            return "exit"
        return "internal"

    @property
    def free_flow_time_s(self) -> float | None:
        """Travel time at the speed limit in seconds, if length and speed limit are set."""
        if self.length_m is None or self.speed_limit_kmh is None:
            return None
        return self.length_m / (self.speed_limit_kmh / KMH_PER_M_PER_S)


@dataclass(frozen=True)
class TurnConfig:
    """One movement through a junction, from the end of one road onto the next one.

    Attributes:
        from_road: Road that ends at the junction.
        to_road: Road that starts at the same junction.
        preference: Relative weight of this movement among the turns from ``from_road``.
            The share actually used is reported in the output.
    """

    from_road: str
    to_road: str
    preference: float


@dataclass(frozen=True)
class FlowSettings:
    """Settings of the ``[flows]`` section.

    Attributes:
        tolerance_vph: Largest difference between requested and achieved junction totals,
            in vehicles per hour, that still counts as met.
        max_travel_time_fraction: Warn when the travel time of a road at the speed limit is
            longer than this share of an hour, since flows are computed per hour.
        lane_capacity_vph: Warn when the flow per lane of a road is above this. Flows are not
            limited: queues are measured by the simulation.
    """

    tolerance_vph: float = 0.5
    max_travel_time_fraction: float = 0.1
    lane_capacity_vph: float = 1800.0

    def __post_init__(self) -> None:
        """Check the settings.

        Raises:
            ValueError: If a setting is not positive.
        """
        validate_flow_settings(self)


@dataclass(frozen=True)
class NetworkConfig:
    """The network of junctions, roads and turns. It is checked when it is created.

    Attributes:
        junction_ids: Ids of the junctions, in the order of the config file.
        roads: Every road of the network.
        turns: Every movement through a junction.
        settings: Settings of the ``[flows]`` section.
    """

    junction_ids: tuple[str, ...]
    roads: tuple[RoadConfig, ...]
    turns: tuple[TurnConfig, ...]
    settings: FlowSettings = field(default_factory=FlowSettings)

    def __post_init__(self) -> None:
        """Check the network.

        Raises:
            ValueError: If the network is invalid. The message names the problem.
        """
        validate_network_config(self)

    @cached_property
    def roads_by_id(self) -> dict[str, RoadConfig]:
        """Roads by their id."""
        return {road.id: road for road in self.roads}

    def preferred_turn_shares(self) -> np.ndarray:
        """Turn preferences divided by their sum per ``from_road``, in the order of turns."""
        totals: dict[str, float] = {}
        for turn in self.turns:
            totals[turn.from_road] = totals.get(turn.from_road, 0.0) + turn.preference
        return np.array([turn.preference / totals[turn.from_road] for turn in self.turns])

    def preferred_transfer_matrix(self) -> np.ndarray:
        """Share of the vehicles at the end of each road that reach the end of another one.

        Returns:
            ``A[r, q]``: share of the vehicles at the end of road ``q`` that reach the end of
            road ``r``, with the preferred turn shares and the ``through_share`` of ``r``.
        """
        road_index = {road.id: index for index, road in enumerate(self.roads)}
        matrix = np.zeros((len(self.roads), len(self.roads)))
        for turn, share in zip(self.turns, self.preferred_turn_shares(), strict=True):
            to_road = self.roads_by_id[turn.to_road]
            matrix[road_index[turn.to_road], road_index[turn.from_road]] += (
                share * to_road.through_share
            )
        return matrix

    def preferred_entry_shares(self) -> np.ndarray:
        """Entry road preferences divided by their sum per junction, in the order of roads.

        Roads that are not entry roads get 0.
        """
        totals: dict[str, float] = {}
        for road in self.roads:
            if road.kind == "entry" and road.to_junction is not None:
                totals[road.to_junction] = totals.get(road.to_junction, 0.0) + (
                    road.preference or 0.0
                )
        return np.array(
            [
                (road.preference or 0.0) / totals[road.to_junction]
                if road.kind == "entry" and road.to_junction is not None
                else 0.0
                for road in self.roads
            ]
        )


def load_network_config(path: str | Path) -> NetworkConfig:
    """Read the network flows part of a config file.

    Args:
        path: TOML config file.

    Returns:
        The checked network.

    Raises:
        ValueError: If the network or the ``[flows]`` section is invalid. The message names
            the file.
    """
    path = Path(path)
    config_tables = read_config(path)
    try:
        return NetworkConfig(
            junction_ids=junction_ids(config_tables),
            roads=tuple(_parse_road(table) for table in config_tables.get("roads", [])),
            turns=tuple(_parse_turn(table) for table in config_tables.get("turns", [])),
            settings=parse_table(config_tables.get("flows", {}), FlowSettings, "[flows]"),
        )
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None


def _parse_road(road_table: dict) -> RoadConfig:
    """Read one ``[[roads]]`` table, where ``from`` and ``to`` name the junctions."""
    table_name = f"road {road_table.get('id', '?')!r}"
    return parse_table(road_table, RoadConfig, table_name, ROAD_TOML_KEYS)


def _parse_turn(turn_table: dict) -> TurnConfig:
    """Read one ``[[turns]]`` table."""
    table_name = f"turn {turn_table.get('from_road', '?')!r} -> {turn_table.get('to_road', '?')!r}"
    return parse_table(turn_table, TurnConfig, table_name)

"""Checks of the network flows config. Each check raises a ValueError naming the problem."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from trafficgen.flows.config import FlowSettings, NetworkConfig, RoadConfig

MAX_SPECTRAL_RADIUS_OF_LEAVING_NETWORK = 1 - 1e-9


def validate_flow_settings(settings: FlowSettings) -> None:
    """Check the ``[flows]`` settings.

    Args:
        settings: The settings to check.

    Raises:
        ValueError: If a setting is not positive.
    """
    for name in ("tolerance_vph", "max_travel_time_fraction", "lane_capacity_vph"):
        _require_positive(f"flows {name}", getattr(settings, name))


def validate_network_config(config: NetworkConfig) -> None:
    """Check that the network is complete and that vehicles can leave it.

    Args:
        config: The network to check.

    Raises:
        ValueError: If the network is invalid. The message names the problem.
    """
    _validate_unique_road_ids(config)
    for road in config.roads:
        _validate_road(road, set(config.junction_ids))
    _validate_every_junction_has_roads_in_and_out(config)
    _validate_some_road_enters_the_network(config)
    _validate_turns_connect_roads(config)
    _validate_roads_into_junctions_have_turns(config)
    _validate_preferences_are_not_all_zero(config)
    _validate_vehicles_can_leave_the_network(config)


def _validate_road(road: RoadConfig, junction_ids: set[str]) -> None:
    """Check the junctions, the preference and the attributes of one road."""
    road_name = f"road {road.id!r}"
    if road.from_junction is None and road.to_junction is None:
        raise ValueError(f"{road_name} has neither 'from' nor 'to'")
    for junction in (road.from_junction, road.to_junction):
        if junction is not None and junction not in junction_ids:
            raise ValueError(f"{road_name} uses unknown junction {junction!r}")

    if road.kind == "entry" and road.preference is None:
        raise ValueError(f"{road_name} enters the network but has no 'preference'")
    if road.kind != "entry" and road.preference is not None:
        raise ValueError(f"{road_name}: 'preference' applies only to entry roads (without 'from')")
    _require_non_negative(f"{road_name}: preference", road.preference)

    if road.kind != "internal" and road.through_share != 1:
        raise ValueError(
            f"{road_name}: 'through_share' applies only to roads between two junctions"
        )
    if not 0 < road.through_share <= 1:
        raise ValueError(f"{road_name}: through_share must be in (0, 1], not {road.through_share}")

    for attribute in ("length_m", "lanes", "speed_limit_kmh"):
        _require_positive(f"{road_name}: {attribute}", getattr(road, attribute))


def _validate_unique_road_ids(config: NetworkConfig) -> None:
    """Check that no two roads share an id."""
    id_counts = Counter(road.id for road in config.roads)
    duplicate_ids = sorted(road_id for road_id, count in id_counts.items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"duplicate road ids: {duplicate_ids}")


def _validate_every_junction_has_roads_in_and_out(config: NetworkConfig) -> None:
    """Check that vehicles can reach and leave every junction."""
    for junction in config.junction_ids:
        if not any(road.to_junction == junction for road in config.roads):
            raise ValueError(f"junction {junction!r} has no road leading into it")
        if not any(road.from_junction == junction for road in config.roads):
            raise ValueError(f"junction {junction!r} has no road leading out of it")


def _validate_some_road_enters_the_network(config: NetworkConfig) -> None:
    """Check that traffic can enter the network at all."""
    if not any(road.kind == "entry" for road in config.roads):
        raise ValueError("no road enters the network: give at least one road no 'from'")


def _validate_turns_connect_roads(config: NetworkConfig) -> None:
    """Check that every turn joins two known roads at the same junction, once."""
    roads_by_id = config.roads_by_id
    seen_turns: set[tuple[str, str]] = set()
    for turn in config.turns:
        turn_name = f"turn {turn.from_road!r} -> {turn.to_road!r}"
        for road_id in (turn.from_road, turn.to_road):
            if road_id not in roads_by_id:
                raise ValueError(f"{turn_name} uses unknown road {road_id!r}")
        if (turn.from_road, turn.to_road) in seen_turns:
            raise ValueError(f"{turn_name} is defined twice")
        seen_turns.add((turn.from_road, turn.to_road))

        from_road, to_road = roads_by_id[turn.from_road], roads_by_id[turn.to_road]
        if from_road.to_junction is None:
            raise ValueError(f"{turn_name} starts on {from_road.id!r}, which leaves the network")
        if to_road.from_junction != from_road.to_junction:
            raise ValueError(
                f"{turn_name}: {from_road.id!r} ends at {from_road.to_junction!r}, "
                f"but {to_road.id!r} starts at {to_road.from_junction!r}"
            )
        _require_non_negative(f"{turn_name}: preference", turn.preference)


def _validate_roads_into_junctions_have_turns(config: NetworkConfig) -> None:
    """Check that vehicles at the end of every road can go somewhere."""
    roads_with_turns = {turn.from_road for turn in config.turns}
    for road in config.roads:
        if road.to_junction is not None and road.id not in roads_with_turns:
            raise ValueError(f"road {road.id!r} ends at a junction but has no turns")


def _validate_preferences_are_not_all_zero(config: NetworkConfig) -> None:
    """Check that each group of preferences can be turned into shares."""
    totals: dict[str, float] = defaultdict(float)
    for turn in config.turns:
        totals[f"turns from road {turn.from_road!r}"] += turn.preference
    for road in config.roads:
        if road.kind == "entry":
            totals[f"entry roads of junction {road.to_junction!r}"] += road.preference or 0.0
    for group, total in totals.items():
        if not total > 0:
            raise ValueError(f"the preferences of the {group} are all 0")


def _validate_vehicles_can_leave_the_network(config: NetworkConfig) -> None:
    """Check that no group of roads keeps vehicles forever, with the preferred shares.

    ``(I - A)^-1`` of the preferred transfer matrix ``A`` exists exactly when its spectral
    radius is below 1.
    """
    eigenvalues = np.linalg.eigvals(config.preferred_transfer_matrix())
    spectral_radius = max(abs(eigenvalues), default=0.0)
    if spectral_radius >= MAX_SPECTRAL_RADIUS_OF_LEAVING_NETWORK:
        raise ValueError(
            "vehicles can never leave the network: some roads only lead back to each other. "
            "Add a turn onto an exit road or a through_share below 1 on that loop"
        )


def _require_positive(name: str, value: float | None) -> None:
    """Raise if a value is set and not positive."""
    if value is not None and not value > 0:
        raise ValueError(f"{name} must be positive, not {value}")


def _require_non_negative(name: str, value: float | None) -> None:
    """Raise if a value is set and negative."""
    if value is not None and not value >= 0:
        raise ValueError(f"{name} must not be negative, not {value}")

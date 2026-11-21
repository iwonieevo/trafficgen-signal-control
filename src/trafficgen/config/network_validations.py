"""Checks of the layer 2 network config. Errors raise a ValueError naming the problem."""

from __future__ import annotations

import warnings
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING, get_args, get_type_hints

import numpy as np

from trafficgen.balancing.result import RoadDemandWarning

if TYPE_CHECKING:
    from trafficgen.config.network import BalanceSettings, NetworkConfig, RoadConfig

SUM_TO_ONE_TOLERANCE = 1e-6
MAX_SPECTRAL_RADIUS_OF_LEAVING_NETWORK = 1 - 1e-9
SECONDS_PER_HOUR = 3600


def validate_balance_settings(settings: BalanceSettings) -> None:
    allowed_weightings = get_args(get_type_hints(type(settings))["weighting"])
    if settings.weighting not in allowed_weightings:
        raise ValueError(
            f"balance weighting must be one of {allowed_weightings}, not {settings.weighting!r}"
        )
    for name in ("tolerance_vph", "max_travel_time_fraction", "lane_capacity_vph"):
        _require_positive(f"balance {name}", getattr(settings, name))


def validate_network_config(config: NetworkConfig) -> None:
    if not config.junctions:
        raise ValueError("the network defines no junctions")
    _require_positive("scale", config.scale)
    _validate_unique_road_ids(config)
    for road in config.roads:
        _validate_road(road, set(config.junction_ids))
    _validate_every_junction_has_roads_in_and_out(config)
    _validate_some_road_enters_the_network(config)
    _validate_entry_weights_sum_to_one(config)
    _validate_turns_connect_roads(config)
    _validate_roads_into_junctions_have_turns(config)
    _validate_turn_ratios_sum_to_one(config)
    _validate_vehicles_can_leave_the_network(config)


def warn_about_long_travel_times(config: NetworkConfig) -> None:
    max_travel_time_s = config.balance.max_travel_time_fraction * SECONDS_PER_HOUR
    for road in config.roads:
        travel_time_s = road.free_flow_time_s
        if travel_time_s is not None and travel_time_s > max_travel_time_s:
            warnings.warn(
                f"road {road.id!r} takes {travel_time_s:.0f} s at the speed limit, more than "
                f"{max_travel_time_s:.0f} s: its flow is still counted in the same hour",
                RoadDemandWarning,
                stacklevel=4,
            )


def _validate_road(road: RoadConfig, junction_ids: set[str]) -> None:
    road_name = f"road {road.id!r}"
    if road.from_junction is None and road.to_junction is None:
        raise ValueError(f"{road_name} has neither 'from' nor 'to'")
    for junction in (road.from_junction, road.to_junction):
        if junction is not None and junction not in junction_ids:
            raise ValueError(f"{road_name} uses unknown junction {junction!r}")

    if road.kind == "entry" and road.weight is None:
        raise ValueError(f"{road_name} enters the network but has no 'weight'")
    if road.kind != "entry" and road.weight is not None:
        raise ValueError(f"{road_name}: 'weight' applies only to entry roads (without 'from')")
    _require_non_negative(f"{road_name}: weight", road.weight)

    if road.kind != "internal" and road.through_share != 1:
        raise ValueError(
            f"{road_name}: 'through_share' applies only to roads between two junctions"
        )
    if not 0 < road.through_share <= 1:
        raise ValueError(f"{road_name}: through_share must be in (0, 1], not {road.through_share}")

    for attribute in ("length_m", "lanes", "speed_limit_kmh"):
        _require_positive(f"{road_name}: {attribute}", getattr(road, attribute))


def _validate_unique_road_ids(config: NetworkConfig) -> None:
    id_counts = Counter(road.id for road in config.roads)
    duplicate_ids = sorted(road_id for road_id, count in id_counts.items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"duplicate road ids: {duplicate_ids}")


def _validate_every_junction_has_roads_in_and_out(config: NetworkConfig) -> None:
    for junction in config.junction_ids:
        if not any(road.to_junction == junction for road in config.roads):
            raise ValueError(f"junction {junction!r} has no road leading into it")
        if not any(road.from_junction == junction for road in config.roads):
            raise ValueError(f"junction {junction!r} has no road leading out of it")


def _validate_some_road_enters_the_network(config: NetworkConfig) -> None:
    if not any(road.kind == "entry" for road in config.roads):
        raise ValueError("no road enters the network: give at least one road no 'from'")


def _validate_entry_weights_sum_to_one(config: NetworkConfig) -> None:
    weights_by_junction: dict[str, list[float]] = defaultdict(list)
    for road in config.roads:
        if road.kind == "entry" and road.to_junction is not None:
            weights_by_junction[road.to_junction].append(road.weight or 0.0)
    _validate_shares_sum_to_one(
        weights_by_junction, lambda junction: f"weights of the entry roads of junction {junction!r}"
    )


def _validate_turns_connect_roads(config: NetworkConfig) -> None:
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
        _require_non_negative(f"{turn_name}: ratio", turn.ratio)


def _validate_roads_into_junctions_have_turns(config: NetworkConfig) -> None:
    roads_with_turns = {turn.from_road for turn in config.turns}
    for road in config.roads:
        if road.to_junction is not None and road.id not in roads_with_turns:
            raise ValueError(f"road {road.id!r} ends at a junction but has no turns")


def _validate_turn_ratios_sum_to_one(config: NetworkConfig) -> None:
    ratios_by_road: dict[str, list[float]] = defaultdict(list)
    for turn in config.turns:
        ratios_by_road[turn.from_road].append(turn.ratio)
    _validate_shares_sum_to_one(ratios_by_road, lambda road_id: f"turn ratios of road {road_id!r}")


def _validate_vehicles_can_leave_the_network(config: NetworkConfig) -> None:
    eigenvalues = np.linalg.eigvals(config.road_transfer_matrix())
    spectral_radius = max(abs(eigenvalues), default=0.0)
    if spectral_radius >= MAX_SPECTRAL_RADIUS_OF_LEAVING_NETWORK:
        raise ValueError(
            "vehicles can never leave the network: some roads only lead back to each other. "
            "Add a turn onto an exit road or a through_share below 1 on that loop"
        )


def _validate_shares_sum_to_one(
    shares_by_group: dict[str, list[float]], describe_group: Callable[[str], str]
) -> None:
    for group, shares in shares_by_group.items():
        share_sum = sum(shares)
        if not np.isclose(share_sum, 1.0, atol=SUM_TO_ONE_TOLERANCE):
            raise ValueError(f"{describe_group(group)} sum to {share_sum:g}, not 1")


def _require_positive(name: str, value: float | None) -> None:
    if value is not None and not value > 0:
        raise ValueError(f"{name} must be positive, not {value}")


def _require_non_negative(name: str, value: float | None) -> None:
    if value is not None and not value >= 0:
        raise ValueError(f"{name} must not be negative, not {value}")

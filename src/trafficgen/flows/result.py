"""The result of the network flows: output tables, the balance report and warnings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from trafficgen.timeutils import SECONDS_PER_HOUR

if TYPE_CHECKING:
    from trafficgen.flows.config import NetworkConfig, RoadConfig

NO_FLOW_VPH = 1e-9


class FlowWarning(UserWarning):
    """Issued for unmet junction totals, long travel times and flows over lane capacity."""


@dataclass(frozen=True)
class NetworkFlows:
    """Hourly flows on every road and turn in long format, with the balance report.

    The tables and their columns are listed in docs/network-flows.md.

    Attributes:
        entry_flows: Vehicles per hour entering the network on each entry road, with the
            preferred and the actually used share among the entry roads of its junction.
        road_flows: Vehicles per hour reaching the end of each road.
        turn_flows: Vehicles per hour of each movement, with the preferred and the actually
            used share among the turns from the same road.
        junction_balance: Requested and achieved totals per junction and hour, with
            ``difference = achieved - requested``.
        roads: One row per road with its attributes, travel time and highest flow per lane.
        adjusted_hours: Hours in which the preferred shares were changed to meet the totals.
        warnings: Messages about unmet totals, long travel times and flows over capacity.
        tolerance_vph: Largest difference that still counts as met.
    """

    entry_flows: pd.DataFrame
    road_flows: pd.DataFrame
    turn_flows: pd.DataFrame
    junction_balance: pd.DataFrame
    roads: pd.DataFrame
    adjusted_hours: pd.DatetimeIndex
    warnings: tuple[str, ...]
    tolerance_vph: float

    @classmethod
    def from_solution(
        cls,
        config: NetworkConfig,
        hours: pd.DatetimeIndex,
        road_flows: np.ndarray,
        turn_flows: np.ndarray,
        requested_totals: np.ndarray,
        achieved_totals: np.ndarray,
        adjusted_hours: pd.DatetimeIndex,
    ) -> NetworkFlows:
        """Build the output tables and warnings from the solved flows.

        Args:
            config: The network.
            hours: The hours, one row of every array each.
            road_flows: Flow of every road, in the order of ``config.roads``.
            turn_flows: Flow of every turn, in the order of ``config.turns``.
            requested_totals: Requested total of every junction.
            achieved_totals: Achieved total of every junction.
            adjusted_hours: Hours in which the preferred shares were changed.

        Returns:
            The result with its warnings.
        """
        settings = config.settings
        road_summary = _road_summary_table(config.roads, road_flows, settings.lane_capacity_vph)
        flows = cls(
            entry_flows=_entry_flow_table(config, hours, road_flows),
            road_flows=_road_flow_table(config, hours, road_flows),
            turn_flows=_turn_flow_table(config, hours, road_flows, turn_flows),
            junction_balance=_long_table(
                hours,
                {"junction": list(config.junction_ids)},
                {
                    "requested": requested_totals,
                    "achieved": achieved_totals,
                    "difference": achieved_totals - requested_totals,
                },
            ),
            roads=road_summary,
            adjusted_hours=pd.DatetimeIndex(adjusted_hours, name="datetime"),
            warnings=(),
            tolerance_vph=settings.tolerance_vph,
        )
        messages = _travel_time_warnings(config)
        messages += _capacity_warnings(road_summary, len(hours), settings.lane_capacity_vph)
        messages += _unbalanced_hours_warnings(flows)
        return replace(flows, warnings=tuple(messages))

    @property
    def output_tables(self) -> dict[str, pd.DataFrame]:
        """The five output tables by name, as written by ``scripts/generate_flows.py``."""
        return {
            "entry_flows": self.entry_flows,
            "road_flows": self.road_flows,
            "turn_flows": self.turn_flows,
            "junction_balance": self.junction_balance,
            "roads": self.roads,
        }

    @property
    def unbalanced_hours(self) -> pd.DatetimeIndex:
        """Hours in which some junction total differs by more than ``tolerance_vph``."""
        differences = self.junction_balance.pivot_table(
            index="datetime", columns="junction", values="difference", aggfunc="first"
        )
        is_unbalanced = np.abs(differences.to_numpy()).max(axis=1) > self.tolerance_vph
        return pd.DatetimeIndex(differences.index[is_unbalanced], name="datetime")


def _long_table(
    hours: pd.DatetimeIndex,
    key_columns: dict[str, Sequence[object] | np.ndarray],
    value_columns: dict[str, np.ndarray],
) -> pd.DataFrame:
    """Build a long table with one row per hour and item.

    Args:
        hours: The hours.
        key_columns: Columns that describe the items, one value per item.
        value_columns: Columns with one row per hour and one column per item.

    Returns:
        Rows ordered by hour, then by item.
    """
    item_count = len(next(iter(key_columns.values())))
    table: dict[str, object] = {"datetime": np.repeat(hours, item_count)}
    for column_name, keys in key_columns.items():
        table[column_name] = np.tile(np.asarray(keys), len(hours))
    for column_name, values_per_hour in value_columns.items():
        table[column_name] = np.asarray(values_per_hour).ravel()
    return pd.DataFrame(table)


def _shares(flows: np.ndarray, totals: np.ndarray, preferred: np.ndarray) -> np.ndarray:
    """Divide flows by their totals, using the preferred share where there is no traffic."""
    has_traffic = totals > NO_FLOW_VPH
    safe_totals = np.where(has_traffic, totals, 1.0)
    return np.where(has_traffic, flows / safe_totals, preferred)


def _entry_flow_table(
    config: NetworkConfig, hours: pd.DatetimeIndex, road_flows: np.ndarray
) -> pd.DataFrame:
    """Build the ``entry_flows`` table."""
    entry = [index for index, road in enumerate(config.roads) if road.kind == "entry"]
    junctions = [config.roads[index].to_junction for index in entry]
    flows = road_flows[:, entry]
    junction_totals = np.column_stack(
        [flows[:, [other == junction for other in junctions]].sum(axis=1) for junction in junctions]
    ).reshape(flows.shape)
    preferred = config.preferred_entry_shares()[entry]
    return _long_table(
        hours,
        {
            "road": [config.roads[index].id for index in entry],
            "junction": junctions,
            "preferred_share": preferred,
        },
        {
            "share": _shares(flows, junction_totals, preferred),
            "vehicles_per_hour": flows,
        },
    )


def _road_flow_table(
    config: NetworkConfig, hours: pd.DatetimeIndex, road_flows: np.ndarray
) -> pd.DataFrame:
    """Build the ``road_flows`` table."""
    roads = config.roads
    return _long_table(
        hours,
        {
            "road": [road.id for road in roads],
            "from_junction": [road.from_junction for road in roads],
            "to_junction": [road.to_junction for road in roads],
            "kind": [road.kind for road in roads],
        },
        {"vehicles_per_hour": road_flows},
    )


def _turn_flow_table(
    config: NetworkConfig,
    hours: pd.DatetimeIndex,
    road_flows: np.ndarray,
    turn_flows: np.ndarray,
) -> pd.DataFrame:
    """Build the ``turn_flows`` table."""
    turns = config.turns
    road_index = {road.id: index for index, road in enumerate(config.roads)}
    from_road_flows = road_flows[:, [road_index[turn.from_road] for turn in turns]]
    preferred = config.preferred_turn_shares()
    return _long_table(
        hours,
        {
            "junction": [config.roads_by_id[turn.from_road].to_junction for turn in turns],
            "from_road": [turn.from_road for turn in turns],
            "to_road": [turn.to_road for turn in turns],
            "preferred_share": preferred,
        },
        {
            "share": _shares(turn_flows, from_road_flows, preferred),
            "vehicles_per_hour": turn_flows,
        },
    )


def _road_summary_table(
    roads: tuple[RoadConfig, ...], road_flows: np.ndarray, lane_capacity_vph: float
) -> pd.DataFrame:
    """Build the ``roads`` table: attributes, travel time and flow per lane of each road."""
    lanes = np.array([road.lanes or np.nan for road in roads], dtype=float)
    flow_per_lane = road_flows / lanes
    summary = pd.DataFrame([_road_columns(road) for road in roads])
    summary["max_flow_per_lane"] = flow_per_lane.max(axis=0) if len(road_flows) else np.nan
    summary["hours_over_capacity"] = (flow_per_lane > lane_capacity_vph).sum(axis=0)
    return summary


def _road_columns(road: RoadConfig) -> dict[str, object]:
    """Describe one road for the ``roads`` table."""
    config_fields = {name: value for name, value in asdict(road).items() if name != "id"}
    return {
        "road": road.id,
        "kind": road.kind,
        **config_fields,
        "free_flow_time_s": road.free_flow_time_s,
    }


def _travel_time_warnings(config: NetworkConfig) -> list[str]:
    """Warn about roads that take a large part of an hour at the speed limit."""
    max_travel_time_s = config.settings.max_travel_time_fraction * SECONDS_PER_HOUR
    return [
        f"road {road.id!r} takes {road.free_flow_time_s:.0f} s at the speed limit, more than "
        f"{max_travel_time_s:.0f} s: its flow is still counted in the same hour"
        for road in config.roads
        if road.free_flow_time_s is not None and road.free_flow_time_s > max_travel_time_s
    ]


def _capacity_warnings(
    road_summary: pd.DataFrame, hour_count: int, lane_capacity_vph: float
) -> list[str]:
    """Warn about roads whose flow per lane is above the capacity in some hours."""
    over_capacity = road_summary.loc[(road_summary["hours_over_capacity"] > 0).to_numpy()]
    return [
        f"road {road['road']!r} has more than {lane_capacity_vph:g} vehicles per hour per lane "
        f"in {road['hours_over_capacity']} of {hour_count} hours "
        f"(highest {road['max_flow_per_lane']:.0f}); flows are not limited"
        for road in over_capacity.to_dict("records")
    ]


def _unbalanced_hours_warnings(flows: NetworkFlows) -> list[str]:
    """Warn about hours in which some junction total could not be met."""
    unbalanced_hours = flows.unbalanced_hours
    if unbalanced_hours.empty:
        return []
    balance = flows.junction_balance
    worst = balance.iloc[int(np.abs(balance["difference"].to_numpy()).argmax())]
    hour_count = balance["datetime"].nunique()
    return [
        f"{len(unbalanced_hours)} of {hour_count} hours could not be balanced within "
        f"{flows.tolerance_vph:g} vehicles per hour. Largest difference: "
        f"{worst['difference']:+.1f} at junction {worst['junction']!r} on {worst['datetime']} "
        f"(requested {worst['requested']:.1f}, achieved {worst['achieved']:.1f})"
    ]

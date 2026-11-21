"""Result of layer 2: the output tables of every road and turn of a network, and its report."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from trafficgen.utils.tables import hourly_long_table

if TYPE_CHECKING:
    from trafficgen.config.network import NetworkConfig, RoadConfig


class RoadDemandWarning(UserWarning):
    """Raised for unbalanced hours and for unrealistic travel times or flows per lane."""


@dataclass(frozen=True)
class RoadDemand:
    """Hourly flows on every road and turn in long format, with the balance report.

    ``road_flows`` holds the vehicles per hour reaching the end of each road, and
    ``junction_balance`` the requested and achieved totals, ``difference = achieved - requested``.
    """

    entry_flows: pd.DataFrame
    road_flows: pd.DataFrame
    turn_flows: pd.DataFrame
    junction_balance: pd.DataFrame
    roads: pd.DataFrame
    warnings: tuple[str, ...]
    tolerance_vph: float

    @classmethod
    def from_flows(
        cls,
        config: NetworkConfig,
        hours: pd.DatetimeIndex,
        road_flows: np.ndarray,
        requested_totals: np.ndarray,
        achieved_totals: np.ndarray,
    ) -> RoadDemand:
        settings = config.balance
        road_flow_table = _road_flow_table(config, hours, road_flows)
        road_summary = _road_summary_table(config.roads, road_flows, settings.lane_capacity_vph)
        demand = cls(
            entry_flows=_entry_flow_table(road_flow_table),
            road_flows=road_flow_table,
            turn_flows=_turn_flow_table(config, hours, road_flows),
            junction_balance=hourly_long_table(
                hours,
                {"junction": config.junction_ids},
                {
                    "requested": requested_totals,
                    "achieved": achieved_totals,
                    "difference": achieved_totals - requested_totals,
                },
            ),
            roads=road_summary,
            warnings=(),
            tolerance_vph=settings.tolerance_vph,
        )
        messages = _capacity_warnings(road_summary, len(hours), settings.lane_capacity_vph)
        messages += _unbalanced_hours_warnings(demand)
        return replace(demand, warnings=tuple(messages))

    @property
    def output_tables(self) -> dict[str, pd.DataFrame]:
        return {
            "entry_flows": self.entry_flows,
            "road_flows": self.road_flows,
            "turn_flows": self.turn_flows,
            "junction_balance": self.junction_balance,
            "roads": self.roads,
        }

    @property
    def unbalanced_hours(self) -> pd.DatetimeIndex:
        differences = self.junction_balance.pivot_table(
            index="datetime", columns="junction", values="difference", aggfunc="first"
        )
        is_unbalanced = np.abs(differences.to_numpy()).max(axis=1) > self.tolerance_vph
        return pd.DatetimeIndex(differences.index[is_unbalanced], name="datetime")


def _road_summary_table(
    roads: tuple[RoadConfig, ...], road_flows: np.ndarray, lane_capacity_vph: float
) -> pd.DataFrame:
    lanes = np.array([road.lanes or np.nan for road in roads], dtype=float)
    flow_per_lane = road_flows / lanes
    summary = pd.DataFrame([_road_columns(road) for road in roads])
    summary["max_flow_per_lane"] = flow_per_lane.max(axis=0) if len(road_flows) else np.nan
    summary["hours_over_capacity"] = (flow_per_lane > lane_capacity_vph).sum(axis=0)
    return summary


def _capacity_warnings(
    road_summary: pd.DataFrame, hour_count: int, lane_capacity_vph: float
) -> list[str]:
    over_capacity = road_summary.loc[(road_summary["hours_over_capacity"] > 0).to_numpy()]
    return [
        f"road {road['road']!r} has more than {lane_capacity_vph:g} vehicles per hour per lane "
        f"in {road['hours_over_capacity']} of {hour_count} hours "
        f"(highest {road['max_flow_per_lane']:.0f}); flows are not limited"
        for road in over_capacity.to_dict("records")
    ]


def _unbalanced_hours_warnings(demand: RoadDemand) -> list[str]:
    unbalanced_hours = demand.unbalanced_hours
    if unbalanced_hours.empty:
        return []
    balance = demand.junction_balance
    worst = balance.iloc[int(np.abs(balance["difference"].to_numpy()).argmax())]
    hour_count = balance["datetime"].nunique()
    return [
        f"{len(unbalanced_hours)} of {hour_count} hours could not be balanced within "
        f"{demand.tolerance_vph:g} vehicles per hour. Largest difference: "
        f"{worst['difference']:+.1f} at junction {worst['junction']!r} on {worst['datetime']} "
        f"(requested {worst['requested']:.1f}, achieved {worst['achieved']:.1f})"
    ]


def _road_flow_table(
    config: NetworkConfig, hours: pd.DatetimeIndex, road_flows: np.ndarray
) -> pd.DataFrame:
    roads = config.roads
    return hourly_long_table(
        hours,
        {
            "road": [road.id for road in roads],
            "from_junction": [road.from_junction for road in roads],
            "to_junction": [road.to_junction for road in roads],
            "kind": [road.kind for road in roads],
        },
        {"vehicles_per_hour": road_flows},
    )


def _entry_flow_table(road_flow_table: pd.DataFrame) -> pd.DataFrame:
    entry_rows = road_flow_table.loc[(road_flow_table["kind"] == "entry").to_numpy()]
    return pd.DataFrame(
        {
            "datetime": entry_rows["datetime"].to_numpy(),
            "road": entry_rows["road"].to_numpy(),
            "junction": entry_rows["to_junction"].to_numpy(),
            "vehicles_per_hour": entry_rows["vehicles_per_hour"].to_numpy(),
        }
    )


def _turn_flow_table(
    config: NetworkConfig, hours: pd.DatetimeIndex, road_flows: np.ndarray
) -> pd.DataFrame:
    turns = config.turns
    road_index = {road.id: index for index, road in enumerate(config.roads)}
    ratios = np.array([turn.ratio for turn in turns])
    from_road_flows = road_flows[:, [road_index[turn.from_road] for turn in turns]]
    return hourly_long_table(
        hours,
        {
            "junction": [config.roads_by_id[turn.from_road].to_junction for turn in turns],
            "from_road": [turn.from_road for turn in turns],
            "to_road": [turn.to_road for turn in turns],
            "ratio": ratios,
        },
        {"vehicles_per_hour": from_road_flows * ratios},
    )


def _road_columns(road: RoadConfig) -> dict[str, object]:
    config_fields = {name: value for name, value in asdict(road).items() if name != "id"}
    return {
        "road": road.id,
        "kind": road.kind,
        **config_fields,
        "free_flow_time_s": road.free_flow_time_s,
    }

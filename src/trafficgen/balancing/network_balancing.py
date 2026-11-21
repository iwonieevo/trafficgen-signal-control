"""Layer 2: balance hourly junction counts over the roads and turns of a network.

The model is described in docs/layer2.md.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from trafficgen.balancing.result import RoadDemand, RoadDemandWarning
from trafficgen.utils.optimization import non_negative_least_squares_per_row

if TYPE_CHECKING:
    from trafficgen.config.network import NetworkConfig


class NetworkBalancer:
    """Linear model of how traffic entering a network spreads over its roads.

    Both matrices have one column per junction in ``entry_junction_ids``, the junctions with
    entry roads. Each column holds the effect of one vehicle entering at that junction.
    """

    def __init__(self, config: NetworkConfig) -> None:
        self.config = config
        self.junction_ids = config.junction_ids
        self.entry_junction_ids = config.entry_junction_ids
        identity = np.eye(len(config.roads))
        self.road_flow_per_entering_vehicle = np.maximum(
            np.linalg.solve(identity - config.road_transfer_matrix(), config.entry_weight_matrix()),
            0.0,
        )
        self.junction_traffic_per_entering_vehicle = (
            config.road_end_matrix() @ self.road_flow_per_entering_vehicle
        )

    def balance(self, counts: pd.DataFrame) -> RoadDemand:
        requested = self._validated_counts(counts)
        hours = pd.DatetimeIndex(requested.index)
        requested_totals = requested.to_numpy()
        entry_flows = non_negative_least_squares_per_row(
            self.junction_traffic_per_entering_vehicle,
            requested_totals,
            self._difference_weights(requested_totals),
        )
        road_flows = entry_flows @ self.road_flow_per_entering_vehicle.T
        achieved_totals = entry_flows @ self.junction_traffic_per_entering_vehicle.T

        demand = RoadDemand.from_flows(
            self.config, hours, road_flows, requested_totals, achieved_totals
        )
        for message in demand.warnings:
            warnings.warn(message, RoadDemandWarning, stacklevel=2)
        return demand

    def _validated_counts(self, counts: pd.DataFrame) -> pd.DataFrame:
        missing = [junction for junction in self.junction_ids if junction not in counts.columns]
        if missing:
            raise ValueError(f"counts have no column for junctions {missing}")
        if not isinstance(counts.index, pd.DatetimeIndex):
            raise ValueError("counts must be indexed by datetime")
        values = counts.loc[:, self.junction_ids].to_numpy(dtype=float)
        if np.isnan(values).any():
            raise ValueError("counts contain missing values")
        if (values < 0).any():
            raise ValueError("counts contain negative values")
        hours = pd.DatetimeIndex(counts.index, name="datetime")
        return pd.DataFrame(values, index=hours, columns=self.junction_ids)

    def _difference_weights(self, requested_totals: np.ndarray) -> np.ndarray:
        if self.config.balance.weighting == "relative":
            return 1.0 / np.maximum(requested_totals, 1.0)
        return np.ones_like(requested_totals)

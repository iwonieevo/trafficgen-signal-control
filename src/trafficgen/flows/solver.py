"""Spread hourly junction counts over the roads and turns of a network.

The model is described in docs/network-flows.md. In short, for every hour:

1. Preferred flows: vehicles enter at the boundary and follow the preferred shares. The
   entry flow of each junction is fitted with non-negative least squares, so that the
   traffic through every junction is as close to its count as possible.
2. If a junction total is still missed, the flows closest to the preferred ones that meet
   every total exactly are used instead. Only the shares change, never the totals.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from scipy.optimize import minimize, nnls

from trafficgen.flows.result import FlowWarning, NetworkFlows

if TYPE_CHECKING:
    from trafficgen.flows.config import NetworkConfig

EXACT_FIT_TOLERANCE = 1e-10
EXACT_FIT_MAX_ITERATIONS = 500


class FlowSolver:
    """Turns hourly junction counts into flows on every road and turn of one network.

    Flows are rates in vehicles per hour and need not be integers. Given the counts, the
    result is deterministic.
    """

    def __init__(self, config: NetworkConfig) -> None:
        """Build the matrices of the network.

        Args:
            config: The checked network.
        """
        self.config = config
        roads, turns = config.roads, config.turns
        road_index = {road.id: index for index, road in enumerate(roads)}
        self._entry_roads = [index for index, road in enumerate(roads) if road.kind == "entry"]
        self._turn_from_roads = [road_index[turn.from_road] for turn in turns]
        self._preferred_turn_shares = config.preferred_turn_shares()

        # C[j, r]: 1 if road r ends at junction j.
        self._road_end_matrix = np.array(
            [
                [float(road.to_junction == junction) for road in roads]
                for junction in config.junction_ids
            ]
        ).reshape(len(config.junction_ids), len(roads))

        # Step 1: road flows per vehicle entering at each junction, (I - A)^-1 B.
        entry_junctions = [
            junction
            for junction in config.junction_ids
            if any(road.kind == "entry" and road.to_junction == junction for road in roads)
        ]
        entry_shares = config.preferred_entry_shares()
        entry_matrix = np.array(
            [
                [
                    entry_shares[index] if road.to_junction == junction else 0.0
                    for junction in entry_junctions
                ]
                for index, road in enumerate(roads)
            ]
        ).reshape(len(roads), len(entry_junctions))
        transfer = np.eye(len(roads)) - config.preferred_transfer_matrix()
        self._road_flow_per_entering_vehicle = np.maximum(
            np.linalg.solve(transfer, entry_matrix), 0.0
        )
        self._junction_traffic_per_entering_vehicle = (
            self._road_end_matrix @ self._road_flow_per_entering_vehicle
        )

        # Step 2: the unknowns are the flows of the entry roads followed by the turn flows.
        variable_count = len(self._entry_roads) + len(turns)
        # G[r, x]: road flow as a function of the unknowns.
        self._road_flow_matrix = np.zeros((len(roads), variable_count))
        # O[r, x]: sum of the turns leaving road r.
        leaving_matrix = np.zeros((len(roads), variable_count))
        for position, index in enumerate(self._entry_roads):
            self._road_flow_matrix[index, position] = 1.0
        for turn_number, turn in enumerate(turns):
            column = len(self._entry_roads) + turn_number
            to_road = road_index[turn.to_road]
            self._road_flow_matrix[to_road, column] = roads[to_road].through_share
            leaving_matrix[road_index[turn.from_road], column] = 1.0
        roads_into_junctions = [index for index, road in enumerate(roads) if road.to_junction]
        # Junction totals, then: what reaches the end of a road turns somewhere.
        self._constraint_matrix = np.vstack(
            [
                self._road_end_matrix @ self._road_flow_matrix,
                (self._road_flow_matrix - leaving_matrix)[roads_into_junctions],
            ]
        )

    def solve(self, counts: pd.DataFrame) -> NetworkFlows:
        """Compute the flows of every hour of the requested junction counts.

        Warnings of the result are also issued as ``FlowWarning``.

        Args:
            counts: Requested vehicles per hour through each junction, indexed by datetime,
                with one column per junction id. Other columns are ignored.

        Returns:
            The flows on every road and turn, and how well the counts were met.

        Raises:
            ValueError: If a junction has no column, or the counts are missing or negative.
        """
        requested = self._validated_counts(counts)
        hours = pd.DatetimeIndex(requested.index, name="datetime")
        requested_totals = requested.to_numpy()

        preferred = self._preferred_unknowns(requested_totals)
        unknowns = preferred.copy()
        preferred_totals = preferred @ (self._road_end_matrix @ self._road_flow_matrix).T
        missed = np.abs(preferred_totals - requested_totals).max(axis=1, initial=0.0)
        adjusted = missed > self.config.settings.tolerance_vph
        for hour in np.flatnonzero(adjusted):
            unknowns[hour] = self._closest_exact_unknowns(preferred[hour], requested_totals[hour])

        changed = (unknowns != preferred).any(axis=1)
        road_flows = unknowns @ self._road_flow_matrix.T
        flows = NetworkFlows.from_solution(
            self.config,
            hours,
            road_flows=road_flows,
            turn_flows=unknowns[:, len(self._entry_roads) :],
            requested_totals=requested_totals,
            achieved_totals=road_flows @ self._road_end_matrix.T,
            adjusted_hours=hours[changed],
        )
        for message in flows.warnings:
            warnings.warn(message, FlowWarning, stacklevel=2)
        return flows

    def _preferred_unknowns(self, requested_totals: np.ndarray) -> np.ndarray:
        """Step 1: fit the entry flows per hour and follow the preferred shares.

        Args:
            requested_totals: Requested totals, one row per hour and one column per junction.

        Returns:
            The unknowns of step 2 for every hour: entry road flows, then turn flows.
        """
        entering = np.array(
            [
                nnls(self._junction_traffic_per_entering_vehicle, totals)[0]
                for totals in requested_totals
            ]
        ).reshape(len(requested_totals), self._junction_traffic_per_entering_vehicle.shape[1])
        road_flows = entering @ self._road_flow_per_entering_vehicle.T
        turn_flows = road_flows[:, self._turn_from_roads] * self._preferred_turn_shares
        return np.hstack([road_flows[:, self._entry_roads], turn_flows])

    def _closest_exact_unknowns(self, preferred: np.ndarray, totals: np.ndarray) -> np.ndarray:
        """Step 2: the non-negative flows closest to the preferred ones that meet the totals.

        Args:
            preferred: Unknowns of one hour from step 1.
            totals: Requested totals of that hour.

        Returns:
            The adjusted unknowns, or ``preferred`` if no exact solution was found, for
            example because a junction cannot receive enough traffic from its neighbours.
        """
        matrix = self._constraint_matrix
        targets = np.concatenate([totals, np.zeros(len(matrix) - len(totals))])
        result = minimize(
            lambda unknowns: 0.5 * np.sum((unknowns - preferred) ** 2),
            x0=preferred,
            jac=lambda unknowns: unknowns - preferred,
            method="SLSQP",
            bounds=[(0.0, None)] * len(preferred),
            constraints=[
                {
                    "type": "eq",
                    "fun": lambda unknowns: matrix @ unknowns - targets,
                    "jac": lambda _: matrix,
                }
            ],
            options={"ftol": EXACT_FIT_TOLERANCE, "maxiter": EXACT_FIT_MAX_ITERATIONS},
        )
        adjusted = np.maximum(result.x, 0.0)
        if np.abs(matrix @ adjusted - targets).max() > self.config.settings.tolerance_vph:
            return preferred
        return adjusted

    def _validated_counts(self, counts: pd.DataFrame) -> pd.DataFrame:
        """Check the requested counts and keep the junction columns in config order.

        Args:
            counts: Requested counts.

        Returns:
            The counts as floats, one column per junction.

        Raises:
            ValueError: If a junction has no column, or the counts are missing or negative.
        """
        junction_ids = list(self.config.junction_ids)
        missing = [junction for junction in junction_ids if junction not in counts.columns]
        if missing:
            raise ValueError(f"counts have no column for junctions {missing}")
        if not isinstance(counts.index, pd.DatetimeIndex):
            raise ValueError("counts must be indexed by datetime")
        values = counts.loc[:, junction_ids].to_numpy(dtype=float)
        if np.isnan(values).any():
            raise ValueError("counts contain missing values")
        if (values < 0).any():
            raise ValueError("counts contain negative values")
        return pd.DataFrame(values, index=counts.index, columns=junction_ids)

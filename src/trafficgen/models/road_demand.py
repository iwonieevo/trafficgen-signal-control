"""Layer 2 generator: hourly flows on every road and turn of a network.

The model is described in docs/layer2.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self

import numpy as np
import pandas as pd

from trafficgen.balancing.network_balancing import NetworkBalancer
from trafficgen.balancing.result import RoadDemand
from trafficgen.models.hourly_counts import HourlyCountModel, StatisticalCountModel, TimeLike

if TYPE_CHECKING:
    from trafficgen.config.network import NetworkConfig


class RoadDemandModel:
    """Layer 2 generator: samples junction counts with layer 1 and balances them over the network.

    Used like the layer 1 models: ``fit`` on historical counts, then ``sample`` a time range.
    """

    def __init__(self, config: NetworkConfig) -> None:
        self.config = config
        self.balancer = NetworkBalancer(config)
        self.junction_models_: dict[str, HourlyCountModel] | None = None

    def fit(self, counts_by_junction: Mapping[str, pd.Series]) -> Self:
        missing = [j for j in self.config.junction_ids if j not in counts_by_junction]
        if missing:
            raise ValueError(f"no historical counts for junctions {missing}")
        self.junction_models_ = {
            junction: StatisticalCountModel().fit(counts_by_junction[junction])
            for junction in self.config.junction_ids
        }
        return self

    def sample(
        self, start: TimeLike, end: TimeLike, seed: int | None = None, scale: float | None = None
    ) -> RoadDemand:
        return self.balancer.balance(self.sample_junction_counts(start, end, seed, scale))

    def sample_junction_counts(
        self, start: TimeLike, end: TimeLike, seed: int | None = None, scale: float | None = None
    ) -> pd.DataFrame:
        if self.junction_models_ is None:
            raise RuntimeError("fit the model before sampling")
        junction_ids = self.config.junction_ids
        junction_seeds = _independent_junction_seeds(seed, len(junction_ids))
        count_scale = self.config.scale if scale is None else scale
        counts = {
            junction: self.junction_models_[junction].sample(
                start, end, seed=junction_seed, scale=count_scale
            )
            for junction, junction_seed in zip(junction_ids, junction_seeds, strict=True)
        }
        return pd.DataFrame(counts).rename_axis("datetime")


def _independent_junction_seeds(seed: int | None, junction_count: int) -> list[int | None]:
    if seed is None:
        return [None] * junction_count
    child_sequences = np.random.SeedSequence(seed).spawn(junction_count)
    return [int(child.generate_state(1)[0]) for child in child_sequences]

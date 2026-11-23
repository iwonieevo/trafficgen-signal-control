"""Sample the hourly counts of several junctions together.

Each junction keeps its own model, but statistical models draw the same calendar weeks of
their fitted noise. The noise of real junctions is correlated, for example on holidays or
in bad weather, and drawing the same weeks keeps that correlation without a joint model.
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd

from trafficgen.counts.models import HourlyCountModel, StatisticalCountModel
from trafficgen.timeutils import HOURS_PER_WEEK, TimeLike, hourly_range

MAX_SEED = 2**32


def sample_junctions(
    models: Mapping[str, HourlyCountModel],
    start: TimeLike,
    end: TimeLike,
    seed: int | None = None,
    scale: float = 1.0,
) -> pd.DataFrame:
    """Generate hourly counts for several junctions over the same time range.

    One random generator, created from ``seed``, draws the shared noise weeks and the seed
    of every junction, so the same arguments always give the same table. Every week of the
    range draws one calendar week from the weeks that any statistical model can use, and
    each statistical model uses that week if its data covers it, or a random week if not.
    Other models are sampled independently.

    Args:
        models: Fitted models by junction id.
        start: First generated hour.
        end: Hour right after the last generated hour.
        seed: Seed of the random generator.
        scale: Multiplier of the generated volume.

    Returns:
        Integer vehicle counts indexed by hour, one column per junction in the order of
        ``models``.
    """
    index = hourly_range(start, end)
    rng = np.random.default_rng(seed)
    statistical = [model for model in models.values() if isinstance(model, StatisticalCountModel)]
    noise_weeks = None
    if statistical:
        candidates = pd.DatetimeIndex(
            np.unique(np.concatenate([model.noise_week_starts.to_numpy() for model in statistical]))
        )
        week_count = int(np.ceil(len(index) / HOURS_PER_WEEK))
        noise_weeks = candidates[rng.integers(len(candidates), size=week_count)]
    junction_seeds = rng.integers(MAX_SEED, size=len(models))

    counts = {}
    for (junction, model), junction_seed in zip(models.items(), junction_seeds, strict=True):
        seed_value = int(junction_seed)
        if isinstance(model, StatisticalCountModel):
            counts[junction] = model.sample(
                start, end, seed=seed_value, scale=scale, noise_weeks=noise_weeks
            )
        else:
            counts[junction] = model.sample(start, end, seed=seed_value, scale=scale)
    return pd.DataFrame(counts, index=index)

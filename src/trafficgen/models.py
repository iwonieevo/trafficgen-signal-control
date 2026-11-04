"""Layer 1 of the traffic generator: models of hourly vehicle counts per junction.

Each model is fitted on the counts of a single junction and then samples new hourly
counts for any time range. Models know nothing about roads, lanes or other junctions.

Two models are available:

- ``MeanProfileModel``: the baseline, a weekday and hour average with Poisson noise.
- ``StatisticalCountModel``: a decomposition on the log scale with bootstrapped noise.

Sources:

- Hyndman and Athanasopoulos, "Forecasting: Principles and Practice", 3rd edition:
  log transformations and moving average trends (chapter 3,
  https://otexts.com/fpp3/decomposition.html), bootstrapping the remainder of a
  decomposition (chapter 13, https://otexts.com/fpp3/advanced.html).
- Block bootstrap: https://en.wikipedia.org/wiki/Bootstrapping_(statistics)#Block_bootstrap
- Poisson arrivals: https://en.wikipedia.org/wiki/Poisson_point_process
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Self, cast

import numpy as np
import pandas as pd

HOURS_PER_WEEK = 7 * 24

TimeLike = str | datetime | pd.Timestamp


def validate_counts(counts: pd.Series) -> pd.Series:
    """Check that a series holds usable hourly counts.

    Gaps between hours are allowed, as long as the data includes one full week: at least
    168 consecutive hours. Such a week covers every combination of weekday and hour.

    Args:
        counts: Vehicle counts indexed by datetime.

    Returns:
        The counts as floats, sorted by time.

    Raises:
        ValueError: If the index or the values are not valid hourly counts, or if the data
            has no full week.
    """
    if not isinstance(counts.index, pd.DatetimeIndex):
        raise ValueError("counts must be indexed by datetime")
    if counts.index.tz is not None:
        raise ValueError("counts must use naive datetimes")
    if counts.index.has_duplicates:
        raise ValueError("counts have duplicate timestamps")
    if not (counts.index == counts.index.floor("h")).all():
        raise ValueError("counts must be indexed by whole hours")
    if counts.isna().any() or (counts < 0).any():
        raise ValueError("counts must be non-negative numbers")
    counts = counts.astype(float).sort_index()
    if len(_gap_free_starts(counts.asfreq("h"), HOURS_PER_WEEK)) == 0:
        raise ValueError(f"counts need a full week: {HOURS_PER_WEEK} consecutive hours")
    return counts


def hourly_range(start: TimeLike, end: TimeLike) -> pd.DatetimeIndex:
    """Build the hours of a time range, including ``start`` and excluding ``end``.

    Args:
        start: First hour of the range.
        end: Hour right after the last hour of the range.

    Returns:
        One timestamp per hour.

    Raises:
        ValueError: If a bound is not a whole hour or is timezone-aware, or if ``end``
            is not after ``start``.
    """
    first, stop = pd.Timestamp(start), pd.Timestamp(end)
    for bound in (first, stop):
        if bound.tz is not None:
            raise ValueError(f"expected a naive datetime: {bound}")
        if bound != bound.floor("h"):
            raise ValueError(f"expected a whole hour: {bound}")
    if stop <= first:
        raise ValueError(f"end must be after start: {first} to {stop}")
    return pd.date_range(first, stop, freq="h", inclusive="left")


def _gap_free_starts(values: pd.Series, hours: int) -> np.ndarray:
    """Find where a window of consecutive hours has no gaps.

    Args:
        values: Hourly values on a regular index, with NaN in gaps.
        hours: Length of the window.

    Returns:
        Positions where such a window can start.
    """
    present = values.notna().to_numpy()
    if len(present) < hours:
        return np.array([], dtype=int)
    windows = np.lib.stride_tricks.sliding_window_view(present, hours)
    return np.flatnonzero(windows.all(axis=1))


def _weekday_hour_keys(index: pd.DatetimeIndex) -> pd.MultiIndex:
    """Return the (weekday, hour) key of each timestamp."""
    return pd.MultiIndex.from_arrays([index.day_of_week, index.hour], names=["weekday", "hour"])


def _weekly_profile(values: pd.Series) -> pd.Series:
    """Average values per weekday and hour.

    Args:
        values: Values indexed by datetime.

    Returns:
        Average value per (weekday, hour).
    """
    keys = _weekday_hour_keys(pd.DatetimeIndex(values.index))
    return cast(pd.Series, values.groupby(keys).mean())


class HourlyCountModel(ABC):
    """Model of the hourly vehicle counts of one junction."""

    @abstractmethod
    def fit(self, counts: pd.Series) -> Self:
        """Fit the model on the historical counts of one junction.

        Args:
            counts: Vehicle counts indexed by whole hours.

        Returns:
            The fitted model.
        """

    @abstractmethod
    def sample(
        self, start: TimeLike, end: TimeLike, seed: int | None = None, scale: float = 1.0
    ) -> pd.Series:
        """Generate hourly counts for a time range.

        The same arguments always give the same result when ``seed`` is set. Separate
        calls are not continuous: to get one long series, request the whole range at once.

        Args:
            start: First generated hour.
            end: Hour right after the last generated hour.
            seed: Seed of the random generator.
            scale: Multiplier of the generated volume, for example to create more
                congestion in a simulation.

        Returns:
            Integer vehicle counts indexed by hour.
        """


class MeanProfileModel(HourlyCountModel):
    """Baseline model: the average count per weekday and hour, with Poisson noise.

    It ignores growth over time and any dependence between consecutive hours.
    Poisson noise is the textbook assumption of independent vehicle arrivals at a
    constant rate within each hour (https://en.wikipedia.org/wiki/Poisson_point_process).
    """

    def __init__(self) -> None:
        """Create an unfitted model."""
        self.profile_: pd.Series | None = None

    def fit(self, counts: pd.Series) -> Self:
        """Fit the model on the historical counts of one junction.

        Args:
            counts: Vehicle counts indexed by whole hours.

        Returns:
            The fitted model.
        """
        counts = validate_counts(counts)
        self.profile_ = _weekly_profile(counts)
        return self

    def sample(
        self, start: TimeLike, end: TimeLike, seed: int | None = None, scale: float = 1.0
    ) -> pd.Series:
        """Generate hourly counts for a time range. See ``HourlyCountModel.sample``."""
        if self.profile_ is None:
            raise RuntimeError("fit the model before sampling")
        index = hourly_range(start, end)
        rates = self.profile_.reindex(_weekday_hour_keys(index)).to_numpy() * scale
        values = np.random.default_rng(seed).poisson(rates)
        return pd.Series(values, index=index, name="vehicles")


class StatisticalCountModel(HourlyCountModel):
    """Decomposition of log counts into level, weekly profile and noise.

    The model on the ``log(1 + count)`` scale is::

        y[t] = level[t] + profile[weekday, hour] + noise[t]

    Fitting uses these steps:

    1. ``level`` is a centered four week moving average, which removes the weekly cycle.
    2. ``profile`` is the average of the detrended values per weekday and hour.
    3. ``noise`` is what remains. It is kept as it is.

    Sampling draws random one week blocks of the fitted noise (a block bootstrap) and adds
    them to the deterministic part. Blocks keep the persistence of real noise, including
    bursts over several days, without fitting a noise model. Compared with AR models on
    this data, they matched autocorrelation and bursts at least as well with no extra
    parameters.

    Working on the log scale makes noise proportional to volume. This allows both of the
    variance patterns seen in the data: J1 and J2 have a variance below the mean, which a
    Poisson or negative binomial distribution cannot express, and J3 has large bursts.

    Sampling keeps the level inside the fitted period, and holds the first or last level
    outside of it. Growth is not extrapolated, and the time of year is not modelled, since
    less than two years of data cannot separate seasonality from growth.

    See the module docstring for sources.

    Attributes:
        TREND_WINDOW_HOURS: Length of the moving average behind the level. Whole weeks make
            the weekly cycle cancel out.
        NOISE_BLOCK_HOURS: Length of the noise blocks drawn when sampling.
    """

    TREND_WINDOW_HOURS = 4 * HOURS_PER_WEEK
    NOISE_BLOCK_HOURS = HOURS_PER_WEEK

    def __init__(self) -> None:
        """Create an unfitted model."""
        self.level_: pd.Series | None = None
        self.profile_: pd.Series | None = None
        self.noise_: pd.Series | None = None
        self.block_starts_: np.ndarray | None = None

    def fit(self, counts: pd.Series) -> Self:
        """Fit the model on the historical counts of one junction.

        Args:
            counts: Vehicle counts indexed by whole hours.

        Returns:
            The fitted model.

        Raises:
            ValueError: If the counts are invalid.
        """
        counts = validate_counts(counts)
        log_counts = pd.Series(np.log1p(counts.to_numpy()), index=counts.index).asfreq("h")
        index = pd.DatetimeIndex(log_counts.index)

        rolling_mean = log_counts.rolling(
            self.TREND_WINDOW_HOURS, center=True, min_periods=HOURS_PER_WEEK
        ).mean()
        level = cast(pd.Series, rolling_mean).ffill().bfill()
        detrended = log_counts - level

        profile = _weekly_profile(detrended.dropna())
        noise = detrended - profile.reindex(_weekday_hour_keys(index)).to_numpy()

        self.level_ = level
        self.profile_ = profile
        self.noise_ = noise
        self.block_starts_ = _gap_free_starts(noise, self.NOISE_BLOCK_HOURS)
        return self

    def sample(
        self, start: TimeLike, end: TimeLike, seed: int | None = None, scale: float = 1.0
    ) -> pd.Series:
        """Generate hourly counts for a time range. See ``HourlyCountModel.sample``."""
        if (
            self.level_ is None
            or self.profile_ is None
            or self.noise_ is None
            or self.block_starts_ is None
        ):
            raise RuntimeError("fit the model before sampling")
        index = hourly_range(start, end)
        combined = self.level_.reindex(self.level_.index.union(index)).ffill().bfill()
        mean = (
            combined.reindex(index).to_numpy()
            + self.profile_.reindex(_weekday_hour_keys(index)).to_numpy()
        )

        # Join random blocks of the fitted noise until the whole range is covered.
        block_hours = self.NOISE_BLOCK_HOURS
        block_count = int(np.ceil(len(index) / block_hours))
        starts = np.random.default_rng(seed).choice(self.block_starts_, size=block_count)
        fitted_noise = self.noise_.to_numpy()
        blocks = [fitted_noise[first : first + block_hours] for first in starts]
        noise = np.concatenate(blocks)[: len(index)]

        values = np.rint(np.maximum(np.expm1(mean + noise), 0.0) * scale).astype(int)
        return pd.Series(values, index=index, name="vehicles")

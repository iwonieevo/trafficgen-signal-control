"""Layer 1 of the traffic generator: models of hourly vehicle counts per junction.

Each model is fitted on the counts of a single junction and then samples new hourly
counts for any time range. Models know nothing about roads, lanes or other junctions.

Two models are available:

- ``MeanProfileModel``: the baseline, a weekday and hour average with Poisson noise.
- ``StatisticalCountModel``: a decomposition on the log scale with bootstrapped noise.

Sources:

- Hyndman and Athanasopoulos, "Forecasting: Principles and Practice", 3rd edition:
  log transformations and moving average trends (chapter 3,
  https://otexts.com/fpp3/decomposition.html), dummy predictors for holidays (chapter 7,
  https://otexts.com/fpp3/regression.html), bootstrapping the remainder of a
  decomposition (chapter 13, https://otexts.com/fpp3/advanced.html).
- Block bootstrap: https://en.wikipedia.org/wiki/Bootstrapping_(statistics)#Block_bootstrap
- Poisson arrivals: https://en.wikipedia.org/wiki/Poisson_point_process
- Holiday calendars: https://holidays.readthedocs.io/
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Self

import holidays
import numpy as np
import pandas as pd

HOURS_PER_WEEK = 168
TREND_WINDOW_HOURS = 4 * HOURS_PER_WEEK
NOISE_BLOCK_HOURS = HOURS_PER_WEEK

TimeLike = str | datetime | pd.Timestamp


def validate_counts(counts: pd.Series) -> pd.Series:
    """Check that a series holds usable hourly counts.

    Gaps between hours are allowed.

    Args:
        counts: Vehicle counts indexed by datetime.

    Returns:
        The counts as floats, sorted by time.

    Raises:
        ValueError: If the index or the values are not valid hourly counts, or if there
            is less than one week of data.
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
    if len(counts) < HOURS_PER_WEEK:
        raise ValueError(f"at least {HOURS_PER_WEEK} hours of data are required")
    return counts.astype(float).sort_index()


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


def holiday_mask(index: pd.DatetimeIndex, country: str | None) -> np.ndarray:
    """Tell which hours fall on a public holiday.

    Args:
        index: Hours to check.
        country: ISO country code of the holiday calendar, or ``None`` for no holidays.

    Returns:
        Boolean array with one value per hour.
    """
    if country is None:
        return np.zeros(len(index), dtype=bool)
    calendar = holidays.country_holidays(country, years=sorted(set(index.year)))
    return np.fromiter((day.date() in calendar for day in index), dtype=bool, count=len(index))


def _weekday_hour_keys(index: pd.DatetimeIndex) -> pd.MultiIndex:
    """Return the (weekday, hour) key of each timestamp."""
    return pd.MultiIndex.from_arrays([index.day_of_week, index.hour], names=["weekday", "hour"])


def _complete_profile(values: pd.Series, index: pd.DatetimeIndex, fallback: float) -> pd.Series:
    """Average values per weekday and hour, covering all 168 combinations.

    Args:
        values: Values to average, aligned with ``index``.
        index: Timestamps of the values.
        fallback: Value for a combination that the hourly averages cannot fill either.

    Returns:
        Average value per (weekday, hour). A missing combination takes the average of
        its hour, which matters for short histories.
    """
    frame = pd.DataFrame({"value": values.to_numpy()}, index=_weekday_hour_keys(index))
    profile = frame.groupby(level=["weekday", "hour"])["value"].mean()
    by_hour = frame.groupby(level="hour")["value"].mean()
    keys = pd.MultiIndex.from_product([range(7), range(24)], names=["weekday", "hour"])
    profile = profile.reindex(keys)
    missing = profile.isna().to_numpy()
    hours = keys.get_level_values("hour")[missing]
    profile[missing] = by_hour.reindex(hours).fillna(fallback).to_numpy()
    return profile


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

    It ignores growth over time, holidays and any dependence between consecutive hours.
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
        self.profile_ = _complete_profile(counts, counts.index, fallback=float(counts.mean()))
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
    """Decomposition of log counts into level, weekly profile, holidays and noise.

    The model on the ``log(1 + count)`` scale is::

        y[t] = level[t] + profile[weekday, hour] + holiday_effect * is_holiday[t] + noise[t]

    Fitting uses these steps:

    1. ``level`` is a centered four week moving average, which removes the weekly cycle.
    2. ``profile`` is the average of the detrended values per weekday and hour, on
       non-holiday hours.
    3. ``holiday_effect`` is the average remaining difference on holiday hours.
    4. ``noise`` is what remains. It is kept as it is.

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

    Args:
        country: ISO country code of the holiday calendar, or ``None`` for no holidays.
    """

    def __init__(self, country: str | None = "US") -> None:
        """Create an unfitted model."""
        self.country = country
        self.level_: pd.Series | None = None
        self.profile_: pd.Series | None = None
        self.holiday_effect_: float = 0.0
        self.noise_: pd.Series | None = None
        self._block_starts = np.array([], dtype=int)

    def fit(self, counts: pd.Series) -> Self:
        """Fit the model on the historical counts of one junction.

        Args:
            counts: Vehicle counts indexed by whole hours.

        Returns:
            The fitted model.

        Raises:
            ValueError: If the counts are invalid or gaps leave no complete noise block.
        """
        counts = validate_counts(counts)
        log_counts = np.log1p(counts).asfreq("h")
        index = log_counts.index

        level = log_counts.rolling(
            TREND_WINDOW_HOURS, center=True, min_periods=HOURS_PER_WEEK
        ).mean()
        level = level.ffill().bfill()
        detrended = log_counts - level

        is_holiday = holiday_mask(index, self.country)
        regular = detrended.notna().to_numpy() & ~is_holiday
        profile = _complete_profile(detrended[regular], index[regular], fallback=0.0)
        expected = profile.reindex(_weekday_hour_keys(index)).to_numpy()

        holiday_gaps = (detrended - expected)[is_holiday].dropna()
        holiday_effect = float(holiday_gaps.mean()) if len(holiday_gaps) else 0.0

        noise = detrended - expected - holiday_effect * is_holiday
        self._block_starts = self._find_block_starts(noise)
        self.level_ = level
        self.profile_ = profile
        self.holiday_effect_ = holiday_effect
        self.noise_ = noise
        return self

    @staticmethod
    def _find_block_starts(noise: pd.Series) -> np.ndarray:
        """Find the positions where a noise block has no gaps.

        Args:
            noise: Hourly noise on a regular index, with NaN in gaps.

        Returns:
            Start positions of the usable blocks.

        Raises:
            ValueError: If gaps leave no complete block.
        """
        complete = noise.notna().rolling(NOISE_BLOCK_HOURS).sum() == NOISE_BLOCK_HOURS
        starts = np.flatnonzero(complete.to_numpy()) - NOISE_BLOCK_HOURS + 1
        if len(starts) == 0:
            raise ValueError(f"counts need {NOISE_BLOCK_HOURS} consecutive hours without gaps")
        return starts

    def sample(
        self, start: TimeLike, end: TimeLike, seed: int | None = None, scale: float = 1.0
    ) -> pd.Series:
        """Generate hourly counts for a time range. See ``HourlyCountModel.sample``."""
        if self.level_ is None:
            raise RuntimeError("fit the model before sampling")
        index = hourly_range(start, end)
        combined = self.level_.reindex(self.level_.index.union(index)).ffill().bfill()
        mean = (
            combined.reindex(index).to_numpy()
            + self.profile_.reindex(_weekday_hour_keys(index)).to_numpy()
            + self.holiday_effect_ * holiday_mask(index, self.country)
        )
        noise = self._sample_noise(len(index), np.random.default_rng(seed))
        values = np.rint(np.maximum(np.expm1(mean + noise), 0.0) * scale).astype(int)
        return pd.Series(values, index=index, name="vehicles")

    def _sample_noise(self, length: int, rng: np.random.Generator) -> np.ndarray:
        """Draw consecutive random blocks of the fitted noise.

        Args:
            length: Number of hours to return.
            rng: Random generator.

        Returns:
            Noise values for the requested hours.
        """
        block_count = int(np.ceil(length / NOISE_BLOCK_HOURS))
        starts = rng.choice(self._block_starts, size=block_count)
        noise = self.noise_.to_numpy()
        blocks = [noise[first : first + NOISE_BLOCK_HOURS] for first in starts]
        return np.concatenate(blocks)[:length]

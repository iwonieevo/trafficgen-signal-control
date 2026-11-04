"""Compare generated traffic with the real counts it was fitted on.

These checks measure how well generated series reproduce the real data. Because they use
the training data, they show the quality of the fit, not performance on unseen dates.

With thousands of autocorrelated hours, a significance test would flag almost any small
difference, so this module reports the sizes of differences instead of p-values.

Sources:

- Wasserstein distance: https://en.wikipedia.org/wiki/Wasserstein_metric
- Kolmogorov-Smirnov statistic:
  https://en.wikipedia.org/wiki/Kolmogorov%E2%80%93Smirnov_test
"""

from typing import cast

import numpy as np
import pandas as pd

from trafficgen.models import HourlyCountModel

STATISTICS_LAGS = (1, 24, 168)


def sample_many(
    model: HourlyCountModel, index: pd.Index, runs: int, seed: int = 0
) -> pd.DataFrame:
    """Generate several independent series over the same hours.

    Args:
        model: Fitted model.
        index: Hours to generate. They must form a continuous range.
        runs: Number of series.
        seed: Seed of the first series. The next ones use the following integers.

    Returns:
        DataFrame with one column per series.
    """
    start = cast(pd.Timestamp, index[0])
    end = cast(pd.Timestamp, index[-1] + pd.Timedelta(hours=1))
    series = [model.sample(start, end, seed=seed + run) for run in range(runs)]
    return pd.concat(series, axis=1, keys=range(runs)).reindex(index)


def series_statistics(counts: pd.Series) -> dict[str, float]:
    """Summarize one series of hourly counts.

    Args:
        counts: Hourly vehicle counts.

    Returns:
        Mean, spread, quantiles and autocorrelations.
    """
    statistics = {
        "mean": counts.mean(),
        "std": counts.std(),
        "p50": counts.quantile(0.50),
        "p90": counts.quantile(0.90),
        "p99": counts.quantile(0.99),
        "max": counts.max(),
    }
    regular = counts.asfreq("h")
    for lag in STATISTICS_LAGS:
        statistics[f"acf_{lag}h"] = regular.autocorr(lag)
    return {name: float(value) for name, value in statistics.items()}


def statistics_table(real: pd.Series, samples: pd.DataFrame) -> pd.DataFrame:
    """Compare the statistics of the real series with those of the generated ones.

    Args:
        real: Real hourly counts.
        samples: Generated series over the same hours.

    Returns:
        One row per statistic, with the real value, the mean generated value and the
        range covering 90% of the generated series.
    """
    generated = pd.DataFrame([series_statistics(column) for _, column in samples.items()])
    return pd.DataFrame(
        {
            "real": pd.Series(series_statistics(real)),
            "generated": generated.mean(),
            "generated_p05": generated.quantile(0.05),
            "generated_p95": generated.quantile(0.95),
        }
    )


def wasserstein_distance(real: pd.Series, generated: pd.Series) -> float:
    """Compute the Wasserstein distance of two equally long series, in vehicles per hour.

    Args:
        real: Real hourly counts.
        generated: Generated hourly counts.

    Returns:
        The average number of vehicles per hour that must change to turn one
        distribution into the other.
    """
    return float(np.abs(np.sort(real.to_numpy()) - np.sort(generated.to_numpy())).mean())


def ks_statistic(real: pd.Series, generated: pd.Series) -> float:
    """Compute the Kolmogorov-Smirnov statistic of two series.

    Args:
        real: Real hourly counts.
        generated: Generated hourly counts.

    Returns:
        The largest gap between the two cumulative distributions, from 0 to 1.
    """
    a, b = np.sort(real.to_numpy()), np.sort(generated.to_numpy())
    values = np.union1d(a, b)
    gaps = np.searchsorted(a, values, side="right") / len(a) - (
        np.searchsorted(b, values, side="right") / len(b)
    )
    return float(np.abs(gaps).max())


def profile_error(real: pd.Series, generated: pd.Series, keys: str = "weekly") -> float:
    """Compute the relative error of an average profile.

    Args:
        real: Real hourly counts.
        generated: Generated hourly counts.
        keys: ``"daily"`` for 24 hours or ``"weekly"`` for 168 weekday and hour pairs.

    Returns:
        Mean absolute difference of the two profiles divided by the mean real count.
    """

    def profile(counts: pd.Series) -> pd.Series:
        index = pd.DatetimeIndex(counts.index)
        groups = [index.day_of_week, index.hour] if keys == "weekly" else [index.hour]
        return cast(pd.Series, counts.groupby(groups).mean())

    return float((profile(real) - profile(generated)).abs().mean() / real.mean())


def interval_coverage(real: pd.Series, samples: pd.DataFrame, width: float = 0.8) -> float:
    """Compute the share of real hours inside the range of the generated values.

    Args:
        real: Real hourly counts.
        samples: Generated series over the same hours.
        width: Central share of the generated values that forms the range.

    Returns:
        Share of real hours inside the range. It should be close to ``width``.
    """
    low = samples.quantile((1 - width) / 2, axis=1)
    high = samples.quantile((1 + width) / 2, axis=1)
    return float(((real >= low) & (real <= high)).mean())


def realism_scores(real: pd.Series, samples: pd.DataFrame) -> dict[str, float]:
    """Summarize how closely generated series match the real one.

    Args:
        real: Real hourly counts.
        samples: Generated series over the same hours.

    Returns:
        Distribution distances and profile errors averaged over the generated series,
        and the coverage of the 80% range.
    """
    columns = [column for _, column in samples.items()]
    return {
        "wasserstein": float(np.mean([wasserstein_distance(real, c) for c in columns])),
        "ks": float(np.mean([ks_statistic(real, c) for c in columns])),
        "daily_profile_error": float(np.mean([profile_error(real, c, "daily") for c in columns])),
        "weekly_profile_error": float(np.mean([profile_error(real, c, "weekly") for c in columns])),
        "coverage_80": interval_coverage(real, samples),
    }

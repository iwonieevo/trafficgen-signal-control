"""Tests of the comparison between generated and real traffic."""

import numpy as np
import pandas as pd
import pytest

from trafficgen import MeanProfileModel
from trafficgen.validation import (
    interval_coverage,
    ks_statistic,
    profile_error,
    realism_scores,
    sample_many,
    series_statistics,
    statistics_table,
    wasserstein_distance,
)


def test_sample_many_returns_different_series_over_the_same_hours(hourly_counts):
    model = MeanProfileModel().fit(hourly_counts)
    samples = sample_many(model, hourly_counts.index, runs=3)
    assert samples.shape == (len(hourly_counts), 3)
    pd.testing.assert_index_equal(samples.index, hourly_counts.index)
    assert not samples[0].equals(samples[1])


def test_series_statistics_of_a_known_series(hourly_counts):
    constant = pd.Series(5.0, index=hourly_counts.index)
    statistics = series_statistics(constant)
    assert statistics["mean"] == 5
    assert statistics["std"] == 0
    assert statistics["max"] == 5


def test_series_statistics_measures_autocorrelation(hourly_counts):
    statistics = series_statistics(hourly_counts)
    assert statistics["acf_24h"] > 0.5
    assert statistics["acf_168h"] > statistics["acf_24h"] - 0.1


def test_statistics_table_compares_real_and_generated(hourly_counts):
    samples = pd.concat({run: hourly_counts for run in range(3)}, axis=1)
    table = statistics_table(hourly_counts, samples)
    assert list(table.columns) == ["real", "generated", "generated_p05", "generated_p95"]
    assert table.loc["mean", "real"] == pytest.approx(table.loc["mean", "generated"])


def test_wasserstein_distance_is_zero_for_reordered_values(hourly_counts):
    shuffled = hourly_counts.sample(frac=1, random_state=0)
    assert wasserstein_distance(hourly_counts, shuffled) == 0


def test_wasserstein_distance_measures_a_shift(hourly_counts):
    assert wasserstein_distance(hourly_counts, hourly_counts + 3) == pytest.approx(3)


def test_ks_statistic_limits():
    low = pd.Series([1.0, 2.0, 3.0])
    assert ks_statistic(low, low) == 0
    assert ks_statistic(low, low + 100) == 1


def test_ks_statistic_of_a_known_gap():
    real = pd.Series([1.0, 2.0, 3.0, 4.0])
    generated = pd.Series([1.0, 2.0, 5.0, 6.0])
    assert ks_statistic(real, generated) == pytest.approx(0.5)


@pytest.mark.parametrize("keys", ["daily", "weekly"])
def test_profile_error_is_zero_for_identical_series(hourly_counts, keys):
    assert profile_error(hourly_counts, hourly_counts, keys) == 0


@pytest.mark.parametrize("keys", ["daily", "weekly"])
def test_profile_error_is_relative_to_the_mean(hourly_counts, keys):
    constant = pd.Series(10.0, index=hourly_counts.index)
    assert profile_error(constant, constant * 1.5, keys) == pytest.approx(0.5)


def test_weekly_profile_error_sees_what_the_daily_one_cannot(hourly_counts):
    index = hourly_counts.index
    # Weekdays and weekends swap, while the average day stays the same in both series.
    real = pd.Series(np.where(index.day_of_week == 0, 20.0, 10.0), index=index)
    moved = pd.Series(np.where(index.day_of_week == 1, 20.0, 10.0), index=index)
    assert profile_error(real, moved, "daily") == 0
    assert profile_error(real, moved, "weekly") > 0


def test_interval_coverage_counts_real_values_inside_the_range():
    index = pd.date_range("2024-01-01", periods=4, freq="h")
    real = pd.Series([5.0, 5.0, 5.0, 100.0], index=index)
    samples = pd.DataFrame({run: [4.0 + run / 10 * 2] * 4 for run in range(11)}, index=index)
    assert interval_coverage(real, samples, width=0.8) == pytest.approx(0.75)


def test_realism_scores_are_perfect_for_identical_series(hourly_counts):
    samples = pd.concat({run: hourly_counts for run in range(3)}, axis=1)
    scores = realism_scores(hourly_counts, samples)
    assert scores["wasserstein"] == 0
    assert scores["ks"] == 0
    assert scores["daily_profile_error"] == 0
    assert scores["weekly_profile_error"] == 0
    assert scores["coverage_80"] == 1

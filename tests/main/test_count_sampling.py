"""Tests of sampling the counts of several junctions together."""

import numpy as np
import pandas as pd
import pytest

from trafficgen import MeanProfileModel, StatisticalCountModel, sample_junctions

START, END = "2024-03-04", "2024-03-25"


@pytest.fixture
def twin_models(hourly_counts):
    """Two statistical models fitted on the same data, and a baseline."""
    return {
        "A": StatisticalCountModel().fit(hourly_counts),
        "B": StatisticalCountModel().fit(hourly_counts),
        "C": MeanProfileModel().fit(hourly_counts),
    }


def test_columns_follow_the_models_over_the_whole_range(twin_models):
    counts = sample_junctions(twin_models, START, END, seed=1)
    assert list(counts.columns) == ["A", "B", "C"]
    assert len(counts) == 21 * 24
    assert counts.index.name == "datetime"


def test_same_seed_gives_the_same_counts(twin_models):
    pd.testing.assert_frame_equal(
        sample_junctions(twin_models, START, END, seed=3),
        sample_junctions(twin_models, START, END, seed=3),
    )
    assert not sample_junctions(twin_models, START, END, seed=4).equals(
        sample_junctions(twin_models, START, END, seed=3)
    )


def test_statistical_models_use_the_same_noise_weeks(twin_models):
    counts = sample_junctions(twin_models, START, END, seed=5)
    # Same data and same weeks: the same series, although each junction has its own seed.
    np.testing.assert_array_equal(counts["A"].to_numpy(), counts["B"].to_numpy())


def test_scale_multiplies_the_volume(twin_models):
    single = sample_junctions(twin_models, START, END, seed=2)["A"].sum()
    double = sample_junctions(twin_models, START, END, seed=2, scale=2.0)["A"].sum()
    assert double == pytest.approx(2 * single, rel=0.01)


def test_noise_weeks_outside_the_data_fall_back_to_random_weeks(hourly_counts):
    model = StatisticalCountModel().fit(hourly_counts)
    weeks = pd.DatetimeIndex(["1990-01-01", "1990-01-08"])
    with_weeks = model.sample(START, "2024-03-18", seed=7, noise_weeks=weeks)
    pd.testing.assert_series_equal(with_weeks, model.sample(START, "2024-03-18", seed=7))


def test_noise_weeks_must_cover_every_block(hourly_counts):
    model = StatisticalCountModel().fit(hourly_counts)
    with pytest.raises(ValueError, match="expected 2 noise weeks, got 1"):
        model.sample(START, "2024-03-18", noise_weeks=model.noise_week_starts[:1])

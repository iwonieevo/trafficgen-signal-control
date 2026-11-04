"""Tests of the hourly count models."""

import numpy as np
import pandas as pd
import pytest

from trafficgen import MeanProfileModel, StatisticalCountModel
from trafficgen.models import hourly_range, validate_counts

MODELS = [MeanProfileModel, StatisticalCountModel]
START, END = "2024-03-04", "2024-03-18"


def with_changed_value(counts: pd.Series, position: int, value: float) -> pd.Series:
    """Return a copy of the counts with one value replaced."""
    changed = counts.astype(float)
    changed.iloc[position] = value
    return changed


def test_validate_accepts_gaps_next_to_a_full_week(hourly_counts):
    gappy = hourly_counts.iloc[np.r_[0:168, 300:320]]
    assert len(validate_counts(gappy)) == 188


def test_validate_sorts_and_converts_to_float(hourly_counts):
    result = validate_counts(hourly_counts.iloc[::-1])
    assert result.index.is_monotonic_increasing
    assert result.dtype == float


def test_validate_rejects_a_range_index():
    with pytest.raises(ValueError, match="indexed by datetime"):
        validate_counts(pd.Series(range(200)))


def test_validate_rejects_timezones(hourly_counts):
    with pytest.raises(ValueError, match="naive"):
        validate_counts(hourly_counts.tz_localize("UTC"))


def test_validate_rejects_duplicates(hourly_counts):
    with pytest.raises(ValueError, match="duplicate timestamps"):
        validate_counts(hourly_counts.iloc[np.r_[0:len(hourly_counts), 0]])


def test_validate_rejects_partial_hours(hourly_counts):
    with pytest.raises(ValueError, match="whole hours"):
        validate_counts(hourly_counts.set_axis(hourly_counts.index + pd.Timedelta(minutes=30)))


@pytest.mark.parametrize("value", [-1.0, float("nan")])
def test_validate_rejects_invalid_values(hourly_counts, value):
    with pytest.raises(ValueError, match="non-negative"):
        validate_counts(with_changed_value(hourly_counts, 5, value))


@pytest.mark.parametrize(
    "keep",
    [
        pytest.param(np.r_[0:167], id="one hour short"),
        pytest.param(np.r_[0:100, 200:300], id="enough hours but split by a gap"),
    ],
)
def test_validate_requires_a_full_week(hourly_counts, keep):
    with pytest.raises(ValueError, match="full week"):
        validate_counts(hourly_counts.iloc[keep])


def test_hourly_range_excludes_the_end():
    index = hourly_range("2024-01-01 00:00", "2024-01-01 03:00")
    assert list(index.hour) == [0, 1, 2]


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2024-01-01 00:30", "2024-01-02", "whole hour"),
        ("2024-01-01", "2024-01-02 00:30", "whole hour"),
        ("2024-01-02", "2024-01-01", "after start"),
        ("2024-01-01", "2024-01-01", "after start"),
        ("2024-01-01 00:00+00:00", "2024-01-02 00:00+00:00", "naive"),
    ],
)
def test_hourly_range_rejects_invalid_bounds(start, end, message):
    with pytest.raises(ValueError, match=message):
        hourly_range(start, end)


@pytest.mark.parametrize("model_class", MODELS)
def test_fit_returns_the_model(model_class, hourly_counts):
    model = model_class()
    assert model.fit(hourly_counts) is model


@pytest.mark.parametrize("model_class", MODELS)
def test_sample_requires_fit(model_class):
    with pytest.raises(RuntimeError, match="fit"):
        model_class().sample(START, END)


@pytest.mark.parametrize("model_class", MODELS)
def test_sample_covers_exactly_the_requested_hours(model_class, hourly_counts):
    counts = model_class().fit(hourly_counts).sample(START, END, seed=1)
    pd.testing.assert_index_equal(counts.index, hourly_range(START, END), check_names=False)
    assert pd.api.types.is_integer_dtype(counts)
    assert (counts >= 0).all()


@pytest.mark.parametrize("model_class", MODELS)
def test_seed_controls_the_result(model_class, hourly_counts):
    model = model_class().fit(hourly_counts)
    first = model.sample(START, END, seed=1)
    pd.testing.assert_series_equal(first, model.sample(START, END, seed=1))
    assert not first.equals(model.sample(START, END, seed=2))


@pytest.mark.parametrize("model_class", MODELS)
def test_scale_multiplies_the_volume(model_class, hourly_counts):
    model = model_class().fit(hourly_counts)
    regular = model.sample(START, END, seed=1)
    scaled = model.sample(START, END, seed=1, scale=10)
    assert scaled.sum() / regular.sum() == pytest.approx(10, rel=0.05)


@pytest.mark.parametrize("model_class", MODELS)
def test_generated_traffic_keeps_the_weekly_rhythm(model_class, hourly_counts):
    counts = model_class().fit(hourly_counts).sample("2024-01-01", "2024-02-26", seed=1)
    afternoon, night = counts[counts.index.hour == 14], counts[counts.index.hour == 2]
    weekdays, weekends = counts[counts.index.day_of_week < 5], counts[counts.index.day_of_week >= 5]
    assert afternoon.mean() > 2 * night.mean()
    assert weekdays.mean() > 1.5 * weekends.mean()


@pytest.mark.parametrize("model_class", MODELS)
def test_generated_mean_matches_the_data(model_class, hourly_counts):
    counts = model_class().fit(hourly_counts).sample("2024-01-01", "2024-02-26", seed=1)
    assert counts.mean() == pytest.approx(hourly_counts.mean(), rel=0.05)


def test_mean_profile_is_the_average_per_weekday_and_hour(hourly_counts):
    model = MeanProfileModel().fit(hourly_counts)
    index = hourly_counts.index
    monday_noon = hourly_counts[(index.day_of_week == 0) & (index.hour == 12)]
    assert model.profile_ is not None
    assert len(model.profile_) == 168
    assert list(model.profile_.index.names) == ["weekday", "hour"]
    assert model.profile_.loc[(0, 12)] == pytest.approx(monday_noon.mean())


def test_statistical_model_follows_growth_inside_the_data(hourly_counts):
    grown = hourly_counts * np.linspace(1, 4, len(hourly_counts))
    counts = StatisticalCountModel().fit(grown.round()).sample("2024-01-01", "2024-02-26", seed=1)
    assert counts.iloc[-168:].mean() > 2 * counts.iloc[:168].mean()


def test_baseline_ignores_growth(hourly_counts):
    grown = hourly_counts * np.linspace(1, 4, len(hourly_counts))
    counts = MeanProfileModel().fit(grown.round()).sample("2024-01-01", "2024-02-26", seed=1)
    assert counts.iloc[-168:].mean() == pytest.approx(counts.iloc[:168].mean(), rel=0.1)


def test_statistical_level_stays_flat_outside_the_data(hourly_counts):
    model = StatisticalCountModel().fit(hourly_counts)
    # Both ranges start on a Monday, so the same seed must give the same counts.
    near = model.sample("2030-01-07", "2030-01-14", seed=1)
    far = model.sample("2035-01-08", "2035-01-15", seed=1)
    assert near.to_list() == far.to_list()


def test_statistical_level_holds_the_first_value_before_the_data(hourly_counts):
    grown = hourly_counts * np.linspace(1, 4, len(hourly_counts))
    model = StatisticalCountModel().fit(grown.round())
    before = model.sample("2023-01-02", "2023-01-09", seed=1)
    after = model.sample("2030-01-07", "2030-01-14", seed=1)
    assert after.mean() > 2 * before.mean()


def test_sampling_does_not_change_the_fitted_model(hourly_counts):
    model = StatisticalCountModel().fit(hourly_counts)
    assert model.level_ is not None
    level = model.level_.copy()
    model.sample("2030-01-01", "2030-02-01", seed=1)
    pd.testing.assert_series_equal(model.level_, level)


def test_statistical_model_handles_gaps(hourly_counts):
    gappy = hourly_counts.iloc[np.r_[0:300, 400:800]]
    model = StatisticalCountModel().fit(gappy)
    assert model.noise_ is not None and model.block_starts_ is not None
    # Every block that sampling can draw must avoid the gap.
    noise = model.noise_.to_numpy()
    size = model.NOISE_BLOCK_HOURS
    assert all(not np.isnan(noise[first : first + size]).any() for first in model.block_starts_)
    assert len(model.block_starts_) > 0
    assert not model.sample(START, END, seed=1).isna().any()


def test_statistical_model_handles_zero_counts(hourly_counts):
    zeros = hourly_counts * 0
    counts = StatisticalCountModel().fit(zeros).sample(START, END, seed=1)
    assert (counts == 0).all()


def test_statistical_model_accepts_exactly_one_week(hourly_counts):
    counts = StatisticalCountModel().fit(hourly_counts.iloc[:168]).sample(START, END, seed=1)
    assert len(counts) == 14 * 24


def test_noise_blocks_keep_persistence_between_hours():
    index = pd.date_range("2024-01-01", periods=20 * 168, freq="h")
    rng = np.random.default_rng(0)
    persistent = np.zeros(len(index))
    for hour in range(1, len(index)):
        persistent[hour] = 0.8 * persistent[hour - 1] + rng.normal(0, 0.2)
    counts = pd.Series(np.rint(np.exp(4 + persistent)), index=index)

    model = StatisticalCountModel().fit(counts)
    generated = model.sample("2024-01-01", "2024-05-20", seed=1)
    remaining = np.log1p(generated.to_numpy()) - np.log1p(generated.to_numpy()).mean()
    assert np.corrcoef(remaining[:-1], remaining[1:])[0, 1] > 0.6


def test_class_variables_control_the_settings(hourly_counts):
    class ShortWindows(StatisticalCountModel):
        TREND_WINDOW_HOURS = 168
        NOISE_BLOCK_HOURS = 24

    regular = StatisticalCountModel().fit(hourly_counts)
    short = ShortWindows().fit(hourly_counts)
    assert short.block_starts_ is not None and regular.block_starts_ is not None
    assert short.level_ is not None and regular.level_ is not None
    assert len(short.block_starts_) == len(hourly_counts) - 24 + 1
    assert len(regular.block_starts_) == len(hourly_counts) - 168 + 1
    assert short.sample(START, END, seed=1).notna().all()
    assert not short.level_.equals(regular.level_)

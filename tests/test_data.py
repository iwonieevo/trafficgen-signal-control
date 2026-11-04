"""Tests of loading counts from CSV files."""

import pandas as pd
import pytest

from trafficgen import StatisticalCountModel, load_counts


def test_load_counts_reads_and_sorts(tmp_path):
    path = tmp_path / "counts.csv"
    path.write_text("datetime,vehicles\n2024-01-01 01:00:00,7\n2024-01-01 00:00:00,5\n")

    counts = load_counts(path)

    assert counts.to_list() == [5, 7]
    assert counts.index[0] == pd.Timestamp("2024-01-01 00:00:00")
    assert counts.name == "vehicles"


def test_load_counts_ignores_extra_columns(tmp_path):
    path = tmp_path / "counts.csv"
    path.write_text("datetime,vehicles,note\n2024-01-01 00:00:00,5,x\n")
    assert load_counts(path).to_list() == [5]


@pytest.mark.parametrize("header", ["time,vehicles", "datetime,count", "a,b"])
def test_load_counts_requires_both_columns(tmp_path, header):
    path = tmp_path / "counts.csv"
    path.write_text(f"{header}\n2024-01-01 00:00:00,5\n")
    with pytest.raises(ValueError, match="missing columns"):
        load_counts(path)


def test_generated_output_can_be_used_as_input(tmp_path, hourly_counts):
    model = StatisticalCountModel().fit(hourly_counts)
    generated = model.sample("2024-03-04", "2024-04-01", seed=1)
    path = tmp_path / "generated.csv"
    generated.rename_axis("datetime").to_csv(path)

    loaded = load_counts(path)

    assert loaded.to_list() == generated.to_list()
    assert StatisticalCountModel().fit(loaded).sample("2030-01-07", "2030-01-08", seed=1).sum() > 0

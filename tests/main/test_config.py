"""Tests of the shared config file and of the junction counts part of it."""

from pathlib import Path

import pytest

from trafficgen import (
    StatisticalCountModel,
    fit_count_models,
    load_counts_config,
    load_network_config,
)
from trafficgen.config import junction_ids, read_config

CONFIGS_DIR = Path(__file__).parents[2] / "configs"


def write_config(directory: Path, *ids: str, extra: str = "") -> Path:
    """Write a config file with one junction per id, all using data.csv."""
    junctions = "".join(f'[[junctions]]\nid = "{id_}"\ndata = "data.csv"\n\n' for id_ in ids)
    path = directory / "config.toml"
    path.write_text(junctions + extra)
    return path


def test_unknown_sections_are_rejected(tmp_path):
    with pytest.raises(ValueError, match=r"unknown sections \['balance'\]"):
        read_config(write_config(tmp_path, "A", extra="[balance]\nweighting = 'absolute'\n"))


@pytest.mark.parametrize(
    ("tables", "message"),
    [
        ({}, "no junctions"),
        ({"junctions": [{"id": "A"}, {"id": "A"}]}, "duplicate junction ids"),
        ({"junctions": [{"data": "a.csv"}]}, "needs an 'id'"),
    ],
)
def test_junction_ids_are_checked(tables, message):
    with pytest.raises(ValueError, match=message):
        junction_ids(tables)


def test_data_paths_are_relative_to_the_config_file(tmp_path, monkeypatch):
    path = write_config(tmp_path, "A")
    monkeypatch.chdir("/")
    assert load_counts_config(path).junctions[0].data == (tmp_path / "data.csv").resolve()


def test_counts_settings_are_read(tmp_path):
    config = load_counts_config(write_config(tmp_path, "A", "B", extra="[counts]\nscale = 2.5\n"))
    assert config.junction_ids == ["A", "B"]
    assert config.settings.scale == 2.5


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("[counts]\nscale = 0\n", "scale must be positive"),
        ("[counts]\nscael = 2\n", "unknown keys"),
    ],
)
def test_invalid_counts_settings_fail_and_name_the_file(tmp_path, extra, message):
    with pytest.raises(ValueError, match=f"config.toml: .*{message}"):
        load_counts_config(write_config(tmp_path, "A", extra=extra))


def test_junction_needs_data_for_the_counts(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[[junctions]]\nid = "A"\n')
    with pytest.raises(ValueError, match=r"junction 'A' is missing \['data'\]"):
        load_counts_config(path)


@pytest.mark.parametrize("name", ["single_intersection.toml", "grid_2x2.toml"])
def test_both_parts_read_the_shipped_configs(name):
    counts = load_counts_config(CONFIGS_DIR / name)
    network = load_network_config(CONFIGS_DIR / name)
    assert counts.junction_ids == list(network.junction_ids)


def test_fit_count_models_fits_one_model_per_junction(tmp_path, hourly_counts):
    hourly_counts.to_csv(tmp_path / "data.csv")
    models = fit_count_models(load_counts_config(write_config(tmp_path, "A", "B")))

    assert list(models) == ["A", "B"]
    assert all(isinstance(model, StatisticalCountModel) for model in models.values())
    assert models["A"].sample("2024-03-04", "2024-03-05", seed=1).sum() > 0

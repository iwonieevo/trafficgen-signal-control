"""Tests of the config file and of building generators from it."""

import pytest

from trafficgen import StatisticalCountModel, build_generators, load_config


def write_config(directory, *ids):
    """Write a config file with one junction per id, all using data.csv."""
    junctions = "".join(f'[[junctions]]\nid = "{id_}"\ndata = "data.csv"\n\n' for id_ in ids)
    path = directory / "config.toml"
    path.write_text(junctions)
    return path


def test_data_paths_are_relative_to_the_config_file(tmp_path, monkeypatch):
    path = write_config(tmp_path, "A")
    monkeypatch.chdir("/")
    assert load_config(path).junctions[0].data == (tmp_path / "data.csv").resolve()


def test_config_requires_junctions(tmp_path):
    with pytest.raises(ValueError, match="no junctions"):
        load_config(write_config(tmp_path))


def test_config_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_config(write_config(tmp_path, "A", "A"))


def test_build_generators_fits_one_model_per_junction(tmp_path, hourly_counts):
    hourly_counts.to_csv(tmp_path / "data.csv")
    generators = build_generators(load_config(write_config(tmp_path, "A", "B")))

    assert set(generators) == {"A", "B"}
    assert all(isinstance(model, StatisticalCountModel) for model in generators.values())
    assert generators["A"].sample("2024-03-04", "2024-03-05", seed=1).sum() > 0

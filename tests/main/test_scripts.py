"""Tests of the command line scripts, without network access."""

import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from trafficgen import load_counts


def test_split_junctions_writes_one_file_per_junction(tmp_path, monkeypatch, load_script):
    script = load_script("download_kaggle_data")
    monkeypatch.setattr(script, "PROCESSED_DIR", tmp_path / "processed")
    source = tmp_path / "kaggle_traffic.csv"
    source.write_text(
        "DateTime,Junction,Vehicles,ID\n"
        "2024-01-01 00:00:00,1,5,101\n"
        "2024-01-01 00:00:00,2,7,102\n"
        "2024-01-01 01:00:00,1,6,103\n"
    )

    script.split_junctions(source)

    assert sorted(path.name for path in (tmp_path / "processed").iterdir()) == [
        "kaggle_junction_1.csv",
        "kaggle_junction_2.csv",
    ]
    junction_1 = tmp_path / "processed" / "kaggle_junction_1.csv"
    assert junction_1.read_text().splitlines()[0] == "datetime,vehicles"
    assert load_counts(junction_1).to_list() == [5, 6]


@pytest.fixture
def config_path(tmp_path, hourly_counts):
    """Write a config file with one junction and its data."""
    hourly_counts.to_csv(tmp_path / "data.csv")
    path = tmp_path / "config.toml"
    path.write_text('[[junctions]]\nid = "A"\ndata = "data.csv"\n')
    return path


def run_generate(script, monkeypatch, config_path, *arguments):
    """Run the generation script with a fixed time range and the given arguments."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_traffic.py",
            "--config",
            str(config_path),
            "--start",
            "2024-03-04T00:00",
            "--end",
            "2024-03-04T03:00",
            *arguments,
        ],
    )
    script.main()


def test_generate_writes_csv_to_a_new_directory(tmp_path, monkeypatch, load_script, config_path):
    output = tmp_path / "new" / "directory" / "counts.csv"
    script = load_script("generate_traffic")
    run_generate(
        script, monkeypatch, config_path, "--junction", "A", "--seed", "1", "--output", str(output)
    )

    assert len(load_counts(output)) == 3


def test_generate_prints_to_stdout_by_default(monkeypatch, load_script, config_path, capsys):
    script = load_script("generate_traffic")
    run_generate(script, monkeypatch, config_path, "--junction", "A", "--seed", "1")

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "datetime,vehicles"
    assert pd.Timestamp(lines[1].split(",")[0]) == pd.Timestamp("2024-03-04 00:00")


def test_generate_stdout_has_clean_line_endings_when_redirected(config_path):
    script = Path(__file__).parents[2] / "scripts" / "generate_traffic.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config",
            str(config_path),
            "--junction",
            "A",
            "--start",
            "2024-03-04T00:00",
            "--end",
            "2024-03-04T03:00",
        ],
        capture_output=True,
        check=True,
    )
    assert b"\r\r\n" not in result.stdout
    assert len(result.stdout.splitlines()) == 4


def test_generate_rejects_an_unknown_junction(monkeypatch, load_script, config_path):
    script = load_script("generate_traffic")
    with pytest.raises(SystemExit, match="Unknown junction 'B'. Available: A"):
        run_generate(script, monkeypatch, config_path, "--junction", "B")


@pytest.fixture
def network_config_path(tmp_path, hourly_counts):
    hourly_counts.to_csv(tmp_path / "data.csv")
    grid_config = Path(__file__).parents[2] / "configs" / "network_grid_2x2.toml"
    path = tmp_path / "network.toml"
    path.write_text(
        re.sub(r"\.\./data/processed/kaggle_junction_\d\.csv", "data.csv", grid_config.read_text())
    )
    return path


def run_generate_road_demand(monkeypatch, load_script, config_path, output_dir, *arguments):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_road_demand.py",
            "--config",
            str(config_path),
            "--start",
            "2024-03-04T00:00",
            "--end",
            "2024-03-05T00:00",
            "--output-dir",
            str(output_dir),
            *arguments,
        ],
    )
    load_script("generate_road_demand").main()


def test_generate_road_demand_writes_every_output_table(
    tmp_path, monkeypatch, load_script, network_config_path, capsys
):
    output_dir = tmp_path / "new" / "output"
    run_generate_road_demand(
        monkeypatch, load_script, network_config_path, output_dir, "--seed", "1"
    )

    assert sorted(path.name for path in output_dir.iterdir()) == [
        "entry_flows.csv",
        "junction_balance.csv",
        "road_flows.csv",
        "roads.csv",
        "turn_flows.csv",
    ]
    road_flows = pd.read_csv(output_dir / "road_flows.csv")
    assert list(road_flows.columns) == [
        "datetime",
        "road",
        "from_junction",
        "to_junction",
        "kind",
        "vehicles_per_hour",
    ]
    assert len(set(road_flows["datetime"])) == 24
    assert (road_flows["vehicles_per_hour"].to_numpy() >= 0).all()
    assert "wrote" in capsys.readouterr().out


def test_generate_road_demand_is_reproducible_with_a_seed(
    tmp_path, monkeypatch, load_script, network_config_path
):
    for run in ("first", "second"):
        run_generate_road_demand(
            monkeypatch, load_script, network_config_path, tmp_path / run, "--seed", "7"
        )
    first = (tmp_path / "first" / "turn_flows.csv").read_text()
    assert first == (tmp_path / "second" / "turn_flows.csv").read_text()


def test_generate_road_demand_scale_multiplies_the_requested_counts(
    tmp_path, monkeypatch, load_script, network_config_path
):
    for scale in ("1", "2"):
        run_generate_road_demand(
            monkeypatch,
            load_script,
            network_config_path,
            tmp_path / scale,
            "--seed",
            "3",
            "--scale",
            scale,
        )
    single = pd.read_csv(tmp_path / "1" / "junction_balance.csv")["requested"].sum()
    double = pd.read_csv(tmp_path / "2" / "junction_balance.csv")["requested"].sum()
    assert double == pytest.approx(2 * single, rel=0.01)


def test_generate_road_demand_rejects_an_invalid_config(
    tmp_path, monkeypatch, load_script, network_config_path
):
    network_config_path.write_text(
        network_config_path.read_text().replace("ratio = 0.7", "ratio = 0.6", 1)
    )
    with pytest.raises(SystemExit, match="sum to 0.9, not 1"):
        run_generate_road_demand(monkeypatch, load_script, network_config_path, tmp_path / "out")

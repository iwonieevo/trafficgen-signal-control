"""Tests of the command line scripts, without network access."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trafficgen import load_counts, load_junction_counts


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
    """Copy the grid config, with every junction using the same synthetic data."""
    hourly_counts.to_csv(tmp_path / "data.csv")
    grid_config = Path(__file__).parents[2] / "configs" / "grid_2x2.toml"
    text = grid_config.read_text()
    for number in range(1, 5):
        text = text.replace(f"../data/processed/kaggle_junction_{number}.csv", "data.csv")
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def run_script(monkeypatch, load_script, name, *arguments):
    """Run the main function of a script with the given arguments."""
    monkeypatch.setattr(sys, "argv", [f"{name}.py", *arguments])
    load_script(name).main()


def generate_counts(monkeypatch, load_script, config_path, *arguments):
    """Run scripts/generate_counts.py for three hours with the given arguments."""
    run_script(
        monkeypatch,
        load_script,
        "generate_counts",
        "--config",
        str(config_path),
        "--start",
        "2024-03-04T00:00",
        "--end",
        "2024-03-04T03:00",
        *arguments,
    )


def test_generate_counts_writes_every_junction_to_a_new_directory(
    tmp_path, monkeypatch, load_script, config_path
):
    output = tmp_path / "new" / "directory" / "counts.csv"
    generate_counts(monkeypatch, load_script, config_path, "--seed", "1", "--output", str(output))

    counts = load_junction_counts(output)
    assert list(counts.columns) == ["J1", "J2", "J3", "J4"]
    assert len(counts) == 3


def test_generate_counts_prints_to_stdout_by_default(monkeypatch, load_script, config_path, capsys):
    generate_counts(monkeypatch, load_script, config_path, "--junction", "J2", "--seed", "1")

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "datetime,J2"
    assert pd.Timestamp(lines[1].split(",")[0]) == pd.Timestamp("2024-03-04 00:00")


def test_selected_junctions_match_the_full_output(tmp_path, monkeypatch, load_script, config_path):
    generate_counts(
        monkeypatch, load_script, config_path, "--seed", "4", "--output", str(tmp_path / "all.csv")
    )
    generate_counts(
        monkeypatch,
        load_script,
        config_path,
        "--seed",
        "4",
        "--junction",
        "J3",
        "--output",
        str(tmp_path / "j3.csv"),
    )
    pd.testing.assert_frame_equal(
        load_junction_counts(tmp_path / "j3.csv"),
        load_junction_counts(tmp_path / "all.csv")[["J3"]],
    )


def test_generate_counts_stdout_has_clean_line_endings_when_redirected(config_path):
    script = Path(__file__).parents[2] / "scripts" / "generate_counts.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config",
            str(config_path),
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


def test_generate_counts_rejects_an_unknown_junction(monkeypatch, load_script, config_path):
    with pytest.raises(SystemExit, match="Unknown junction 'X'. Available: J1, J2, J3, J4"):
        generate_counts(monkeypatch, load_script, config_path, "--junction", "X")


@pytest.fixture
def counts_path(tmp_path):
    """Write a day of counts for the four junctions of the grid."""
    rng = np.random.default_rng(0)
    index = pd.date_range("2024-03-04", periods=24, freq="h", name="datetime")
    counts = pd.DataFrame(
        rng.integers(0, 100, size=(24, 4)), index=index, columns=["J1", "J2", "J3", "J4"]
    )
    path = tmp_path / "counts.csv"
    counts.to_csv(path)
    return path


def generate_flows(monkeypatch, load_script, config_path, counts_path, output_dir):
    """Run scripts/generate_flows.py."""
    run_script(
        monkeypatch,
        load_script,
        "generate_flows",
        "--config",
        str(config_path),
        "--counts",
        str(counts_path),
        "--output-dir",
        str(output_dir),
    )


def test_generate_flows_writes_every_output_table(
    tmp_path, monkeypatch, load_script, config_path, counts_path, capsys
):
    output_dir = tmp_path / "new" / "output"
    generate_flows(monkeypatch, load_script, config_path, counts_path, output_dir)

    assert sorted(path.name for path in output_dir.iterdir()) == [
        "entry_flows.csv",
        "junction_balance.csv",
        "road_flows.csv",
        "roads.csv",
        "turn_flows.csv",
    ]
    balance = pd.read_csv(output_dir / "junction_balance.csv")
    assert balance["datetime"].nunique() == 24
    assert balance["difference"].abs().max() < 1e-6
    assert "wrote" in capsys.readouterr().out


def test_generate_flows_is_deterministic(
    tmp_path, monkeypatch, load_script, config_path, counts_path
):
    for run in ("first", "second"):
        generate_flows(monkeypatch, load_script, config_path, counts_path, tmp_path / run)
    first = (tmp_path / "first" / "turn_flows.csv").read_text()
    assert first == (tmp_path / "second" / "turn_flows.csv").read_text()


def test_generate_flows_rejects_counts_without_a_junction(
    tmp_path, monkeypatch, load_script, config_path, counts_path
):
    counts = pd.read_csv(counts_path).drop(columns="J4")
    counts.to_csv(counts_path, index=False)
    with pytest.raises(SystemExit, match=r"no column for junctions \['J4'\]"):
        generate_flows(monkeypatch, load_script, config_path, counts_path, tmp_path / "out")


def test_generate_flows_rejects_an_invalid_config(
    tmp_path, monkeypatch, load_script, config_path, counts_path
):
    config_path.write_text(
        config_path.read_text().replace("preference = 0.7", "preference = -1", 1)
    )
    with pytest.raises(SystemExit, match="preference must not be negative"):
        generate_flows(monkeypatch, load_script, config_path, counts_path, tmp_path / "out")

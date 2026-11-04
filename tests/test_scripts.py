"""Tests of the command line scripts, without network access."""

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


def test_generate_writes_csv_to_a_new_directory(
    tmp_path, monkeypatch, load_script, config_path
):
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
    script = Path(__file__).parent.parent / "scripts" / "generate_traffic.py"
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

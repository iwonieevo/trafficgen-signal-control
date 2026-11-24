"""Generated traffic in the real SUMO simulator: routes, a whole run and its accuracy.

Accuracy is measured as the vehicles that enter each junction in each hour of the
simulation, compared with the requested junction counts.
"""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

from trafficgen import (
    GeneratedTraffic,
    find_sumo_program,
    generate_traffic,
    load_network_config,
    traffic_from_counts,
)

REPO_ROOT = Path(__file__).parents[2]
START, END = "2024-03-04T06:00", "2024-03-04T10:00"


def simulate(run: GeneratedTraffic, directory: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    """Run SUMO on a generated run and count the vehicles entering each junction per hour.

    Args:
        run: The generated run.
        directory: Directory for the measurement files.

    Returns:
        Vehicles per hour and junction, in the shape of the counts, and the vehicle and
        teleport statistics of SUMO.
    """
    edge_data = directory / "edge_data.xml"
    additional = directory / "measure.add.xml"
    additional.write_text(
        f'<additional><edgeData id="hourly" period="3600" file="{edge_data.as_posix()}"/>'
        "</additional>"
    )
    statistics_file = directory / "statistics.xml"
    command = [
        find_sumo_program("sumo"),
        "-c", str(run.sumo.config_file),
        "--additional-files", str(additional),
        "--statistic-output", str(statistics_file),
        "--no-step-log",
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    statistics = ET.parse(statistics_file).getroot()
    numbers = {
        f"vehicles_{key}": int(value)
        for key, value in statistics.find("vehicles").attrib.items()  # pyright: ignore[reportOptionalMemberAccess]
    }
    numbers["teleports"] = int(statistics.find("teleports").get("total", "0"))  # pyright: ignore[reportOptionalMemberAccess]

    junction_of_road = run.flows.roads.set_index("road")["to_junction"].dropna()
    rows = [
        (float(interval.get("begin", "0")), edge.get("id"), int(edge.get("left", "0")))
        for interval in ET.parse(edge_data).getroot().iter("interval")
        for edge in interval.iter("edge")
        if edge.get("id") in junction_of_road.index
    ]
    table = pd.DataFrame(rows, columns=["begin", "road", "vehicles"])
    table["junction"] = table["road"].map(junction_of_road)
    simulated = table.pivot_table(
        index="begin", columns="junction", values="vehicles", aggfunc="sum"
    )
    simulated.index = run.counts.index[0] + pd.to_timedelta(simulated.index, unit="s")
    simulated = simulated.reindex(index=run.counts.index, columns=run.counts.columns)
    return simulated.fillna(0), numbers


def vehicles(route_file: Path) -> list[tuple[str, str, str]]:
    """Id, departure time and route of every vehicle of a route file."""
    return [
        (vehicle.get("id", ""), vehicle.get("depart", ""), vehicle.find("route").get("edges", ""))  # pyright: ignore[reportOptionalMemberAccess]
        for vehicle in ET.parse(route_file).getroot().iter("vehicle")
    ]


def with_uniform_departures(config_path: Path) -> Path:
    config_path.write_text(config_path.read_text().replace('"poisson"', '"uniform"'))
    return config_path


@pytest.fixture
def grid_run(tmp_path, grid_config_path) -> GeneratedTraffic:
    """Four hours of generated traffic on the grid, with random departures."""
    return generate_traffic(grid_config_path, START, END, tmp_path / "run", seed=7)


def test_run_writes_counts_flows_and_sumo_input(grid_run):
    directory = grid_run.output_dir
    assert (directory / "counts.csv").is_file()
    assert len(list((directory / "flows").glob("*.csv"))) == 5
    for path in (grid_run.sumo.route_file, grid_run.sumo.config_file):
        assert path.is_file()
    assert grid_run.sumo.end_s == 4 * 3600
    run_info = json.loads((directory / "run.json").read_text())
    assert run_info["seed"] == 7
    assert run_info["vehicles"] == grid_run.sumo.vehicles > 0


def test_every_route_goes_from_an_entry_to_an_exit_over_connected_roads(grid_run, grid_config_path):
    network = load_network_config(grid_config_path)
    kinds = {road.id: road.kind for road in network.roads}
    turns = {(turn.from_road, turn.to_road) for turn in network.turns}

    for vehicle_id, depart, route in vehicles(grid_run.sumo.route_file):
        edges = route.split()
        assert kinds[edges[0]] == "entry", vehicle_id
        assert kinds[edges[-1]] == "exit", vehicle_id
        assert all((a, b) in turns for a, b in zip(edges, edges[1:], strict=False)), vehicle_id
        assert 0 <= float(depart) < grid_run.sumo.end_s


def test_same_seed_gives_the_same_vehicles(tmp_path, grid_config_path, grid_run):
    again = generate_traffic(grid_config_path, START, END, tmp_path / "again", seed=7)
    other = generate_traffic(grid_config_path, START, END, tmp_path / "other", seed=8)
    assert vehicles(again.sumo.route_file) == vehicles(grid_run.sumo.route_file)
    assert vehicles(other.sumo.route_file) != vehicles(grid_run.sumo.route_file)


def test_generated_run_runs_in_sumo(tmp_path, grid_run):
    simulated, numbers = simulate(grid_run, tmp_path)

    assert numbers["vehicles_loaded"] == grid_run.sumo.vehicles
    assert numbers["vehicles_inserted"] == grid_run.sumo.vehicles
    assert numbers["vehicles_running"] == numbers["vehicles_waiting"] == 0
    assert numbers["teleports"] == 0
    # Random departures and turns on a few hours: totals follow the counts, but not exactly.
    total_ratio = simulated.to_numpy().sum() / grid_run.counts.to_numpy().sum()
    assert 0.9 <= total_ratio <= 1.1
    ratio = simulated.sum() / grid_run.counts.sum()
    assert ratio.between(0.7, 1.3).all(), ratio


def test_simulated_junction_traffic_matches_different_counts(tmp_path, grid_config_path):
    config = with_uniform_departures(grid_config_path)
    hours = pd.date_range(START, periods=6, freq="h", name="datetime")
    counts = pd.DataFrame(
        {
            "J1": [400, 450, 500, 450, 400, 350],
            "J2": [150, 200, 250, 200, 150, 100],
            "J3": [200, 200, 150, 150, 200, 200],
            "J4": [80, 120, 160, 120, 80, 60],
        },
        index=hours,
        dtype=float,
    )
    run = traffic_from_counts(config, counts, tmp_path / "run", seed=1)
    assert len(run.flows.adjusted_hours) > 0
    simulated, numbers = simulate(run, tmp_path)

    assert numbers["teleports"] == 0
    total_ratio = simulated.sum() / counts.sum()
    assert total_ratio.between(0.95, 1.05).all(), total_ratio
    hourly_ratio = simulated / counts
    assert ((hourly_ratio >= 0.8) & (hourly_ratio <= 1.2)).to_numpy().all(), hourly_ratio


def test_single_intersection_gets_every_requested_vehicle(tmp_path, scenario_config):
    config = with_uniform_departures(scenario_config("single-intersection"))
    run = generate_traffic(config, START, END, tmp_path / "run", seed=3, scale=3.0)
    simulated, numbers = simulate(run, tmp_path)

    assert numbers["teleports"] == 0
    # Every vehicle passes the junction once. Only the rounding to whole vehicles per entry
    # road, and vehicles crossing an hour boundary on the way, make a difference.
    assert abs(simulated["J1"].sum() - run.counts["J1"].sum()) <= 4
    assert (simulated["J1"] - run.counts["J1"]).abs().max() <= 3


def test_scripts_generate_and_run_traffic(tmp_path, grid_config_path):
    output_dir = tmp_path / "run"
    generate = [
        sys.executable, str(REPO_ROOT / "scripts" / "generate_traffic.py"),
        "--config", str(grid_config_path),
        "--start", START, "--end", END,
        "--seed", "5",
        "--output-dir", str(output_dir),
    ]  # fmt: skip
    result = subprocess.run(generate, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "run it with: uv run python scripts/run_sumo.py" in result.stdout

    from_counts = [
        sys.executable, str(REPO_ROOT / "scripts" / "generate_traffic.py"),
        "--config", str(grid_config_path),
        "--counts", str(output_dir / "counts.csv"),
        "--seed", "5",
        "--output-dir", str(tmp_path / "from_counts"),
    ]  # fmt: skip
    result = subprocess.run(from_counts, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert vehicles(tmp_path / "from_counts" / "sumo" / "routes.rou.xml") == vehicles(
        output_dir / "sumo" / "routes.rou.xml"
    )

    run_sumo = [
        sys.executable, str(REPO_ROOT / "scripts" / "run_sumo.py"),
        str(output_dir / "sumo" / "run.sumocfg"),
    ]  # fmt: skip
    result = subprocess.run(run_sumo, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

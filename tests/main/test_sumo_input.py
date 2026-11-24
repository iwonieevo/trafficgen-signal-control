"""Tests of the SUMO input files and their config, without running SUMO."""

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trafficgen import (
    FlowSolver,
    fit_count_models,
    generate_traffic,
    load_counts_config,
    load_network_config,
    load_sumo_config,
    sample_junctions,
    traffic_from_counts,
)
from trafficgen.simulation.files import write_entry_flows, write_sumo_config, write_turn_ratios

START = pd.Timestamp("2024-03-04")


def entry_flows(vehicles_per_hour: dict[str, list[float]]) -> pd.DataFrame:
    """An ``entry_flows`` table with the given flows per road and hour."""
    rows = [
        {"datetime": START + pd.Timedelta(hours=hour), "road": road, "vehicles_per_hour": value}
        for road, values in vehicles_per_hour.items()
        for hour, value in enumerate(values)
    ]
    return pd.DataFrame(rows)


def flow_elements(path: Path) -> list[dict[str, str]]:
    return [flow.attrib for flow in ET.parse(path).getroot().iter("flow")]


POISSON = '[sumo]\ndepartures = "poisson"\n'


def test_sumo_config_defaults_to_random_departures(grid_config_path):
    grid_config_path.write_text(grid_config_path.read_text().replace(POISSON, ""))
    config = load_sumo_config(grid_config_path)
    assert config.net_file.name == "grid.net.xml"
    assert config.net_file.is_absolute()
    assert config.settings.departures == "poisson"


def test_sumo_section_sets_the_departures(grid_config_path):
    grid_config_path.write_text(grid_config_path.read_text().replace("poisson", "uniform"))
    assert load_sumo_config(grid_config_path).settings.departures == "uniform"


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ('[sumo]\ndepartures = "random"\n', "departures must be one of"),
        ("[sumo]\nvehicle_types = 2\n", "unknown keys"),
    ],
)
def test_invalid_sumo_section_fails(grid_config_path, section, message):
    grid_config_path.write_text(grid_config_path.read_text().replace(POISSON, section))
    with pytest.raises(ValueError, match=message):
        load_sumo_config(grid_config_path)


def test_sumo_input_needs_a_network_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[[junctions]]\nid = "A"\n')
    with pytest.raises(ValueError, match=r"needs the network file in a \[network\] section"):
        load_sumo_config(path)


def test_random_departures_have_the_rate_of_each_hour(tmp_path):
    path = tmp_path / "flows.xml"
    write_entry_flows(
        entry_flows({"in": [36.0, 72.0], "quiet": [0.001, 0.0]}), START, path, "poisson"
    )

    flows = flow_elements(path)
    assert [(flow["from"], flow["begin"], flow["end"]) for flow in flows] == [
        ("in", "0", "3600"),
        ("in", "3600", "7200"),
    ]
    assert [flow["period"] for flow in flows] == ["exp(0.01)", "exp(0.02)"]
    assert flows[0]["departLane"] == "best"


def test_uniform_departures_carry_fractions_over_to_the_next_hour(tmp_path):
    path = tmp_path / "flows.xml"
    write_entry_flows(entry_flows({"in": [1.4] * 5, "other": [0.2] * 5}), START, path, "uniform")

    numbers = {(flow["from"], flow["begin"]): int(flow["number"]) for flow in flow_elements(path)}
    assert [numbers[("in", str(hour * 3600))] for hour in range(5)] == [1, 2, 1, 2, 1]
    # 0.2 per hour adds up to one vehicle in the third hour.
    assert [key for key in numbers if key[0] == "other"] == [("other", "7200")]


def test_turn_ratios_follow_the_used_shares_of_every_hour(tmp_path, grid_config_path):
    network = load_network_config(grid_config_path)
    counts = pd.DataFrame(
        {"J1": [120.0, 80.0], "J2": [30.0, 60.0], "J3": [40.0, 20.0], "J4": [10.0, 30.0]},
        index=pd.date_range(START, periods=2, freq="h", name="datetime"),
    )
    flows = FlowSolver(network).solve(counts)
    path = tmp_path / "turns.xml"
    write_turn_ratios(flows.turn_flows, START, path)

    intervals = list(ET.parse(path).getroot().iter("interval"))
    assert [(interval.get("begin"), interval.get("end")) for interval in intervals] == [
        ("0", "3600"),
        ("3600", "7200"),
    ]
    for interval, (_, hour) in zip(intervals, flows.turn_flows.groupby("datetime"), strict=True):
        relations = interval.findall("edgeRelation")
        assert len(relations) == len(network.turns)
        written = {(r.get("from"), r.get("to")): float(r.get("probability", "")) for r in relations}
        used = dict(
            zip(zip(hour["from_road"], hour["to_road"], strict=True), hour["share"], strict=True)
        )
        assert written == pytest.approx(used, abs=1e-7)
        per_road = pd.Series(written).groupby(level=0).sum()
        np.testing.assert_allclose(per_road.to_numpy(), 1.0, atol=1e-6)


def test_sumo_config_points_at_the_network_and_routes(tmp_path):
    scenario = tmp_path / "scenario"
    net_file = scenario / "net.net.xml"
    route_file = scenario / "runs" / "one" / "sumo" / "routes.rou.xml"
    route_file.parent.mkdir(parents=True)
    net_file.touch()
    route_file.touch()
    config = route_file.parent / "run.sumocfg"
    write_sumo_config(config, net_file, route_file)

    inputs = {option.tag: option.get("value") for option in ET.parse(config).getroot()[0]}
    assert inputs == {"net-file": "../../../net.net.xml", "route-files": "routes.rou.xml"}
    assert (config.parent / inputs["net-file"]).resolve() == net_file.resolve()


def test_sampled_counts_are_met_by_the_network_flows(grid_config_path):
    models = fit_count_models(load_counts_config(grid_config_path))
    counts = sample_junctions(models, "2024-03-04", "2024-03-06", seed=1)
    counts["J1"] *= 3  # Different counts per junction, so that shares must be adjusted.
    flows = FlowSolver(load_network_config(grid_config_path)).solve(counts)

    achieved = flows.junction_balance.pivot(index="datetime", columns="junction", values="achieved")
    np.testing.assert_allclose(achieved[counts.columns].to_numpy(), counts.to_numpy(), atol=1e-6)
    assert flows.unbalanced_hours.empty


def test_through_share_below_one_is_rejected_before_anything_is_generated(
    tmp_path, grid_config_path
):
    grid_config_path.write_text(
        grid_config_path.read_text() + '\n[[roads]]\nid = "A0B0"\nthrough_share = 0.9\n'
    )
    with pytest.raises(ValueError, match=r"roads \['A0B0'\] have through_share < 1"):
        generate_traffic(grid_config_path, "2024-03-04", "2024-03-05", tmp_path / "run")
    counts = pd.DataFrame({"J1": [1.0]}, index=pd.DatetimeIndex([START], name="datetime"))
    with pytest.raises(ValueError, match="through_share < 1"):
        traffic_from_counts(grid_config_path, counts, tmp_path / "run")
    assert not (tmp_path / "run").exists()

"""Tests of the tuning of fixed-time signal programs, without SUMO."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

import pytest

GRID_NET = Path(__file__).parents[2] / "scenarios" / "grid-2x2" / "grid.net.xml"


@pytest.fixture
def tuning(load_script) -> ModuleType:
    """Import the tuning script as a module."""
    return load_script("tune_fixed_time")


@pytest.fixture
def programs(tuning):
    """The programs of the grid network."""
    return tuning.read_programs(GRID_NET)


def flows_into_a0(vehicles_per_hour: float) -> dict[str, float]:
    """The same flow on the two entry roads of A0, which use different phases."""
    return {"bottom0A0": vehicles_per_hour, "left0A0": vehicles_per_hour}


def greens(program) -> list[int]:
    return [phase.duration for phase in program.phases if phase.approaches]


def test_programs_are_read_with_the_approaches_of_every_green_phase(programs):
    assert [program.junction for program in programs] == ["A0", "A1", "B0", "B1"]
    a0 = programs[0]
    assert a0.cycle == 90
    assert [phase.approaches for phase in a0.phases] == [
        {"A1A0": 1, "bottom0A0": 1},
        {},
        {"B0A0": 1, "left0A0": 1},
        {},
    ]


def test_design_hour_is_the_busiest_hour(tuning, tmp_path):
    path = tmp_path / "turn_flows.csv"
    path.write_text(
        "datetime,junction,from_road,to_road,preferred_share,share,vehicles_per_hour\n"
        "2024-03-04 07:00:00,J1,left0A0,A0B0,0.7,0.7,70\n"
        "2024-03-04 08:00:00,J1,left0A0,A0B0,0.7,0.7,140\n"
        "2024-03-04 08:00:00,J1,left0A0,A0A1,0.3,0.3,60\n"
        "2024-03-04 08:00:00,J1,bottom0A0,A0A1,1.0,1.0,50\n"
    )

    assert tuning.design_flows(path) == (
        "2024-03-04 08:00:00",
        {"bottom0A0": 50.0, "left0A0": 200.0},
    )
    assert tuning.design_flows(path, "2024-03-04 07:00:00")[1] == {"left0A0": 70.0}
    with pytest.raises(ValueError, match="no hour"):
        tuning.design_flows(path, "2024-03-04 09:00:00")


def test_flow_ratio_of_a_phase_is_that_of_its_busiest_approach(tuning, programs):
    flows = {"A1A0": 100.0, "bottom0A0": 400.0, "left0A0": 200.0}
    ratios = tuning.flow_ratios(programs[0], flows, saturation_flow=1600)
    assert ratios == pytest.approx([0.25, 0.125])


def test_cycle_follows_the_formula_of_webster(tuning, programs):
    # Y = 2 * 0.4 and L = 2 * 3 s: (1.5 * 6 + 5) / (1 - 0.8) = 70 s.
    cycle = tuning.webster_cycle(
        programs, flows_into_a0(640), saturation_flow=1600, lost_time=3, max_cycle=120
    )
    assert cycle == 70


def test_cycle_stays_between_the_minimum_greens_and_the_maximum(tuning, programs):
    # Two greens of 8 s and two yellows of 3 s.
    assert tuning.webster_cycle(programs, {}, min_green=8) == 22
    assert tuning.webster_cycle(programs, flows_into_a0(780), max_cycle=120) == 120
    # At a flow ratio sum of 1 or more the formula has no answer.
    assert tuning.webster_cycle(programs, flows_into_a0(2000), max_cycle=120) == 120


def test_green_time_is_split_by_flow_ratio(tuning, programs):
    program = tuning.retime(programs[0], {"bottom0A0": 600.0, "left0A0": 300.0}, cycle=66)

    assert greens(program) == [40, 20]
    assert program.cycle == 66
    assert [phase.state for phase in program.phases] == [
        phase.state for phase in programs[0].phases
    ]
    assert [phase.duration for phase in program.phases if not phase.approaches] == [3, 3]


def test_every_phase_gets_at_least_the_minimum_green(tuning, programs):
    assert greens(tuning.retime(programs[0], {"bottom0A0": 600.0}, cycle=66, min_green=8)) == [
        52,
        8,
    ]
    assert greens(tuning.retime(programs[0], {}, cycle=37)) == [16, 15]
    with pytest.raises(ValueError, match="too short for A0"):
        tuning.retime(programs[0], {}, cycle=21, min_green=8)


def test_all_junctions_get_the_cycle_of_the_busiest_one(tuning, programs):
    tuned = tuning.tune(programs, flows_into_a0(640), saturation_flow=1600, lost_time=3)

    assert {program.cycle for program in tuned} == {70}
    assert greens(tuned[0]) == [32, 32]
    # A junction without traffic splits the green equally.
    assert greens(tuned[3]) == [32, 32]


def test_script_writes_programs_for_a_run(tuning, monkeypatch, tmp_path, capsys):
    run = tmp_path / "run"
    (run / "sumo").mkdir(parents=True)
    (run / "flows").mkdir()
    (run / "sumo" / "run.sumocfg").write_text(
        f'<configuration><input><net-file value="{GRID_NET.as_posix()}"/>'
        '<route-files value="routes.rou.xml"/></input></configuration>'
    )
    (run / "flows" / "turn_flows.csv").write_text(
        "datetime,junction,from_road,to_road,preferred_share,share,vehicles_per_hour\n"
        "2024-03-04 08:00:00,J1,left0A0,A0B0,1.0,1.0,600\n"
        "2024-03-04 08:00:00,J1,bottom0A0,A0A1,1.0,1.0,300\n"
        "2024-03-04 08:00:00,J2,A0B0,B0right0,1.0,1.0,600\n"
    )
    output = tmp_path / "tls.test.add.xml"
    arguments = [str(run), "--name", "test", "--output", str(output), "--no-offsets"]
    monkeypatch.setattr(sys, "argv", ["tune_fixed_time.py", *arguments])

    tuning.main()

    assert "design hour 2024-03-04 08:00:00" in capsys.readouterr().out
    logics = {logic.attrib["id"]: logic for logic in ET.parse(output).getroot().iter("tlLogic")}
    assert sorted(logics) == ["A0", "A1", "B0", "B1"]
    for logic in logics.values():
        assert logic.attrib["programID"] == "test"
        assert logic.attrib["offset"] == "0"
    durations = {
        junction: [int(phase.attrib["duration"]) for phase in logic.iter("phase")]
        for junction, logic in logics.items()
    }
    assert len({sum(phases) for phases in durations.values()}) == 1
    # West and east have twice the flow of north and south at A0, and all of it at B0.
    north_south, _, west_east, _ = durations["A0"]
    assert west_east > north_south
    assert durations["B0"][0] == 8


def test_script_rejects_a_directory_that_is_not_a_run(tuning, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["tune_fixed_time.py", str(tmp_path), "--name", "test"])
    with pytest.raises(SystemExit, match="Not a run of the traffic generator"):
        tuning.main()

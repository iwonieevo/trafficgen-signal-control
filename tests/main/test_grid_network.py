"""Check what other parts rely on in the grid-2x2 network, without running SUMO.

The traffic generator places its flows by node and edge id, and reads the turns from the
connections. An RL environment gets one agent per traffic light. A rebuilt network or an
edited signal program must keep all of this.
"""

import tomllib
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import pytest

SCENARIO_DIR = Path(__file__).parents[2] / "scenarios" / "grid-2x2"
MIN_YELLOW_S = 3.0
FIXED_TIME_FILES = sorted(SCENARIO_DIR.glob("tls.fixed-*.add.xml"))

# Signalized nodes, each with the nodes it is connected to in both directions.
NEIGHBOURS = {
    "A0": ("A1", "B0", "bottom0", "left0"),
    "A1": ("A0", "B1", "left1", "top0"),
    "B0": ("A0", "B1", "bottom1", "right0"),
    "B1": ("A1", "B0", "right1", "top1"),
}
BOUNDARY_NODES = sorted({node for nodes in NEIGHBOURS.values() for node in nodes} - set(NEIGHBOURS))
# Edge ids join the ids of the start and the end node.
EDGES = {
    f"{start}{end}": (start, end)
    for junction, neighbours in NEIGHBOURS.items()
    for neighbour in neighbours
    for start, end in ((junction, neighbour), (neighbour, junction))
}


@pytest.fixture(scope="module")
def network() -> ET.Element:
    """Root of the network file of the scenario."""
    return ET.parse(SCENARIO_DIR / "grid.net.xml").getroot()


def test_nodes_keep_their_ids_and_types(network):
    types = {
        node.get("id"): node.get("type")
        for node in network.iter("junction")
        if node.get("type") != "internal"
    }
    assert types == dict.fromkeys(NEIGHBOURS, "traffic_light") | dict.fromkeys(
        BOUNDARY_NODES, "dead_end"
    )


def test_edges_keep_their_ids(network):
    edges = {
        edge.get("id"): (edge.get("from"), edge.get("to"))
        for edge in network.iter("edge")
        if edge.get("function") != "internal"
    }
    assert len(EDGES) == 24
    assert edges == EDGES


def test_every_approach_turns_right_straight_and_left_only(network):
    direction_by_target_by_edge: dict[str, dict[str, str]] = defaultdict(dict)
    for connection in network.iter("connection"):
        if connection.attrib["from"] in EDGES:
            target, direction = connection.attrib["to"], connection.attrib["dir"]
            # No U-turns: the network is built with --no-turnarounds.
            assert direction != "t", connection.attrib
            direction_by_target_by_edge[connection.attrib["from"]][target] = direction

    approaches = sorted(edge for edge, (_, end) in EDGES.items() if end in NEIGHBOURS)
    assert sorted(direction_by_target_by_edge) == approaches
    for edge, direction_by_target in direction_by_target_by_edge.items():
        assert sorted(direction_by_target.values()) == ["l", "r", "s"], edge


def test_every_junction_has_one_signal_program_for_all_its_connections(network):
    links_by_light: dict[str, set[int]] = defaultdict(set)
    for connection in network.iter("connection"):
        if "tl" in connection.attrib:
            links_by_light[connection.attrib["tl"]].add(int(connection.attrib["linkIndex"]))

    programs = network.findall("tlLogic")
    assert sorted(program.attrib["id"] for program in programs) == sorted(NEIGHBOURS)
    for program in programs:
        links = links_by_light[program.attrib["id"]]
        for phase in program.iter("phase"):
            assert links == set(range(len(phase.attrib["state"]))), program.attrib["id"]


def test_green_always_ends_with_a_yellow_phase(network):
    for program in network.iter("tlLogic"):
        phases = program.findall("phase")
        for phase, following in zip(phases, phases[1:] + phases[:1], strict=True):
            state, next_state = phase.attrib["state"], following.attrib["state"]
            for link, (signal, next_signal) in enumerate(zip(state, next_state, strict=True)):
                assert not (signal in "Gg" and next_signal == "r"), (
                    f"link {link} of {program.attrib['id']} goes from green to red"
                )
            if "y" in state:
                assert float(phase.attrib["duration"]) >= MIN_YELLOW_S, program.attrib["id"]


def test_there_is_a_fixed_time_program_for_every_traffic_level():
    names = {path.name for path in FIXED_TIME_FILES}
    assert names == {f"tls.fixed-x{scale}.add.xml" for scale in (1, 7, 12, 16)}


@pytest.mark.parametrize("path", FIXED_TIME_FILES, ids=lambda path: path.name)
def test_fixed_time_programs_keep_the_phases_of_the_network(network, path):
    states_in_network = {
        program.attrib["id"]: [phase.attrib["state"] for phase in program.iter("phase")]
        for program in network.iter("tlLogic")
    }
    programs = ET.parse(path).getroot().findall("tlLogic")
    assert sorted(program.attrib["id"] for program in programs) == sorted(NEIGHBOURS)

    cycles = set()
    for program in programs:
        junction = program.attrib["id"]
        # scripts/run_sumo.py finds the file by this name, and SUMO activates a new id.
        assert f"tls.{program.attrib['programID']}.add.xml" == path.name
        phases = program.findall("phase")
        # The green phases are the actions of an RL agent, and the network has yellow after
        # every green, so only the durations may differ.
        assert [phase.attrib["state"] for phase in phases] == states_in_network[junction]
        for phase in phases:
            if "y" in phase.attrib["state"]:
                assert float(phase.attrib["duration"]) >= MIN_YELLOW_S, junction
        cycle = sum(float(phase.attrib["duration"]) for phase in phases)
        assert 0 <= float(program.attrib["offset"]) < cycle, junction
        cycles.add(cycle)
    # Offsets only keep the junctions in step if all of them have the same cycle.
    assert len(cycles) == 1


def test_generator_config_names_every_signalized_node(network):
    with (SCENARIO_DIR / "scenario.toml").open("rb") as file:
        config = tomllib.load(file)
    signalized = sorted(
        node.attrib["id"]
        for node in network.iter("junction")
        if node.get("type") == "traffic_light"
    )
    assert sorted(junction["node"] for junction in config["junctions"]) == signalized

"""Tests of the network flows part of the config and of its checks."""

from pathlib import Path

import numpy as np
import pytest

from trafficgen import load_network_config

JUNCTIONS = """
[[junctions]]
id = "A"

[[junctions]]
id = "B"
"""

ROADS = """
[[roads]]
id = "in_A"
to = "A"
preference = 1.0

[[roads]]
id = "A_B"
from = "A"
to = "B"
length_m = 300
lanes = 1
speed_limit_kmh = 50
through_share = 0.9

[[roads]]
id = "A_out"
from = "A"

[[roads]]
id = "B_out"
from = "B"
"""

TURNS = """
[[turns]]
from_road = "in_A"
to_road = "A_B"
preference = 3.0

[[turns]]
from_road = "in_A"
to_road = "A_out"
preference = 1.0

[[turns]]
from_road = "A_B"
to_road = "B_out"
preference = 1.0
"""


def write(directory: Path, text: str) -> Path:
    path = directory / "network.toml"
    path.write_text(text)
    return path


def test_line_network_is_read_without_junction_data(tmp_path):
    config = load_network_config(
        write(tmp_path, JUNCTIONS + ROADS + TURNS + "[flows]\ntolerance_vph = 0.1\n")
    )

    assert config.junction_ids == ("A", "B")
    assert [road.kind for road in config.roads] == ["entry", "internal", "exit", "exit"]
    assert config.roads_by_id["A_B"].free_flow_time_s == pytest.approx(21.6)
    assert config.settings.tolerance_vph == 0.1


def test_preferences_are_turned_into_shares(tmp_path):
    config = load_network_config(write(tmp_path, JUNCTIONS + ROADS + TURNS))
    np.testing.assert_allclose(config.preferred_turn_shares(), [0.75, 0.25, 1.0])
    np.testing.assert_allclose(config.preferred_entry_shares(), [1.0, 0, 0, 0])


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('id = "B_out"', 'id = "in_A"', "duplicate road ids"),
        ('to = "B"', 'to = "C"', "unknown junction 'C'"),
        ('id = "B_out"\nfrom = "B"', 'id = "B_out"', "neither 'from' nor 'to'"),
        ("preference = 1.0\n\n[[roads]]", "\n[[roads]]", "has no 'preference'"),
        ('id = "A_out"', 'id = "A_out"\npreference = 1.0', "applies only to entry roads"),
        ("through_share = 0.9", "through_share = 1.5", r"through_share must be in \(0, 1\]"),
        ("lanes = 1", "lanes = 0", "lanes must be positive"),
        ("lanes = 1", "lane = 1", "unknown keys"),
        ("preference = 3.0", "preference = -1.0", "preference must not be negative"),
        ('to_road = "B_out"', 'to_road = "nowhere"', "unknown road 'nowhere'"),
        ('to_road = "A_out"', 'to_road = "B_out"', "'B_out' starts at 'B'"),
        ("preference = 3.0", "ratio = 3.0", "unknown keys"),
    ],
)
def test_invalid_configs_fail_with_a_clear_message(tmp_path, old, new, message):
    text = JUNCTIONS + ROADS + TURNS
    assert old in text
    with pytest.raises(ValueError, match=message):
        load_network_config(write(tmp_path, text.replace(old, new, 1)))


def test_error_names_the_file(tmp_path):
    path = write(tmp_path, (JUNCTIONS + ROADS + TURNS).replace('to = "B"', 'to = "C"'))
    with pytest.raises(ValueError, match="network.toml: road 'A_B' uses unknown junction"):
        load_network_config(path)


def test_preferences_of_a_road_cannot_all_be_zero(tmp_path):
    text = (JUNCTIONS + ROADS + TURNS).replace("preference = 3.0", "preference = 0.0")
    text = text.replace(
        'to_road = "A_out"\npreference = 1.0', 'to_road = "A_out"\npreference = 0.0'
    )
    with pytest.raises(ValueError, match="preferences of the turns from road 'in_A' are all 0"):
        load_network_config(write(tmp_path, text))


def test_road_ending_at_a_junction_needs_turns(tmp_path):
    turns = TURNS.split("[[turns]]")
    with pytest.raises(ValueError, match="'A_B' ends at a junction but has no turns"):
        load_network_config(write(tmp_path, JUNCTIONS + ROADS + "[[turns]]".join(turns[:3])))


def test_junction_needs_a_way_out(tmp_path):
    roads = ROADS.split('[[roads]]\nid = "B_out"')[0]
    turns = "[[turns]]".join(TURNS.split("[[turns]]")[:3])
    with pytest.raises(ValueError, match="'B' has no road leading out of it"):
        load_network_config(write(tmp_path, JUNCTIONS + roads + turns))


def test_closed_loop_is_rejected(tmp_path):
    text = (
        JUNCTIONS
        + """
[[roads]]
id = "in_A"
to = "A"
preference = 1.0

[[roads]]
id = "A_B"
from = "A"
to = "B"

[[roads]]
id = "B_A"
from = "B"
to = "A"

[[roads]]
id = "B_out"
from = "B"

[[turns]]
from_road = "in_A"
to_road = "A_B"
preference = 1.0

[[turns]]
from_road = "A_B"
to_road = "B_A"
preference = 1.0

[[turns]]
from_road = "B_A"
to_road = "A_B"
preference = 1.0
"""
    )
    with pytest.raises(ValueError, match="can never leave the network"):
        load_network_config(write(tmp_path, text))


def test_invalid_flow_settings_fail(tmp_path):
    with pytest.raises(ValueError, match="tolerance_vph must be positive"):
        load_network_config(
            write(tmp_path, JUNCTIONS + ROADS + TURNS + "[flows]\ntolerance_vph = 0\n")
        )


SINGLE_NET = (
    Path(__file__).parents[2] / "scenarios" / "single-intersection" / "intersection.net.xml"
)


def write_from_net(directory: Path, extra: str = "", node: str = "J0") -> Path:
    """Write a config that reads its network from the single intersection."""
    text = (
        f'[[junctions]]\nid = "J1"\nnode = "{node}"\n\n'
        f'[network]\nfile = "{SINGLE_NET.as_posix()}"\n\n' + extra
    )
    return write(directory, text)


def test_network_is_read_from_the_sumo_file(tmp_path):
    config = load_network_config(write_from_net(tmp_path))

    assert config.junction_ids == ("J1",)
    assert config.roads_by_id["-E0"].kind == "entry"
    assert config.roads_by_id["-E0"].preference == 1.0
    assert config.roads_by_id["E0"].kind == "exit"
    assert config.roads_by_id["-E0"].length_m == pytest.approx(92.8)
    assert config.roads_by_id["-E0"].speed_limit_kmh == pytest.approx(50.0)
    preferences = {(turn.from_road, turn.to_road): turn.preference for turn in config.turns}
    assert len(preferences) == 12
    assert preferences[("-E0", "E3")] == pytest.approx(0.7)
    assert preferences[("-E0", "E2")] == pytest.approx(0.15)


def test_turn_preferences_of_the_network_can_be_changed(tmp_path):
    config = load_network_config(
        write_from_net(tmp_path, "turn_preferences = { straight = 0.5 }\n")
    )
    preferences = {(turn.from_road, turn.to_road): turn.preference for turn in config.turns}
    assert preferences[("-E0", "E3")] == pytest.approx(0.5)
    assert preferences[("-E0", "E2")] == pytest.approx(0.15)


def test_single_roads_and_turns_can_be_overridden(tmp_path):
    overrides = (
        '[[roads]]\nid = "-E0"\npreference = 3.0\n\n'
        '[[turns]]\nfrom_road = "-E0"\nto_road = "E3"\npreference = 0.9\n'
    )
    config = load_network_config(write_from_net(tmp_path, overrides))

    assert config.roads_by_id["-E0"].preference == 3.0
    assert config.roads_by_id["-E1"].preference == 1.0
    turn = next(t for t in config.turns if (t.from_road, t.to_road) == ("-E0", "E3"))
    assert turn.preference == 0.9


@pytest.mark.parametrize(
    ("extra", "node", "message"),
    [
        ("", "X", r"has no nodes \['X'\]"),
        ('[[roads]]\nid = "nowhere"\n', "J0", "road 'nowhere' is not in the network file"),
        ('[[roads]]\nid = "-E0"\nfrom = "J1"\n', "J0", r"\['from'\] cannot be changed"),
        (
            '[[turns]]\nfrom_road = "-E0"\nto_road = "-E1"\npreference = 1.0\n',
            "J0",
            "is not a connection of the network file",
        ),
    ],
)
def test_invalid_network_overrides_fail(tmp_path, extra, node, message):
    with pytest.raises(ValueError, match=message):
        load_network_config(write_from_net(tmp_path, extra, node))


def test_junction_needs_a_node_with_a_network_file(tmp_path):
    path = write(
        tmp_path, f'[[junctions]]\nid = "J1"\n\n[network]\nfile = "{SINGLE_NET.as_posix()}"\n'
    )
    with pytest.raises(ValueError, match="junction 'J1' needs a 'node'"):
        load_network_config(path)


def test_every_inner_node_needs_a_junction(tmp_path):
    grid_net = SINGLE_NET.parents[1] / "grid-2x2" / "grid.net.xml"
    path = write(
        tmp_path,
        f'[[junctions]]\nid = "J1"\nnode = "A0"\n\n[network]\nfile = "{grid_net.as_posix()}"\n',
    )
    with pytest.raises(ValueError, match="node 'A1' of grid.net.xml is not a dead end"):
        load_network_config(path)


def test_missing_network_file_and_unknown_direction_fail(tmp_path):
    with pytest.raises(ValueError, match="file not found"):
        load_network_config(
            write(
                tmp_path, '[[junctions]]\nid = "J1"\nnode = "J0"\n\n[network]\nfile = "x.net.xml"\n'
            )
        )
    with pytest.raises(ValueError, match=r"unknown directions \['uturn'\]"):
        load_network_config(write_from_net(tmp_path, "turn_preferences = { uturn = 1.0 }\n"))

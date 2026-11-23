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

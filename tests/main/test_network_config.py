"""Tests of the network config of layer 2 and of its checks."""

from pathlib import Path

import pytest

from trafficgen import load_network_config

CONFIGS_DIR = Path(__file__).parents[2] / "configs"

JUNCTIONS = """
[[junctions]]
id = "A"
data = "data.csv"

[[junctions]]
id = "B"
data = "data.csv"
"""

ROADS = """
[[roads]]
id = "in_A"
to = "A"
weight = 1.0

[[roads]]
id = "A_B"
from = "A"
to = "B"
length_m = 300
lanes = 1
speed_limit_kmh = 50
through_share = 0.9

[[roads]]
id = "B_out"
from = "B"
"""

TURNS = """
[[turns]]
from_road = "in_A"
to_road = "A_B"
ratio = 1.0

[[turns]]
from_road = "A_B"
to_road = "B_out"
ratio = 1.0
"""


def write(directory: Path, text: str) -> Path:
    path = directory / "network.toml"
    path.write_text(text)
    return path


@pytest.mark.parametrize("name", ["network_single.toml", "network_grid_2x2.toml"])
def test_shipped_configs_are_valid(name):
    config = load_network_config(CONFIGS_DIR / name)
    assert config.roads and config.turns


def test_line_network_is_read(tmp_path, monkeypatch):
    path = write(
        tmp_path,
        "scale = 2.0\n" + JUNCTIONS + ROADS + TURNS + "[balance]\nweighting = 'relative'\n",
    )
    monkeypatch.chdir("/")
    config = load_network_config(path)

    assert config.junctions[0].data == (tmp_path / "data.csv").resolve()
    assert [road.kind for road in config.roads] == ["entry", "internal", "exit"]
    assert config.roads_by_id["A_B"].through_share == 0.9
    assert config.roads_by_id["A_B"].free_flow_time_s == pytest.approx(21.6)
    assert config.scale == 2.0
    assert config.balance.weighting == "relative"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('id = "B_out"', 'id = "in_A"', "duplicate road ids"),
        ('to = "B"', 'to = "C"', "unknown junction 'C'"),
        ('id = "B_out"\nfrom = "B"', 'id = "B_out"', "neither 'from' nor 'to'"),
        ("weight = 1.0", "weight = 0.5", "sum to 0.5, not 1"),
        ("weight = 1.0", "", "has no 'weight'"),
        ("through_share = 0.9", "through_share = 1.5", r"through_share must be in \(0, 1\]"),
        ("lanes = 1", "lanes = 0", "lanes must be positive"),
        ("lanes = 1", "lane = 1", "unknown keys"),
        ('to_road = "B_out"', 'to_road = "nowhere"', "unknown road 'nowhere'"),
        ('to_road = "A_B"\nratio = 1.0', 'to_road = "A_B"\nratio = 0.7', "sum to 0.7, not 1"),
        ('to_road = "A_B"', 'to_road = "B_out"', "'B_out' starts at 'B'"),
    ],
)
def test_invalid_configs_fail_with_a_clear_message(tmp_path, old, new, message):
    text = JUNCTIONS + ROADS + TURNS
    assert old in text
    with pytest.raises(ValueError, match=message):
        load_network_config(write(tmp_path, text.replace(old, new, 1)))


def test_error_names_the_file(tmp_path):
    path = write(tmp_path, JUNCTIONS + ROADS + TURNS.replace("ratio = 1.0", "ratio = 0.5", 1))
    with pytest.raises(ValueError, match="network.toml"):
        load_network_config(path)


def test_road_ending_at_a_junction_needs_turns(tmp_path):
    turns = TURNS.split("[[turns]]")[1]
    with pytest.raises(ValueError, match="'A_B' ends at a junction but has no turns"):
        load_network_config(write(tmp_path, JUNCTIONS + ROADS + "[[turns]]" + turns))


def test_junction_needs_a_way_out(tmp_path):
    roads = ROADS.split('[[roads]]\nid = "B_out"')[0]
    turns = TURNS.split("[[turns]]")[1]
    with pytest.raises(ValueError, match="'B' has no road leading out of it"):
        load_network_config(write(tmp_path, JUNCTIONS + roads + "[[turns]]" + turns))


def test_network_needs_an_entry(tmp_path):
    text = (
        JUNCTIONS
        + """
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
from_road = "A_B"
to_road = "B_out"
ratio = 1.0

[[turns]]
from_road = "B_A"
to_road = "A_B"
ratio = 1.0
"""
    )
    with pytest.raises(ValueError, match="no road enters the network"):
        load_network_config(write(tmp_path, text))


def test_closed_loop_is_rejected(tmp_path):
    text = (
        JUNCTIONS
        + """
[[roads]]
id = "in_A"
to = "A"
weight = 1.0

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
ratio = 1.0

[[turns]]
from_road = "A_B"
to_road = "B_A"
ratio = 1.0

[[turns]]
from_road = "B_A"
to_road = "A_B"
ratio = 1.0
"""
    )
    with pytest.raises(ValueError, match="can never leave the network"):
        load_network_config(write(tmp_path, text))


def test_invalid_balance_settings_fail(tmp_path):
    with pytest.raises(ValueError, match="weighting must be one of"):
        load_network_config(
            write(tmp_path, JUNCTIONS + ROADS + TURNS + "[balance]\nweighting = 'x'\n")
        )

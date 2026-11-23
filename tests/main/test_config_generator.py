"""Tests of scripts/generate_config.py, without SUMO."""

import shlex
from pathlib import Path

import pytest

from trafficgen import load_counts_config, load_network_config

REPOSITORY = Path(__file__).parents[2]
GENERATED_CONFIGS = ["single_intersection.toml", "grid_2x2.toml"]
SINGLE_NET = REPOSITORY / "sumo/scenarios/single-intersection/intersection.net.xml"
GRID_NET = REPOSITORY / "sumo/scenarios/grid-2x2/grid.net.xml"


@pytest.fixture
def generator(load_script):
    return load_script("generate_config")


def command_in_header(config_path: Path) -> list[str]:
    """Read the arguments of the command in the header of a generated config."""
    command_line = config_path.read_text().splitlines()[1].removeprefix("# ")
    arguments = shlex.split(command_line)
    script_position = arguments.index("scripts/generate_config.py")
    return arguments[script_position + 1 : arguments.index("--output")]


@pytest.mark.parametrize("name", GENERATED_CONFIGS)
def test_committed_configs_are_reproduced_by_their_header_command(
    generator, tmp_path, monkeypatch, name
):
    committed = REPOSITORY / "configs" / name
    monkeypatch.chdir(REPOSITORY)
    output = tmp_path / name

    generator.main([*command_in_header(committed), "--output", str(output)])

    assert output.read_text() == committed.read_text()


def test_roads_and_turn_directions_are_read(generator, tmp_path):
    output = tmp_path / "single.toml"
    generator.main([str(SINGLE_NET), "--junction", "J0=J1", "--output", str(output)])
    config = load_network_config(output)

    assert config.roads_by_id["-E0"].kind == "entry"
    assert config.roads_by_id["E0"].kind == "exit"
    assert config.roads_by_id["-E0"].length_m == pytest.approx(92.8)
    preferences = {(turn.from_road, turn.to_road): turn.preference for turn in config.turns}
    assert preferences[("-E0", "E3")] == pytest.approx(0.7)
    assert preferences[("-E0", "E2")] == pytest.approx(0.15)


def test_grid_junctions_get_data_in_the_order_of_the_mapping(generator, tmp_path):
    output = tmp_path / "grid.toml"
    mappings = ["--junction", "B1=X", "--junction", "A0=Y", "--junction", "A1=Z"]
    generator.main([str(GRID_NET), *mappings, "--junction", "B0=W", "--output", str(output)])
    counts = load_counts_config(output)

    assert counts.junction_ids == ["X", "Y", "Z", "W"]
    assert counts.junctions[0].data.name == "kaggle_junction_1.csv"
    kinds = [road.kind for road in load_network_config(output).roads]
    assert kinds.count("entry") == kinds.count("exit") == 8
    assert kinds.count("internal") == 8


def test_every_inner_node_needs_a_junction(generator, tmp_path):
    with pytest.raises(SystemExit, match="SUMO node 'J0' has no --junction mapping"):
        generator.main([str(SINGLE_NET), "--junction", "X=J1", "--output", str(tmp_path / "x")])


def test_header_leaves_out_the_output_path(generator):
    text = generator.render_config({"counts": {"scale": 1.0}}, ["net.xml", "--output", "a.toml"])
    assert "a.toml" not in text
    assert "generate_config.py net.xml --output <this file>" in text

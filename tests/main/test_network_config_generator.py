"""Tests of scripts/generate_network_config.py, without SUMO."""

import shlex
from pathlib import Path

import pytest

from trafficgen import load_network_config

REPOSITORY = Path(__file__).parents[2]
GENERATED_CONFIGS = ["network_single.toml", "network_grid_2x2.toml"]


@pytest.fixture
def generator(load_script):
    return load_script("generate_network_config")


def command_in_header(config_path: Path) -> list[str]:
    command_line = config_path.read_text().splitlines()[1].removeprefix("# ")
    arguments = shlex.split(command_line)
    script_position = arguments.index("scripts/generate_network_config.py")
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


def test_grid_has_entries_only_on_the_boundary(generator, tmp_path):
    output = tmp_path / "grid.toml"
    generator.main(["grid", "--rows", "3", "--cols", "3", "--output", str(output)])
    config = load_network_config(output)

    kinds = [road.kind for road in config.roads]
    assert kinds.count("entry") == kinds.count("exit") == 12
    assert kinds.count("internal") == 24
    assert "J5" not in config.entry_junction_ids
    assert config.roads_by_id["north_J2"].weight == 1.0
    assert config.roads_by_id["north_J1"].weight == 0.5


def test_from_sumo_reads_roads_and_turn_directions(generator, tmp_path):
    output = tmp_path / "single.toml"
    net_file = REPOSITORY / "sumo/scenarios/single-intersection/intersection.net.xml"
    generator.main(["from-sumo", str(net_file), "--junction", "J0=J1", "--output", str(output)])
    config = load_network_config(output)

    assert config.roads_by_id["-E0"].kind == "entry"
    assert config.roads_by_id["E0"].kind == "exit"
    assert config.roads_by_id["-E0"].length_m == pytest.approx(92.8)
    ratios = {(turn.from_road, turn.to_road): turn.ratio for turn in config.turns}
    assert ratios[("-E0", "E3")] == pytest.approx(0.7)
    assert ratios[("-E0", "E2")] == pytest.approx(0.15)


def test_from_sumo_needs_a_junction_for_every_inner_node(generator, tmp_path):
    net_file = REPOSITORY / "sumo/scenarios/single-intersection/intersection.net.xml"
    with pytest.raises(SystemExit, match="SUMO node 'J0' has no --junction mapping"):
        generator.main(
            ["from-sumo", str(net_file), "--junction", "X=J1", "--output", str(tmp_path / "x")]
        )


def test_missing_turn_directions_share_the_remaining_ratio(generator):
    ratios = generator._ratios_by_target(
        {"straight_road": "straight", "left_road": "left"}, (0.15, 0.7, 0.15)
    )
    assert ratios == pytest.approx({"straight_road": 0.7 / 0.85, "left_road": 0.15 / 0.85})


def test_header_leaves_out_the_output_path(generator):
    text = generator.render_config({"scale": 1.0}, ["grid", "--output", "a.toml", "--rows", "1"])
    assert "a.toml" not in text
    assert "grid --rows 1 --output <this file>" in text

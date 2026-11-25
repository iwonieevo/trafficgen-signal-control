"""Check that the SUMO scenarios are complete without running SUMO."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCENARIOS_DIR = Path(__file__).parents[2] / "scenarios"
SCENARIOS = sorted(path for path in SCENARIOS_DIR.iterdir() if path.is_dir())


def test_scenarios_exist():
    assert SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda path: path.name)
def test_scenario_config_is_valid(scenario):
    # scripts/run_sumo.py requires exactly one config per scenario.
    configs = list(scenario.glob("*.sumocfg"))
    assert len(configs) == 1

    input_section = ET.parse(configs[0]).getroot().find("input")
    assert input_section is not None

    for option in input_section:
        for name in option.attrib["value"].split(","):
            path = scenario / name.strip()
            assert path.is_file(), f"missing input file: {path.name}"
            ET.parse(path)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda path: path.name)
def test_additional_files_are_valid_and_name_existing_traffic_lights(scenario):
    # Files like tls.<controller>.add.xml are not listed in the config, so check them here.
    additional_files = sorted(scenario.glob("*.add.xml"))
    if not additional_files:
        return
    network = ET.parse(next(scenario.glob("*.net.xml"))).getroot()
    traffic_lights = {logic.attrib["id"] for logic in network.iter("tlLogic")}

    for path in additional_files:
        for logic in ET.parse(path).getroot().iter("tlLogic"):
            assert logic.attrib["id"] in traffic_lights, path.name

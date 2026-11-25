"""Tests of the SUMO launcher."""

import shutil
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def launcher(load_script) -> ModuleType:
    """Import the launcher script as a module."""
    return load_script("run_sumo")


def test_find_config_returns_the_scenario_config(launcher):
    assert launcher.find_config("single-intersection").name == "intersection.sumocfg"


def test_find_config_lists_available_scenarios(launcher):
    with pytest.raises(SystemExit, match="Unknown scenario 'nope'. Available: .*hello-world"):
        launcher.find_config("nope")


@pytest.mark.parametrize("config_count", [0, 2])
def test_find_config_requires_exactly_one_config(launcher, monkeypatch, tmp_path, config_count):
    monkeypatch.setattr(launcher, "SCENARIOS_DIR", tmp_path)
    (tmp_path / "broken").mkdir()
    for number in range(config_count):
        (tmp_path / "broken" / f"{number}.sumocfg").touch()
    with pytest.raises(SystemExit, match="exactly one"):
        launcher.find_config("broken")


@pytest.mark.parametrize(("gui", "name"), [(False, "sumo"), (True, "sumo-gui")])
def test_find_executable_prefers_the_python_package(launcher, monkeypatch, tmp_path, gui, name):
    # Windows only finds programs that have an executable extension.
    program = tmp_path / "bin" / (f"{name}.exe" if sys.platform == "win32" else name)
    program.parent.mkdir()
    program.touch(mode=0o755)
    monkeypatch.setitem(sys.modules, "sumo", SimpleNamespace(SUMO_HOME=str(tmp_path)))
    monkeypatch.setenv("SUMO_HOME", "unchanged")

    assert Path(launcher.find_executable(gui)).samefile(program)
    assert launcher.os.environ["SUMO_HOME"] == str(tmp_path)


def test_find_executable_falls_back_to_the_path(launcher, monkeypatch):
    monkeypatch.setitem(sys.modules, "sumo", None)
    monkeypatch.setattr(shutil, "which", lambda name, path=None: f"/usr/bin/{name}")
    assert launcher.find_executable(False) == "/usr/bin/sumo"


def test_find_executable_reports_a_missing_installation(launcher, monkeypatch):
    monkeypatch.setitem(sys.modules, "sumo", None)
    monkeypatch.setattr(shutil, "which", lambda name, path=None: None)
    with pytest.raises(SystemExit, match="SUMO executable not found: sumo-gui"):
        launcher.find_executable(True)


def test_find_config_accepts_the_path_of_a_config(launcher, tmp_path):
    config = tmp_path / "run.sumocfg"
    config.touch()
    assert launcher.find_config(str(config)) == config


def test_find_config_reports_a_missing_config_file(launcher, tmp_path):
    with pytest.raises(SystemExit, match="SUMO config not found"):
        launcher.find_config(str(tmp_path / "missing.sumocfg"))


@pytest.fixture
def scenario_with_controllers(tmp_path) -> Path:
    """A scenario directory with a network, a config and the programs of two controllers."""
    scenario = tmp_path / "scenario"
    scenario.mkdir()
    for name in ("grid.net.xml", "tls.fixed-x7.add.xml", "tls.actuated.add.xml"):
        (scenario / name).touch()
    (scenario / "grid.sumocfg").write_text(
        '<configuration><input><net-file value="grid.net.xml"/></input></configuration>'
    )
    return scenario


def write_run_config(scenario: Path, inputs: str = "") -> Path:
    """Write the config of a run in the runs directory of a scenario, as the generator does."""
    config = scenario / "runs" / "week" / "sumo" / "run.sumocfg"
    config.parent.mkdir(parents=True)
    config.write_text(
        '<configuration><input><net-file value="../../../grid.net.xml"/>'
        f'<route-files value="routes.rou.xml"/>{inputs}</input></configuration>'
    )
    return config


def test_find_controller_looks_next_to_the_network(launcher, scenario_with_controllers):
    expected = scenario_with_controllers / "tls.fixed-x7.add.xml"
    run_config = write_run_config(scenario_with_controllers)

    for config in (scenario_with_controllers / "grid.sumocfg", run_config):
        assert launcher.find_controller(config, "fixed-x7").samefile(expected)


def test_find_controller_lists_available_controllers(launcher, scenario_with_controllers):
    config = scenario_with_controllers / "grid.sumocfg"
    with pytest.raises(SystemExit, match="Unknown controller 'nope' .* actuated, fixed-x7"):
        launcher.find_controller(config, "nope")


def test_find_controller_requires_a_network_in_the_config(launcher, tmp_path):
    config = tmp_path / "empty.sumocfg"
    config.write_text("<configuration><input/></configuration>")
    with pytest.raises(SystemExit, match="No net-file"):
        launcher.find_controller(config, "fixed-x7")


def test_command_without_a_controller_only_names_the_config(launcher, scenario_with_controllers):
    config = scenario_with_controllers / "grid.sumocfg"
    assert launcher.build_command("sumo", config) == ["sumo", "-c", str(config)]


def test_command_adds_the_programs_of_the_controller(launcher, scenario_with_controllers):
    config = write_run_config(scenario_with_controllers)

    command = launcher.build_command("sumo", config, "actuated")

    assert command[:4] == ["sumo", "-c", str(config), "--additional-files"]
    assert Path(command[4]).samefile(scenario_with_controllers / "tls.actuated.add.xml")


def test_command_keeps_the_additional_files_of_the_config(launcher, scenario_with_controllers):
    # On the command line, --additional-files replaces the files of the config.
    config = write_run_config(
        scenario_with_controllers, '<additional-files value="detectors.add.xml, more.add.xml"/>'
    )

    files = launcher.build_command("sumo", config, "fixed-x7")[4].split(",")

    assert [Path(file).name for file in files] == [
        "detectors.add.xml",
        "more.add.xml",
        "tls.fixed-x7.add.xml",
    ]
    assert Path(files[0]).parent.samefile(config.parent)


def test_main_runs_the_scenario_with_the_controller(launcher, monkeypatch):
    commands = []
    monkeypatch.setattr(sys, "argv", ["run_sumo.py", "grid-2x2", "--controller", "fixed-x12"])
    monkeypatch.setattr(launcher, "find_executable", lambda gui: "sumo")
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, check: commands.append(command) or SimpleNamespace(returncode=0),
    )

    with pytest.raises(SystemExit) as exit_info:
        launcher.main()

    assert exit_info.value.code == 0
    assert Path(commands[0][4]).name == "tls.fixed-x12.add.xml"

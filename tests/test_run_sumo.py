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

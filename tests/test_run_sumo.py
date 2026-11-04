"""Tests of the SUMO launcher."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "run_sumo.py"


@pytest.fixture
def launcher() -> ModuleType:
    """Import the launcher script as a module."""
    spec = importlib.util.spec_from_file_location("run_sumo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    program = tmp_path / "bin" / name
    program.parent.mkdir()
    program.touch(mode=0o755)
    monkeypatch.setitem(sys.modules, "sumo", SimpleNamespace(SUMO_HOME=str(tmp_path)))
    monkeypatch.setenv("SUMO_HOME", "unchanged")

    assert launcher.find_executable(gui) == str(program)
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


def test_scenario_runs_in_sumo():
    pytest.importorskip("sumo")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "hello-world"], capture_output=True, check=False
    )
    assert result.returncode == 0

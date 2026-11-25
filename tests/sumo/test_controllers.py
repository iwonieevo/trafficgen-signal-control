"""Signal programs of the controllers in the real SUMO simulator, and their tuning."""

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from trafficgen import find_sumo_program, generate_traffic

REPO_ROOT = Path(__file__).parents[2]
GRID_DIR = REPO_ROOT / "scenarios" / "grid-2x2"
JUNCTIONS = ("A0", "A1", "B0", "B1")
CONTROLLERS = sorted(
    path.name.removeprefix("tls.").removesuffix(".add.xml")
    for path in GRID_DIR.glob("tls.*.add.xml")
)
START, END = "2024-03-04T06:00", "2024-03-04T08:00"


def run_script(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a script of the repository."""
    command = [sys.executable, str(REPO_ROOT / "scripts" / f"{name}.py"), *arguments]
    return subprocess.run(command, capture_output=True, text=True, check=False)


@pytest.fixture
def grid_run_dir(tmp_path, grid_config_path) -> Path:
    """Two hours of generated traffic on the grid, with the synthetic counts of the tests."""
    run = generate_traffic(grid_config_path, START, END, tmp_path / "run", seed=3, scale=8.0)
    return run.output_dir


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_grid_runs_with_the_controller(controller):
    result = run_script("run_sumo", "grid-2x2", "--controller", controller)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_programs_of_the_controller_are_the_active_ones(tmp_path, controller):
    saved = {junction: tmp_path / f"{junction}.xml" for junction in JUNCTIONS}
    events = tmp_path / "save.add.xml"
    events.write_text(
        "<additional>"
        + "".join(
            f'<timedEvent type="SaveTLSProgram" source="{junction}" dest="{path.as_posix()}"/>'
            for junction, path in saved.items()
        )
        + "</additional>"
    )
    command = [
        find_sumo_program("sumo"),
        "-c", str(GRID_DIR / "grid.sumocfg"),
        "--additional-files", f"{GRID_DIR / f'tls.{controller}.add.xml'},{events}",
        "--no-step-log",
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    for junction, path in saved.items():
        programs = {logic.attrib["programID"] for logic in ET.parse(path).getroot().iter("tlLogic")}
        assert programs == {controller}, junction


def test_generated_run_runs_with_a_controller(grid_run_dir):
    config = grid_run_dir / "sumo" / "run.sumocfg"
    result = run_script("run_sumo", str(config), "--controller", "fixed-x7")
    assert result.returncode == 0, result.stderr


def test_programs_tuned_for_a_run_have_offsets_and_run_in_sumo(tmp_path, grid_run_dir):
    output = tmp_path / "tls.tuned.add.xml"
    result = run_script(
        "tune_fixed_time", str(grid_run_dir), "--name", "tuned", "--output", str(output)
    )
    assert result.returncode == 0, result.stderr

    programs = ET.parse(output).getroot().findall("tlLogic")
    assert sorted(program.attrib["id"] for program in programs) == sorted(JUNCTIONS)
    cycles = {
        sum(int(phase.attrib["duration"]) for phase in program.iter("phase"))
        for program in programs
    }
    assert len(cycles) == 1
    offsets = [float(program.attrib["offset"]) for program in programs]
    assert all(0 <= offset < next(iter(cycles)) for offset in offsets)
    # The junctions next to the busy one start later, so its vehicles arrive on green.
    assert any(offset > 0 for offset in offsets)

    statistics = tmp_path / "statistics.xml"
    command = [
        find_sumo_program("sumo"),
        "-c", str(grid_run_dir / "sumo" / "run.sumocfg"),
        "--additional-files", str(output),
        "--statistic-output", str(statistics),
        "--no-step-log",
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert ET.parse(statistics).getroot().find("teleports").get("total") == "0"  # pyright: ignore[reportOptionalMemberAccess]

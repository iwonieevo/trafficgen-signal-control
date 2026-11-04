"""Run the scenarios in the real SUMO simulator. These tests need SUMO installed."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
SCENARIOS_DIR = REPO_ROOT / "sumo" / "scenarios"
SCENARIOS = sorted(path.name for path in SCENARIOS_DIR.iterdir() if path.is_dir())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_runs_in_sumo(scenario):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_sumo.py"), scenario],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

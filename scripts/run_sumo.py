"""Run a SUMO scenario from sumo/scenarios on Windows, Linux or macOS."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "sumo" / "scenarios"


def find_config(scenario: str) -> Path:
    """Find the configuration file of a scenario.

    Args:
        scenario: Name of a directory in ``sumo/scenarios``.

    Returns:
        The only ``.sumocfg`` file of the scenario.

    Raises:
        SystemExit: If the scenario does not exist or does not have exactly one config.
    """
    directory = SCENARIOS_DIR / scenario
    if not directory.is_dir():
        available = ", ".join(sorted(path.name for path in SCENARIOS_DIR.iterdir()))
        sys.exit(f"Unknown scenario {scenario!r}. Available: {available}")

    configs = list(directory.glob("*.sumocfg"))
    if len(configs) != 1:
        sys.exit(f"Expected exactly one .sumocfg file in: {directory}")
    return configs[0]


def find_executable(gui: bool) -> str:
    """Find the SUMO program, preferring the ``eclipse-sumo`` Python package.

    When the package is found, this also sets ``SUMO_HOME`` for the started program.

    Args:
        gui: Whether to look for ``sumo-gui`` instead of ``sumo``.

    Returns:
        Path of the program. It includes the file extension on Windows.

    Raises:
        SystemExit: If SUMO is not installed.
    """
    name = "sumo-gui" if gui else "sumo"
    try:
        import sumo
    except ImportError:
        executable = shutil.which(name)
    else:
        os.environ["SUMO_HOME"] = sumo.SUMO_HOME
        executable = shutil.which(name, path=str(Path(sumo.SUMO_HOME) / "bin"))

    if executable is None:
        sys.exit(f"SUMO executable not found: {name}. Install it with: uv sync")
    return executable


def main() -> None:
    """Run the requested scenario and exit with the exit code of SUMO."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="name of a directory in sumo/scenarios")
    parser.add_argument("--gui", action="store_true", help="run with sumo-gui")
    args = parser.parse_args()

    config = find_config(args.scenario)
    executable = find_executable(args.gui)
    sys.exit(subprocess.run([executable, "-c", str(config)], check=False).returncode)


if __name__ == "__main__":
    main()

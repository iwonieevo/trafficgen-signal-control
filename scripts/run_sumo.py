"""Run a SUMO scenario from scenarios/, or a given SUMO config, on Windows, Linux or macOS."""

import argparse
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


def find_config(scenario: str) -> Path:
    """Find the configuration file of a scenario.

    Args:
        scenario: Name of a directory in ``scenarios``, or the path of a ``.sumocfg``
            file, for example ``run.sumocfg`` of a generated run.

    Returns:
        The only ``.sumocfg`` file of the scenario, or the given file.

    Raises:
        SystemExit: If the scenario or file does not exist, or the scenario does not have
            exactly one config.
    """
    if scenario.endswith(".sumocfg"):
        path = Path(scenario)
        if not path.is_file():
            sys.exit(f"SUMO config not found: {path}")
        return path

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
        import sumo  # pyright: ignore[reportMissingImports]
    except ImportError:
        executable = shutil.which(name)
    else:
        sumo_home = sumo.SUMO_HOME  # pyright: ignore[reportAttributeAccessIssue]
        os.environ["SUMO_HOME"] = sumo_home
        executable = shutil.which(name, path=str(Path(sumo_home) / "bin"))

    if executable is None:
        sys.exit(f"SUMO executable not found: {name}. Install it with: uv sync")
    return executable


def input_files(config: Path, option: str) -> list[Path]:
    """Read the files of an input option of a SUMO config.

    Args:
        config: SUMO config file.
        option: Name of the option, for example ``net-file`` or ``additional-files``.

    Returns:
        The files of the option, or an empty list if the config does not have it.
    """
    element = ET.parse(config).getroot().find(f"input/{option}")
    if element is None:
        return []
    return [(config.parent / name.strip()).resolve() for name in element.attrib["value"].split(",")]


def find_controller(config: Path, controller: str) -> Path:
    """Find the signal programs of a controller for a SUMO config.

    A controller is a file ``tls.<name>.add.xml`` next to the network of the config. For
    the config of a generated run, this is the directory of its scenario.

    Args:
        config: SUMO config file.
        controller: Name of the controller.

    Returns:
        The file with the signal programs of the controller.

    Raises:
        SystemExit: If the config names no network, or the scenario has no such controller.
    """
    networks = input_files(config, "net-file")
    if not networks:
        sys.exit(f"No net-file in: {config}")

    directory = networks[0].parent
    path = directory / f"tls.{controller}.add.xml"
    if not path.is_file():
        names = sorted(
            file.name.removeprefix("tls.").removesuffix(".add.xml")
            for file in directory.glob("tls.*.add.xml")
        )
        available = ", ".join(names) or "none"
        sys.exit(f"Unknown controller {controller!r} in {directory}. Available: {available}")
    return path


def build_command(executable: str, config: Path, controller: str | None = None) -> list[str]:
    """Build the command that runs a SUMO config.

    Args:
        executable: Path of the SUMO program.
        config: SUMO config file.
        controller: Name of the controller whose signal programs replace the ones of the
            network. The programs of the network are used if None.

    Returns:
        The command and its arguments.

    Raises:
        SystemExit: If the controller does not exist.
    """
    command = [executable, "-c", str(config)]
    if controller is not None:
        # On the command line the option replaces the one of the config, so repeat its files.
        files = [*input_files(config, "additional-files"), find_controller(config, controller)]
        command += ["--additional-files", ",".join(str(file) for file in files)]
    return command


def main() -> None:
    """Run the requested scenario and exit with the exit code of SUMO."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenario", help="name of a directory in scenarios/, or the path of a .sumocfg file"
    )
    parser.add_argument("--gui", action="store_true", help="run with sumo-gui")
    parser.add_argument(
        "--controller",
        help="signal programs to use instead of the ones of the network: "
        "the name in tls.<name>.add.xml of the scenario, for example fixed-x12",
    )
    args = parser.parse_args()

    config = find_config(args.scenario)
    command = build_command(find_executable(args.gui), config, args.controller)
    sys.exit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()

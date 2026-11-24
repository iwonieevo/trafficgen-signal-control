"""Finding the SUMO programs, on Windows, Linux and macOS."""

import os
import shutil
from pathlib import Path


def find_sumo_program(name: str) -> str:
    """Find a SUMO program, preferring the ``eclipse-sumo`` Python package.

    When the package is found, this also sets ``SUMO_HOME`` for the started program.

    Args:
        name: Program name without extension, for example ``sumo`` or ``jtrrouter``.

    Returns:
        Path of the program. It includes the file extension on Windows.

    Raises:
        FileNotFoundError: If SUMO is not installed.
    """
    try:
        import sumo  # pyright: ignore[reportMissingImports]
    except ImportError:
        program = shutil.which(name)
    else:
        sumo_home = sumo.SUMO_HOME  # pyright: ignore[reportAttributeAccessIssue]
        os.environ["SUMO_HOME"] = sumo_home
        program = shutil.which(name, path=str(Path(sumo_home) / "bin"))

    if program is None:
        raise FileNotFoundError(f"SUMO program not found: {name}. Install it with: uv sync")
    return program

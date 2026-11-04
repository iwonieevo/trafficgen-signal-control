"""Run every notebook from start to end. These tests need the downloaded dataset.

This folder is outside the pytest testpaths, so neither `uv run pytest` nor CI runs it.
Run it with `uv run pytest notebook_tests`.
"""

import subprocess
import sys
from pathlib import Path

import pytest

NOTEBOOKS_DIR = Path(__file__).parent.parent / "notebooks"
NOTEBOOKS = sorted(NOTEBOOKS_DIR.glob("*.ipynb"))


def test_notebooks_exist():
    assert NOTEBOOKS


@pytest.mark.parametrize("notebook", NOTEBOOKS, ids=lambda path: path.stem)
def test_notebook_runs(notebook, tmp_path):
    # The executed copy goes to tmp_path, so the committed notebook stays unchanged.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--output-dir",
            str(tmp_path),
            str(notebook),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

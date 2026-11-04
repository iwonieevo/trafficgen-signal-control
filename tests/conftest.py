"""Shared test data: synthetic counts, so tests run without downloading the dataset."""

import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


@pytest.fixture
def hourly_counts() -> pd.Series:
    """Eight weeks of Poisson counts that are busier in the afternoon and on weekdays."""
    index = pd.date_range("2024-01-01", periods=8 * 168, freq="h", name="datetime")
    daily = 30 + 20 * np.sin((index.hour.to_numpy() - 8) / 24 * 2 * np.pi)
    weekly = np.where(index.day_of_week < 5, 1.0, 0.5)
    values = np.random.default_rng(0).poisson(daily * weekly)
    return pd.Series(values, index=index, name="vehicles")


@pytest.fixture
def load_script():
    """Return a function that imports a module from the scripts directory."""

    def load(name: str) -> ModuleType:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load

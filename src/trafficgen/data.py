"""Load hourly vehicle counts from CSV files."""

from pathlib import Path

import pandas as pd

DATETIME_COLUMN = "datetime"
VEHICLES_COLUMN = "vehicles"


def load_counts(path: str | Path) -> pd.Series:
    """Load the hourly counts of one junction.

    The file must have the columns ``datetime`` and ``vehicles``. Models check the rest
    when fitting: whole hours, no duplicate datetimes, non-negative counts and at least one
    full week of consecutive hours.

    Args:
        path: CSV file with the counts of a single junction.

    Returns:
        Vehicle counts indexed by datetime and sorted by time.

    Raises:
        ValueError: If a column is missing.
    """
    frame = pd.read_csv(path)
    missing = {DATETIME_COLUMN, VEHICLES_COLUMN} - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")

    counts = frame.set_index(pd.to_datetime(frame[DATETIME_COLUMN]))[VEHICLES_COLUMN]
    return counts.sort_index()

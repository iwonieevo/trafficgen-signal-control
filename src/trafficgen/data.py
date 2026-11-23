"""Read hourly vehicle counts from CSV files.

Two formats are used:

- Historical counts of one junction, the input of the junction counts models:
  ``datetime,vehicles``.
- Counts of several junctions, the output of the junction counts and the input of the
  network flows: ``datetime`` and one column per junction id.
"""

from pathlib import Path

import pandas as pd

DATETIME_COLUMN = "datetime"
VEHICLES_COLUMN = "vehicles"


def load_counts(path: str | Path) -> pd.Series:
    """Load the historical hourly counts of one junction.

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

    index = pd.DatetimeIndex(frame[DATETIME_COLUMN], name=DATETIME_COLUMN)
    counts = pd.Series(frame[VEHICLES_COLUMN].to_numpy(), index=index, name=VEHICLES_COLUMN)
    return counts.sort_index()


def load_junction_counts(path: str | Path) -> pd.DataFrame:
    """Load hourly counts of several junctions, one column per junction.

    Args:
        path: CSV file with a ``datetime`` column and one column per junction id.

    Returns:
        Counts indexed by datetime and sorted by time, with junction ids as columns.

    Raises:
        ValueError: If the ``datetime`` column is missing.
    """
    frame = pd.read_csv(path)
    if DATETIME_COLUMN not in frame.columns:
        raise ValueError(f"{path} is missing the column {DATETIME_COLUMN!r}")
    frame.index = pd.DatetimeIndex(frame.pop(DATETIME_COLUMN), name=DATETIME_COLUMN)
    frame.columns = frame.columns.astype(str)
    return frame.sort_index()

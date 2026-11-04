"""Load hourly vehicle counts from CSV files."""

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {"DateTime", "Junction", "Vehicles"}


def load_junction_counts(path: str | Path, junction: int) -> pd.Series:
    """Load the hourly counts of one junction.

    Args:
        path: CSV file with the columns ``DateTime``, ``Junction`` and ``Vehicles``.
        junction: Value of the ``Junction`` column to select.

    Returns:
        Vehicle counts indexed by hour and sorted by time.

    Raises:
        ValueError: If columns are missing or the junction has no rows.
    """
    frame = pd.read_csv(path, parse_dates=["DateTime"])
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")

    rows = frame[frame["Junction"] == junction]
    if rows.empty:
        raise ValueError(f"{path} has no rows for junction {junction}")

    counts = rows.set_index("DateTime")["Vehicles"].sort_index()
    counts.name = f"junction_{junction}"
    return counts

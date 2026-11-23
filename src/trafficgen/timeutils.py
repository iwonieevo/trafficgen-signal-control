"""Time constants and hourly ranges shared by both parts of the generator."""

from datetime import datetime

import pandas as pd

HOURS_PER_WEEK = 7 * 24
SECONDS_PER_HOUR = 3600

TimeLike = str | datetime | pd.Timestamp


def hourly_range(start: TimeLike, end: TimeLike) -> pd.DatetimeIndex:
    """Build the hours of a time range, including ``start`` and excluding ``end``.

    Args:
        start: First hour of the range.
        end: Hour right after the last hour of the range.

    Returns:
        One timestamp per hour.

    Raises:
        ValueError: If a bound is not a whole hour or is timezone-aware, or if ``end``
            is not after ``start``.
    """
    first, stop = pd.Timestamp(start), pd.Timestamp(end)
    for bound in (first, stop):
        if bound.tz is not None:
            raise ValueError(f"expected a naive datetime: {bound}")
        if bound != bound.floor("h"):
            raise ValueError(f"expected a whole hour: {bound}")
    if stop <= first:
        raise ValueError(f"end must be after start: {first} to {stop}")
    return pd.date_range(first, stop, freq="h", inclusive="left", name="datetime")

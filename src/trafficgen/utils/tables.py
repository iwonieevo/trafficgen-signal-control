"""Helpers that build long-format tables."""

from collections.abc import Sequence

import numpy as np
import pandas as pd


def hourly_long_table(
    hours: pd.DatetimeIndex,
    key_columns: dict[str, Sequence[object] | np.ndarray],
    value_columns: dict[str, np.ndarray],
) -> pd.DataFrame:
    item_count = len(next(iter(key_columns.values())))
    table: dict[str, object] = {"datetime": np.repeat(hours, item_count)}
    for column_name, keys in key_columns.items():
        table[column_name] = np.tile(np.asarray(keys), len(hours))
    for column_name, values_per_hour in value_columns.items():
        table[column_name] = values_per_hour.ravel()
    return pd.DataFrame(table)

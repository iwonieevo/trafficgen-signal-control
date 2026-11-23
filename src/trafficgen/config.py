"""Read the TOML config file shared by both parts of the generator.

One file describes a whole setup. Each part reads and checks only its own sections:

- ``[[junctions]]``: read by both parts. Both use ``id``, only junction counts uses ``data``.
- ``[counts]``: junction counts.
- ``[flows]``, ``[[roads]]`` and ``[[turns]]``: network flows.

The format is described in docs/traffic-generation.md.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import MISSING, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

SECTIONS = ("junctions", "counts", "flows", "roads", "turns")


def read_config(path: str | Path) -> dict[str, Any]:
    """Read a config file and check its top-level sections.

    Args:
        path: TOML config file.

    Returns:
        The parsed file.

    Raises:
        ValueError: If the file has a section that no part reads, for example a typo.
    """
    with Path(path).open("rb") as file:
        config_tables = tomllib.load(file)
    unknown = sorted(set(config_tables) - set(SECTIONS))
    if unknown:
        raise ValueError(f"{path}: unknown sections {unknown}, allowed: {list(SECTIONS)}")
    return config_tables


def junction_ids(config_tables: Mapping[str, Any]) -> tuple[str, ...]:
    """Read the ids of the junctions, which both parts use as keys.

    Args:
        config_tables: A parsed config file.

    Returns:
        Junction ids in the order of the file.

    Raises:
        ValueError: If there are no junctions, a junction has no id, or two share an id.
    """
    tables = config_tables.get("junctions", [])
    if not tables:
        raise ValueError("the config defines no junctions")
    if any("id" not in table for table in tables):
        raise ValueError("every junction needs an 'id'")
    ids = tuple(str(table["id"]) for table in tables)
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate junction ids: {list(ids)}")
    return ids


def parse_table[T: DataclassInstance](
    table: Mapping[str, Any],
    dataclass_type: type[T],
    table_name: str,
    renamed_keys: Mapping[str, str] | None = None,
) -> T:
    """Turn one TOML table into a dataclass, rejecting unknown and missing keys.

    Args:
        table: Keys and values of the table.
        dataclass_type: Dataclass to create. Its fields are the allowed keys, and fields
            without a default are required.
        table_name: Name of the table in error messages, for example ``"road 'A_B'"``.
        renamed_keys: TOML keys that differ from the field names, for example
            ``{"from": "from_junction"}``.

    Returns:
        The created dataclass. Its own checks run as usual.

    Raises:
        ValueError: If a key is unknown or a required key is missing.
    """
    renamed_keys = renamed_keys or {}
    key_of_field = {field_name: key for key, field_name in renamed_keys.items()}
    dataclass_fields = fields(dataclass_type)
    allowed_keys = {key_of_field.get(field.name, field.name) for field in dataclass_fields}
    required_keys = {
        key_of_field.get(field.name, field.name)
        for field in dataclass_fields
        if field.default is MISSING and field.default_factory is MISSING
    }

    unknown_keys = sorted(set(table) - allowed_keys)
    if unknown_keys:
        raise ValueError(
            f"{table_name} has unknown keys {unknown_keys}, allowed: {sorted(allowed_keys)}"
        )
    missing_keys = sorted(required_keys - set(table))
    if missing_keys:
        raise ValueError(f"{table_name} is missing {missing_keys}")
    return dataclass_type(**{renamed_keys.get(key, key): value for key, value in table.items()})

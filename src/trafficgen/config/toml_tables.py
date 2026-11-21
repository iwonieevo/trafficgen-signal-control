"""Turn tables of a parsed TOML file into dataclasses, rejecting unknown and missing keys."""

from collections.abc import Mapping
from dataclasses import MISSING, fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


def parse_toml_table[T: DataclassInstance](
    table: Mapping[str, Any],
    dataclass_type: type[T],
    table_name: str,
    renamed_keys: Mapping[str, str] | None = None,
) -> T:
    """``renamed_keys`` maps TOML keys to field names, for example ``{"from": "from_junction"}``."""
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

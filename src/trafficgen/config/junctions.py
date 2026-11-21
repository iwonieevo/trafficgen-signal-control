"""Describe junctions in a config file and build one traffic generator per junction.

This config covers only what layer 1 needs: which junctions exist and which historical
counts each one is fitted on. The road network of layer 2 is read by ``trafficgen.config.network``.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from trafficgen.data import load_counts
from trafficgen.models.hourly_counts import HourlyCountModel, StatisticalCountModel


@dataclass(frozen=True)
class JunctionConfig:
    """Input data of one junction.

    Attributes:
        id: Unique name of the junction.
        data: CSV file with the historical counts of this junction, with the columns
            ``datetime`` and ``vehicles``.
    """

    id: str
    data: Path


@dataclass(frozen=True)
class TrafficConfig:
    """Settings of a traffic generation setup.

    Attributes:
        junctions: The junctions to generate traffic for.
    """

    junctions: tuple[JunctionConfig, ...]


def load_config(path: str | Path) -> TrafficConfig:
    """Read a TOML config file.

    Args:
        path: Config file. Relative data paths inside it are resolved against the
            directory of the config file.

    Returns:
        The parsed config.

    Raises:
        ValueError: If there are no junctions or if two junctions share an id.
    """
    path = Path(path)
    with path.open("rb") as file:
        raw = tomllib.load(file)
    return TrafficConfig(junctions=parse_junctions(raw, path))


def parse_junctions(config_tables: dict, config_path: Path) -> tuple[JunctionConfig, ...]:
    junctions = tuple(
        JunctionConfig(id=table["id"], data=(config_path.parent / table["data"]).resolve())
        for table in config_tables.get("junctions", [])
    )
    ids = [junction.id for junction in junctions]
    if not ids:
        raise ValueError(f"{config_path} defines no junctions")
    if len(set(ids)) != len(ids):
        raise ValueError(f"{config_path} has duplicate junction ids: {ids}")
    return junctions


def build_generators(config: TrafficConfig) -> dict[str, HourlyCountModel]:
    """Fit one independent statistical model per configured junction.

    Args:
        config: The junctions and their input data.

    Returns:
        Fitted models by junction id.
    """
    return {
        junction.id: StatisticalCountModel().fit(load_counts(junction.data))
        for junction in config.junctions
    }

"""Describe junctions in a config file and build one traffic generator per junction.

The config currently covers only what layer 1 needs: which junctions exist and which
historical counts each one is fitted on.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from trafficgen.data import load_junction_counts
from trafficgen.models import HourlyCountModel, StatisticalCountModel


@dataclass(frozen=True)
class JunctionConfig:
    """Input data of one junction.

    Attributes:
        id: Unique name of the junction.
        data: CSV file with the historical counts.
        source_junction: Value of the ``Junction`` column to read from that file.
    """

    id: str
    data: Path
    source_junction: int


@dataclass(frozen=True)
class TrafficConfig:
    """Settings of a traffic generation setup.

    Attributes:
        junctions: The junctions to generate traffic for.
        country: ISO country code of the holiday calendar, or ``None`` for no holidays.
    """

    junctions: tuple[JunctionConfig, ...]
    country: str | None = "US"


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

    junctions = tuple(
        JunctionConfig(
            id=item["id"],
            data=(path.parent / item["data"]).resolve(),
            source_junction=item["source_junction"],
        )
        for item in raw.get("junctions", [])
    )
    ids = [junction.id for junction in junctions]
    if not ids:
        raise ValueError(f"{path} defines no junctions")
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path} has duplicate junction ids: {ids}")
    return TrafficConfig(junctions=junctions, country=raw.get("country", "US"))


def build_generators(config: TrafficConfig) -> dict[str, HourlyCountModel]:
    """Fit one independent statistical model per configured junction.

    Args:
        config: The junctions and their input data.

    Returns:
        Fitted models by junction id.
    """
    return {
        junction.id: StatisticalCountModel(country=config.country).fit(
            load_junction_counts(junction.data, junction.source_junction)
        )
        for junction in config.junctions
    }

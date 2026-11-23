"""The junction counts part of the config: the data of each junction and the volume scale.

Only ``[[junctions]]`` and ``[counts]`` are read here. The network sections are left to
``trafficgen.flows.config``.
"""

from dataclasses import dataclass, field
from pathlib import Path

from trafficgen.config import junction_ids, parse_table, read_config
from trafficgen.counts.models import StatisticalCountModel
from trafficgen.data import load_counts


@dataclass(frozen=True)
class JunctionData:
    """Historical data of one junction.

    Attributes:
        id: Unique name of the junction.
        data: CSV file with the historical counts of this junction, with the columns
            ``datetime`` and ``vehicles``.
    """

    id: str
    data: Path


@dataclass(frozen=True)
class CountSettings:
    """Settings of the ``[counts]`` section.

    Attributes:
        scale: Multiplier of the generated volume, for example to create more congestion
            in a simulation.
    """

    scale: float = 1.0

    def __post_init__(self) -> None:
        """Check the settings.

        Raises:
            ValueError: If ``scale`` is not positive.
        """
        if not self.scale > 0:
            raise ValueError(f"counts scale must be positive, not {self.scale}")


@dataclass(frozen=True)
class CountsConfig:
    """Everything the junction counts need from a config file.

    Attributes:
        junctions: The junctions to generate counts for, in the order of the file.
        settings: Settings of the ``[counts]`` section.
    """

    junctions: tuple[JunctionData, ...]
    settings: CountSettings = field(default_factory=CountSettings)

    @property
    def junction_ids(self) -> list[str]:
        """Ids of the junctions, in the order of the file."""
        return [junction.id for junction in self.junctions]


def load_counts_config(path: str | Path) -> CountsConfig:
    """Read the junction counts part of a config file.

    Args:
        path: TOML config file. Relative data paths inside it are resolved against the
            directory of the config file.

    Returns:
        The junctions with their data files and the ``[counts]`` settings.

    Raises:
        ValueError: If the junctions or the ``[counts]`` section are invalid. The message
            names the file.
    """
    path = Path(path)
    config_tables = read_config(path)
    try:
        junction_ids(config_tables)
        junctions = tuple(
            _parse_junction(table, path.parent) for table in config_tables["junctions"]
        )
        settings = parse_table(config_tables.get("counts", {}), CountSettings, "[counts]")
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None
    return CountsConfig(junctions=junctions, settings=settings)


def fit_count_models(config: CountsConfig) -> dict[str, StatisticalCountModel]:
    """Fit one statistical model per configured junction on its historical data.

    Args:
        config: The junctions and their data files.

    Returns:
        Fitted models by junction id, in the order of the config.
    """
    return {
        junction.id: StatisticalCountModel().fit(load_counts(junction.data))
        for junction in config.junctions
    }


def _parse_junction(table: dict, config_dir: Path) -> JunctionData:
    """Read one ``[[junctions]]`` table, resolving its data path.

    Args:
        table: The TOML table.
        config_dir: Directory of the config file.

    Returns:
        The junction and the absolute path of its data.
    """
    junction = parse_table(table, JunctionData, f"junction {table['id']!r}")
    return JunctionData(id=junction.id, data=(config_dir / junction.data).resolve())

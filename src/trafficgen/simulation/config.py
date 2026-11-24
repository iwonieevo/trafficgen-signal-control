"""The SUMO part of the config: the network file and how vehicles depart.

Only ``file`` of ``[network]`` and the ``[sumo]`` section are read here. The format is
described in docs/traffic-generation.md.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, get_args

from trafficgen.config import parse_table, read_config
from trafficgen.flows.config import NetworkSource

Departures = Literal["poisson", "uniform"]


@dataclass(frozen=True)
class SumoSettings:
    """Settings of the ``[sumo]`` section.

    Attributes:
        departures: How the vehicles of one hour depart. ``poisson``: at random times, so the
            number per hour varies around the flow. ``uniform``: evenly spaced, with the
            fractions of a vehicle carried over to the next hour, so the number per hour
            follows the flow as closely as whole vehicles can.
    """

    departures: Departures = "poisson"

    def __post_init__(self) -> None:
        """Check the settings.

        Raises:
            ValueError: If ``departures`` is unknown.
        """
        if self.departures not in get_args(Departures):
            raise ValueError(
                f"[sumo] departures must be one of {list(get_args(Departures))}, "
                f"not {self.departures!r}"
            )


@dataclass(frozen=True)
class SumoConfig:
    """What the SUMO input of a config needs.

    Attributes:
        net_file: Absolute path of the SUMO network file.
        settings: Settings of the ``[sumo]`` section.
    """

    net_file: Path
    settings: SumoSettings = field(default_factory=SumoSettings)


def load_sumo_config(path: str | Path) -> SumoConfig:
    """Read the SUMO part of a config file.

    Args:
        path: TOML config file. The network file is resolved against its directory.

    Returns:
        The network file and the settings.

    Raises:
        ValueError: If there is no ``[network]`` section, the network file does not exist, or
            ``[sumo]`` is invalid. The message names the file.
    """
    path = Path(path)
    config_tables = read_config(path)
    try:
        if "network" not in config_tables:
            raise ValueError("SUMO input needs the network file in a [network] section")
        source = parse_table(config_tables["network"], NetworkSource, "[network]")
        net_file = (path.parent / source.file).resolve()
        if not net_file.is_file():
            raise ValueError(f"[network] file not found: {net_file}")
        settings = parse_table(config_tables.get("sumo", {}), SumoSettings, "[sumo]")
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None
    return SumoConfig(net_file=net_file, settings=settings)

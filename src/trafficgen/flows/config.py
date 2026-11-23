"""The network flows part of the config: the network, its overrides and the solver settings.

Only ``id`` and ``node`` of ``[[junctions]]`` are read here, together with ``[network]``,
``[flows]``, ``[[roads]]`` and ``[[turns]]``. The format is described in
docs/network-flows.md.

The network comes from one of two places:

- With ``[network]``, roads and turns are read from a SUMO network file. ``[[roads]]`` and
  ``[[turns]]`` then only change values of single roads and turns.
- Without it, ``[[roads]]`` and ``[[turns]]`` describe the whole network.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from trafficgen.config import junction_ids, parse_table, read_config
from trafficgen.flows.network import FlowSettings, NetworkConfig, RoadConfig, TurnConfig
from trafficgen.flows.sumo_network import TURN_DIRECTIONS, read_sumo_network

DEFAULT_TURN_PREFERENCES = {"right": 0.15, "straight": 0.7, "left": 0.15}
ROAD_TOML_KEYS = {"from": "from_junction", "to": "to_junction"}
ROAD_OVERRIDE_KEYS = {"id", "preference", "through_share", "length_m", "lanes", "speed_limit_kmh"}
TURN_OVERRIDE_KEYS = {"from_road", "to_road", "preference"}


@dataclass(frozen=True)
class NetworkSource:
    """Settings of the ``[network]`` section.

    Attributes:
        file: SUMO network file, relative to the config file.
        turn_preferences: Preference of each turn direction, ``right``, ``straight`` and
            ``left``. Directions that are left out keep their default.
    """

    file: str
    turn_preferences: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Check the turn preferences.

        Raises:
            ValueError: If a direction is unknown or a preference is negative.
        """
        unknown = sorted(set(self.turn_preferences) - set(TURN_DIRECTIONS))
        if unknown:
            raise ValueError(
                f"[network] turn_preferences has unknown directions {unknown}, "
                f"allowed: {list(TURN_DIRECTIONS)}"
            )
        for direction, preference in self.turn_preferences.items():
            if not preference >= 0:
                raise ValueError(f"[network] turn preference of {direction!r} is negative")


def load_network_config(path: str | Path) -> NetworkConfig:
    """Read the network flows part of a config file.

    Args:
        path: TOML config file. The network file is resolved against its directory.

    Returns:
        The checked network.

    Raises:
        ValueError: If the network, its overrides or the ``[flows]`` section are invalid. The
            message names the file.
    """
    path = Path(path)
    config_tables = read_config(path)
    try:
        if "network" in config_tables:
            roads, turns = _network_from_file(config_tables, path.parent)
        else:
            roads = tuple(_parse_road(table) for table in config_tables.get("roads", []))
            turns = tuple(_parse_turn(table) for table in config_tables.get("turns", []))
        return NetworkConfig(
            junction_ids=junction_ids(config_tables),
            roads=roads,
            turns=turns,
            settings=parse_table(config_tables.get("flows", {}), FlowSettings, "[flows]"),
        )
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None


def _network_from_file(
    config_tables: dict[str, Any], config_dir: Path
) -> tuple[tuple[RoadConfig, ...], tuple[TurnConfig, ...]]:
    """Read the roads and turns from the SUMO network file and apply the overrides.

    Args:
        config_tables: The parsed config file.
        config_dir: Directory of the config file.

    Returns:
        The roads and the turns.

    Raises:
        ValueError: If the file is missing, a junction has no node, or an override is invalid.
    """
    source = parse_table(config_tables["network"], NetworkSource, "[network]")
    net_file = (config_dir / source.file).resolve()
    if not net_file.is_file():
        raise ValueError(f"[network] file not found: {net_file}")

    junction_by_node: dict[str, str] = {}
    for table in config_tables.get("junctions", []):
        if "node" not in table:
            raise ValueError(f"junction {table.get('id')!r} needs a 'node' of {source.file}")
        node = str(table["node"])
        if node in junction_by_node:
            raise ValueError(f"node {node!r} is used by two junctions")
        junction_by_node[node] = str(table["id"])

    preferences = DEFAULT_TURN_PREFERENCES | source.turn_preferences
    roads, turns = read_sumo_network(net_file, junction_by_node, preferences)
    return (
        _override_roads(roads, config_tables.get("roads", [])),
        _override_turns(turns, config_tables.get("turns", [])),
    )


def _override_roads(
    roads: tuple[RoadConfig, ...], tables: list[dict[str, Any]]
) -> tuple[RoadConfig, ...]:
    """Change values of roads read from the network file.

    Raises:
        ValueError: If a table names an unknown road or a key that cannot be changed.
    """
    roads_by_id = {road.id: road for road in roads}
    for table in tables:
        name = f"road {table.get('id', '?')!r}"
        if table.get("id") not in roads_by_id:
            raise ValueError(f"{name} is not in the network file")
        not_allowed = sorted(set(table) - ROAD_OVERRIDE_KEYS)
        if not_allowed:
            raise ValueError(
                f"{name}: {not_allowed} cannot be changed, allowed: {sorted(ROAD_OVERRIDE_KEYS)}"
            )
        changes = {key: value for key, value in table.items() if key != "id"}
        roads_by_id[table["id"]] = replace(roads_by_id[table["id"]], **changes)
    return tuple(roads_by_id.values())


def _override_turns(
    turns: tuple[TurnConfig, ...], tables: list[dict[str, Any]]
) -> tuple[TurnConfig, ...]:
    """Change the preferences of turns read from the network file.

    Raises:
        ValueError: If a table names a turn that the network does not have, or another key.
    """
    turns_by_roads = {(turn.from_road, turn.to_road): turn for turn in turns}
    for table in tables:
        key = (str(table.get("from_road")), str(table.get("to_road")))
        name = f"turn {key[0]!r} -> {key[1]!r}"
        if key not in turns_by_roads:
            raise ValueError(f"{name} is not a connection of the network file")
        not_allowed = sorted(set(table) - TURN_OVERRIDE_KEYS)
        if not_allowed:
            raise ValueError(f"{name}: {not_allowed} cannot be changed, only 'preference'")
        if "preference" in table:
            turns_by_roads[key] = replace(turns_by_roads[key], preference=table["preference"])
    return tuple(turns_by_roads.values())


def _parse_road(road_table: dict) -> RoadConfig:
    """Read one ``[[roads]]`` table, where ``from`` and ``to`` name the junctions."""
    table_name = f"road {road_table.get('id', '?')!r}"
    return parse_table(road_table, RoadConfig, table_name, ROAD_TOML_KEYS)


def _parse_turn(turn_table: dict) -> TurnConfig:
    """Read one ``[[turns]]`` table."""
    table_name = f"turn {turn_table.get('from_road', '?')!r} -> {turn_table.get('to_road', '?')!r}"
    return parse_table(turn_table, TurnConfig, table_name)

"""Read the roads and turns of a network from a SUMO ``.net.xml`` file.

Only the file is read: SUMO itself is not needed. Road ids are the edge ids, so flows can be
fed back into the same network. Dead-end nodes are the boundary of the network, and every
other node must stand for a junction of the config.
"""

import xml.etree.ElementTree as ElementTree
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from trafficgen.flows.network import KMH_PER_M_PER_S, RoadConfig, TurnConfig

TURN_BY_SUMO_DIRECTION = {"r": "right", "R": "right", "s": "straight", "l": "left", "L": "left"}
TURN_DIRECTIONS = ("right", "straight", "left")


def read_sumo_network(
    net_file: Path,
    junction_by_node: Mapping[str, str],
    turn_preferences: Mapping[str, float],
) -> tuple[tuple[RoadConfig, ...], tuple[TurnConfig, ...]]:
    """Read the roads and turns of a SUMO network.

    Lengths, lanes and speed limits come from the lanes of each edge, and turn directions
    from the ``dir`` of each connection. U-turns are left out. Entry roads get a preference
    of 1, so the entry roads of a junction share its entry flow equally.

    Args:
        net_file: SUMO network file.
        junction_by_node: Junction id of every SUMO node that is not a dead end.
        turn_preferences: Preference of each direction: ``right``, ``straight`` and ``left``.
            When several turns from one road have the same direction, they share it.

    Returns:
        The roads and the turns of the network.

    Raises:
        ValueError: If a node that is not a dead end has no junction, or a junction names a
            node that is not in the network.
    """
    network = ElementTree.parse(net_file).getroot()
    nodes = {node.get("id"): node.get("type") for node in network.iter("junction")}
    unknown = sorted(set(junction_by_node) - set(nodes))
    if unknown:
        raise ValueError(f"{net_file.name} has no nodes {unknown}")

    def junction_of(node: str | None) -> str | None:
        """Return the junction of a node, or None for the boundary of the network."""
        if nodes.get(node) == "dead_end":
            return None
        if node is None or node not in junction_by_node:
            raise ValueError(
                f"node {node!r} of {net_file.name} is not a dead end and no junction has "
                f"node = {node!r}"
            )
        return junction_by_node[node]

    roads = []
    for edge in network.iter("edge"):
        if edge.get("function") == "internal":
            continue
        from_junction, to_junction = junction_of(edge.get("from")), junction_of(edge.get("to"))
        if from_junction is None and to_junction is None:
            continue
        lanes = edge.findall("lane")
        roads.append(
            RoadConfig(
                id=str(edge.get("id")),
                from_junction=from_junction,
                to_junction=to_junction,
                preference=1.0 if from_junction is None else None,
                length_m=float(lanes[0].get("length", "nan")),
                lanes=len(lanes),
                speed_limit_kmh=round(float(lanes[0].get("speed", "nan")) * KMH_PER_M_PER_S, 1),
            )
        )
    return tuple(roads), _read_turns(network, {road.id for road in roads}, turn_preferences)


def _read_turns(
    network: ElementTree.Element, road_ids: set[str], turn_preferences: Mapping[str, float]
) -> tuple[TurnConfig, ...]:
    """Read one turn per pair of connected roads, with the preference of its direction.

    Args:
        network: Root of the network file.
        road_ids: Ids of the roads of the network.
        turn_preferences: Preference of each direction.

    Returns:
        The turns, in the order of the first connection of each pair.
    """
    direction_by_target_by_road: dict[str, dict[str, str]] = defaultdict(dict)
    for connection in network.iter("connection"):
        from_road, to_road = connection.get("from"), connection.get("to")
        direction = TURN_BY_SUMO_DIRECTION.get(connection.get("dir", ""))
        if from_road in road_ids and to_road in road_ids and direction is not None:
            assert from_road is not None and to_road is not None
            direction_by_target_by_road[from_road][to_road] = direction

    turns = []
    for from_road, direction_by_target in direction_by_target_by_road.items():
        targets_per_direction = defaultdict(int)
        for direction in direction_by_target.values():
            targets_per_direction[direction] += 1
        turns += [
            TurnConfig(
                from_road=from_road,
                to_road=to_road,
                preference=turn_preferences[direction] / targets_per_direction[direction],
            )
            for to_road, direction in direction_by_target.items()
        ]
    return tuple(turns)

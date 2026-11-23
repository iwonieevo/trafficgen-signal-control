"""Generate a traffic generator config from a SUMO network file.

Road ids are the edge ids of the network, so the network flows can be fed into the same
SUMO scenario. Dead-end nodes are the boundary of the network, and every other node needs a
``--junction NODE=JUNCTION`` mapping. The first lines of the written file hold the command
that wrote it.
"""

import argparse
import shlex
import sys
import xml.etree.ElementTree as ElementTree
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import tomli_w

from trafficgen import CountSettings, FlowSettings, load_counts_config, load_network_config
from trafficgen.flows.config import KMH_PER_M_PER_S

DEFAULT_DATA_TEMPLATE = "../data/processed/kaggle_junction_{number}.csv"
DEFAULT_TURN_PREFERENCES = (0.15, 0.7, 0.15)
TURN_BY_SUMO_DIRECTION = {"r": "right", "R": "right", "s": "straight", "l": "left", "L": "left"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line arguments.

    Args:
        argv: Arguments without the program name.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("net_file", type=Path, help="SUMO .net.xml file")
    parser.add_argument(
        "--junction",
        action="append",
        required=True,
        metavar="NODE=JUNCTION",
        help="SUMO node and the junction id it gets, e.g. J0=J1. Repeat for every node",
    )
    parser.add_argument(
        "--turn-preferences",
        type=float,
        nargs=3,
        default=DEFAULT_TURN_PREFERENCES,
        metavar=("RIGHT", "STRAIGHT", "LEFT"),
        help="preference of each turn direction (default: 0.15 0.7 0.15)",
    )
    parser.add_argument(
        "--data-template",
        default=DEFAULT_DATA_TEMPLATE,
        help="data path relative to the config; {number} is the position of the --junction",
    )
    parser.add_argument("--output", type=Path, required=True, help="TOML file to write")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> dict:
    """Read the roads and turns of the SUMO network into the tables of a config.

    Lengths, lanes and speed limits come from the lanes of each edge, turn directions from
    the ``dir`` of each connection. Entry roads of a junction get equal preferences.

    Args:
        args: The parsed arguments.

    Returns:
        The tables of the config file.

    Raises:
        SystemExit: If a node that is not a dead end has no ``--junction`` mapping.
    """
    junction_by_node = dict(_parse_node_mapping(mapping) for mapping in args.junction)
    network = ElementTree.parse(args.net_file).getroot()
    boundary_nodes = {
        node.get("id") for node in network.iter("junction") if node.get("type") == "dead_end"
    }

    def junction_of(node: str | None) -> str | None:
        """Return the junction id of a SUMO node, or None for the boundary."""
        if node in boundary_nodes:
            return None
        if node not in junction_by_node:
            sys.exit(f"SUMO node {node!r} has no --junction mapping, e.g. --junction {node}=J1")
        return junction_by_node[node]

    roads = []
    for edge in network.iter("edge"):
        if edge.get("function") == "internal":
            continue
        from_junction, to_junction = junction_of(edge.get("from")), junction_of(edge.get("to"))
        if from_junction is None and to_junction is None:
            continue
        lanes = edge.findall("lane")
        road = {
            "id": edge.get("id"),
            "from": from_junction,
            "to": to_junction,
            "preference": 1.0 if from_junction is None else None,
            "length_m": float(lanes[0].get("length", "nan")),
            "lanes": len(lanes),
            "speed_limit_kmh": round(float(lanes[0].get("speed", "nan")) * KMH_PER_M_PER_S, 1),
        }
        roads.append({key: value for key, value in road.items() if value is not None})

    road_ids = {road["id"] for road in roads}
    turn_by_target_by_road: dict[str, dict[str, str]] = defaultdict(dict)
    for connection in network.iter("connection"):
        from_road, to_road = connection.get("from"), connection.get("to")
        turn = TURN_BY_SUMO_DIRECTION.get(connection.get("dir", ""))
        if from_road in road_ids and to_road in road_ids and turn is not None:
            assert from_road is not None and to_road is not None
            turn_by_target_by_road[from_road][to_road] = turn
    preference_by_turn: dict[str, float] = dict(
        zip(("right", "straight", "left"), args.turn_preferences, strict=True)
    )
    turns = [
        {"from_road": from_road, "to_road": to_road, "preference": preference_by_turn[turn]}
        for from_road, turn_by_target in turn_by_target_by_road.items()
        for to_road, turn in turn_by_target.items()
    ]

    return {
        "junctions": [
            {"id": junction, "data": args.data_template.format(number=number)}
            for number, junction in enumerate(junction_by_node.values(), start=1)
        ],
        "counts": asdict(CountSettings()),
        "flows": asdict(FlowSettings()),
        "roads": roads,
        "turns": turns,
    }


def render_config(config: dict, argv: list[str]) -> str:
    """Write the config tables as TOML, after a header with the command that wrote them.

    Args:
        config: The tables of the config file.
        argv: The arguments of the command. ``--output`` is left out of the header.

    Returns:
        The text of the config file.
    """
    header = (
        "# Generated by scripts/generate_config.py. Regenerate instead of editing:\n"
        "# uv run python scripts/generate_config.py "
        f"{shlex.join(_without_output_option(argv))} --output <this file>\n\n"
    )
    sections = []
    for table_name, tables in config.items():
        if isinstance(tables, list):
            sections += [f"[[{table_name}]]\n{tomli_w.dumps(table)}" for table in tables]
        else:
            sections.append(f"[{table_name}]\n{tomli_w.dumps(tables)}")
    return header + "\n".join(sections)


def main(argv: list[str] | None = None) -> None:
    """Write the config and check that both parts of the generator can read it.

    Args:
        argv: Arguments without the program name. Defaults to the command line.

    Raises:
        SystemExit: If the arguments or the generated config are invalid.
    """
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    config = build_config(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_config(config, argv), newline="\n")
    try:
        load_counts_config(args.output)
        load_network_config(args.output)
    except ValueError as error:
        sys.exit(f"the generated config is invalid: {error}")
    print(f"wrote {args.output}")


def _parse_node_mapping(mapping: str) -> tuple[str, str]:
    """Split a ``NODE=JUNCTION`` argument.

    Raises:
        SystemExit: If the argument has no ``=`` or an empty side.
    """
    node, separator, junction = mapping.partition("=")
    if not separator or not node or not junction:
        sys.exit(f"--junction expects NODE=JUNCTION, not {mapping!r}")
    return node, junction


def _without_output_option(argv: list[str]) -> list[str]:
    """Remove ``--output`` and its value, so the header does not depend on the path."""
    kept, skip_next = [], False
    for argument in argv:
        if skip_next:
            skip_next = False
        elif argument == "--output":
            skip_next = True
        elif not argument.startswith("--output="):
            kept.append(argument)
    return kept


if __name__ == "__main__":
    main()

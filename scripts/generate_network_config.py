"""Generate a layer 2 network config, either as a grid or from a SUMO network file."""

import argparse
import shlex
import sys
import xml.etree.ElementTree as ElementTree
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import tomli_w

from trafficgen import BalanceSettings, load_network_config

DEFAULT_DATA_TEMPLATE = "../data/processed/kaggle_junction_{number}.csv"
DEFAULT_TURN_RATIOS = (0.15, 0.7, 0.15)
KMH_PER_M_PER_S = 3.6

GRID_STEPS = {"north": (-1, 0), "east": (0, 1), "south": (1, 0), "west": (0, -1)}
TARGET_BY_TURN_FROM = {
    "north": {"right": "west", "straight": "south", "left": "east"},
    "south": {"right": "east", "straight": "north", "left": "west"},
    "east": {"right": "north", "straight": "west", "left": "south"},
    "west": {"right": "south", "straight": "east", "left": "north"},
}
TURN_BY_SUMO_DIRECTION = {"r": "right", "R": "right", "s": "straight", "l": "left", "L": "left"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    grid = subparsers.add_parser("grid", help="rows x columns of junctions")
    grid.add_argument("--rows", type=int, required=True)
    grid.add_argument("--cols", type=int, required=True)
    grid.add_argument("--length-m", type=float, default=None)
    grid.add_argument("--lanes", type=int, default=None)
    grid.add_argument("--speed-limit-kmh", type=float, default=None)
    grid.add_argument("--through-share", type=float, default=1.0)

    sumo = subparsers.add_parser("from-sumo", help="roads and turns of a SUMO .net.xml file")
    sumo.add_argument("net_file", type=Path)
    sumo.add_argument(
        "--junction",
        action="append",
        required=True,
        metavar="NODE=JUNCTION",
        help="SUMO node and the data junction it stands for, e.g. J0=J1. Repeat per node",
    )

    for subparser in (grid, sumo):
        subparser.add_argument(
            "--turn-ratios",
            type=float,
            nargs=3,
            default=DEFAULT_TURN_RATIOS,
            metavar=("RIGHT", "STRAIGHT", "LEFT"),
        )
        subparser.add_argument(
            "--data-template",
            default=DEFAULT_DATA_TEMPLATE,
            help="data path relative to the config; {number} is the junction's 1-based position",
        )
        subparser.add_argument("--output", type=Path, required=True, help="TOML file to write")
    return parser.parse_args(argv)


def build_grid_config(args: argparse.Namespace) -> dict:
    def junction_id(row: int, col: int) -> str:
        return f"J{row * args.cols + col + 1}"

    def neighbour(row: int, col: int, direction: str) -> str | None:
        row_step, col_step = GRID_STEPS[direction]
        next_row, next_col = row + row_step, col + col_step
        if 0 <= next_row < args.rows and 0 <= next_col < args.cols:
            return junction_id(next_row, next_col)
        return None

    road_attributes = _without_none(
        {"length_m": args.length_m, "lanes": args.lanes, "speed_limit_kmh": args.speed_limit_kmh}
    )
    cells = [(row, col) for row in range(args.rows) for col in range(args.cols)]
    junction_ids = [junction_id(row, col) for row, col in cells]
    entry_roads, exit_roads, internal_roads, turns = [], [], [], []

    for row, col in cells:
        junction = junction_id(row, col)
        neighbours = {direction: neighbour(row, col, direction) for direction in GRID_STEPS}
        outside_directions = [d for d, other in neighbours.items() if other is None]

        incoming_road = {
            direction: f"{other or direction}_{junction}" for direction, other in neighbours.items()
        }
        outgoing_road = {
            direction: f"{junction}_{other or direction}" for direction, other in neighbours.items()
        }

        for direction in outside_directions:
            entry_weight = 1 / len(outside_directions)
            entry_roads.append(
                {"id": incoming_road[direction], "to": junction, "weight": entry_weight}
                | road_attributes
            )
            exit_roads.append({"id": outgoing_road[direction], "from": junction} | road_attributes)
        for direction, other in neighbours.items():
            if other is not None:
                internal_roads.append(
                    {"id": outgoing_road[direction], "from": junction, "to": other}
                    | road_attributes
                    | {"through_share": args.through_share}
                )
        for arriving_from, targets in TARGET_BY_TURN_FROM.items():
            ratios = _ratios_by_target(
                {outgoing_road[target]: turn for turn, target in targets.items()}, args.turn_ratios
            )
            turns += [
                {"from_road": incoming_road[arriving_from], "to_road": to_road, "ratio": ratio}
                for to_road, ratio in ratios.items()
            ]

    return _network_config(
        junction_ids, entry_roads + exit_roads + internal_roads, turns, args.data_template
    )


def build_config_from_sumo(args: argparse.Namespace) -> dict:
    junction_by_node = dict(_parse_node_mapping(mapping) for mapping in args.junction)
    network = ElementTree.parse(args.net_file).getroot()
    boundary_nodes = {
        node.get("id") for node in network.iter("junction") if node.get("type") == "dead_end"
    }

    def junction_of(node: str | None) -> str | None:
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
        roads.append(
            _without_none(
                {
                    "id": edge.get("id"),
                    "from": from_junction,
                    "to": to_junction,
                    "length_m": float(lanes[0].get("length", "nan")),
                    "lanes": len(lanes),
                    "speed_limit_kmh": round(
                        float(lanes[0].get("speed", "nan")) * KMH_PER_M_PER_S, 1
                    ),
                }
            )
        )

    entry_count_by_junction = defaultdict(int)
    for road in roads:
        if "from" not in road:
            entry_count_by_junction[road["to"]] += 1
    for road in roads:
        if "from" not in road:
            road["weight"] = 1 / entry_count_by_junction[road["to"]]

    road_ids = {road["id"] for road in roads}
    turn_by_target_by_road: dict[str, dict[str, str]] = defaultdict(dict)
    for connection in network.iter("connection"):
        from_road, to_road = connection.get("from"), connection.get("to")
        turn = TURN_BY_SUMO_DIRECTION.get(connection.get("dir", ""))
        if from_road is None or to_road is None or turn is None:
            continue
        if from_road in road_ids and to_road in road_ids:
            turn_by_target_by_road[from_road][to_road] = turn
    turns = [
        {"from_road": from_road, "to_road": to_road, "ratio": ratio}
        for from_road, turn_by_target in turn_by_target_by_road.items()
        for to_road, ratio in _ratios_by_target(turn_by_target, args.turn_ratios).items()
    ]
    return _network_config(list(junction_by_node.values()), roads, turns, args.data_template)


def render_config(config: dict, argv: list[str]) -> str:
    header = (
        "# Generated by scripts/generate_network_config.py. Regenerate instead of editing:\n"
        "# uv run python scripts/generate_network_config.py "
        f"{shlex.join(_without_output_option(argv))} --output <this file>\n\n"
    )
    plain_values = {key: value for key, value in config.items() if not isinstance(value, list)}
    sections = [tomli_w.dumps(plain_values)]
    for table_name, tables in config.items():
        if isinstance(tables, list):
            sections += [f"[[{table_name}]]\n{tomli_w.dumps(table)}" for table in tables]
    return header + "\n".join(sections)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    config = build_grid_config(args) if args.mode == "grid" else build_config_from_sumo(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_config(config, argv), newline="\n")
    try:
        load_network_config(args.output)
    except ValueError as error:
        sys.exit(f"the generated config is invalid: {error}")
    print(f"wrote {args.output}")


def _network_config(
    junction_ids: list[str], roads: list[dict], turns: list[dict], data_template: str
) -> dict:
    return {
        "scale": 1.0,
        "balance": asdict(BalanceSettings()),
        "junctions": [
            {"id": junction, "data": data_template.format(number=number)}
            for number, junction in enumerate(junction_ids, start=1)
        ],
        "roads": roads,
        "turns": turns,
    }


def _ratios_by_target(
    turn_by_target: dict[str, str], turn_ratios: tuple[float, float, float]
) -> dict[str, float]:
    ratio_by_turn: dict[str, float] = dict(
        zip(("right", "straight", "left"), turn_ratios, strict=True)
    )
    targets_by_turn: dict[str, list[str]] = defaultdict(list)
    for target, turn in turn_by_target.items():
        targets_by_turn[turn].append(target)
    available_total = sum(ratio_by_turn[turn] for turn in targets_by_turn)
    return {
        target: ratio_by_turn[turn] / available_total / len(targets_by_turn[turn])
        for target, turn in turn_by_target.items()
    }


def _parse_node_mapping(mapping: str) -> tuple[str, str]:
    node, separator, junction = mapping.partition("=")
    if not separator or not node or not junction:
        sys.exit(f"--junction expects NODE=JUNCTION, not {mapping!r}")
    return node, junction


def _without_output_option(argv: list[str]) -> list[str]:
    kept, skip_next = [], False
    for argument in argv:
        if skip_next:
            skip_next = False
        elif argument == "--output":
            skip_next = True
        elif not argument.startswith("--output="):
            kept.append(argument)
    return kept


def _without_none(values: dict) -> dict:
    return {key: value for key, value in values.items() if value is not None}


if __name__ == "__main__":
    main()

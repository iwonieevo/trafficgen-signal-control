"""Tune fixed-time signal programs for a run of the traffic generator with Webster's method.

The programs keep the phases of the network and get new green times, one cycle length for
all junctions and, unless switched off, offsets from the SUMO tool tlsCoordinator.py. They
are written as an additional file that scripts/run_sumo.py loads with --controller.
The method and its limits are described in docs/sumo.md.
"""

import argparse
import math
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SATURATION_FLOW_VPH = 1580.0
LOST_TIME_S = 3.3
MIN_GREEN_S = 8
MAX_CYCLE_S = 120


@dataclass(frozen=True)
class Phase:
    """One phase of a signal program.

    Attributes:
        state: Signal of every connection of the junction.
        duration: Duration in seconds.
        approaches: Edges that have green in this phase, with their lanes. Empty for a
            phase without green, and for the yellow phase after a green one.
    """

    state: str
    duration: int
    approaches: dict[str, int]


@dataclass(frozen=True)
class Program:
    """The signal program of one junction, with the start time of its cycle."""

    junction: str
    phases: tuple[Phase, ...]
    offset: float = 0.0

    @property
    def cycle(self) -> int:
        """Length of the cycle in seconds."""
        return sum(phase.duration for phase in self.phases)


def read_programs(net_file: Path) -> list[Program]:
    """Read the signal program of every junction of a SUMO network.

    Args:
        net_file: SUMO network file.

    Returns:
        The programs, with the approaches that every green phase serves.
    """
    network = ET.parse(net_file).getroot()
    lanes = {
        edge.attrib["id"]: len(edge.findall("lane"))
        for edge in network.iter("edge")
        if edge.get("function") != "internal"
    }
    approach_of_link: dict[tuple[str, int], str] = {}
    for connection in network.iter("connection"):
        if "tl" in connection.attrib:
            link = (connection.attrib["tl"], int(connection.attrib["linkIndex"]))
            approach_of_link[link] = connection.attrib["from"]

    programs = []
    for logic in network.iter("tlLogic"):
        junction = logic.attrib["id"]
        phases = []
        for phase in logic.iter("phase"):
            state = phase.attrib["state"]
            green = (
                set() if "y" in state else {i for i, signal in enumerate(state) if signal in "Gg"}
            )
            approaches = sorted({approach_of_link[junction, link] for link in green})
            phases.append(
                Phase(
                    state=state,
                    duration=round(float(phase.attrib["duration"])),
                    approaches={approach: lanes[approach] for approach in approaches},
                )
            )
        programs.append(Program(junction, tuple(phases)))
    return programs


def design_flows(turn_flows_file: Path, hour: str | None = None) -> tuple[str, dict[str, float]]:
    """Read the flow of every approach in the design hour of a run.

    Args:
        turn_flows_file: ``flows/turn_flows.csv`` of a run.
        hour: Design hour, as written in the file. The hour with the most traffic if None.

    Returns:
        The design hour, and the vehicles per hour that leave each road into a junction.

    Raises:
        ValueError: If the file has no such hour.
    """
    table = pd.read_csv(turn_flows_file)
    if hour is None:
        hour = str(table.groupby("datetime")["vehicles_per_hour"].sum().idxmax())
    table = table[table["datetime"] == hour]
    if table.empty:
        raise ValueError(f"{turn_flows_file} has no hour {hour!r}")
    flows = table.groupby("from_road")["vehicles_per_hour"].sum()
    return hour, {str(road): float(flow) for road, flow in flows.items()}


def flow_ratios(
    program: Program, flows: dict[str, float], saturation_flow: float = SATURATION_FLOW_VPH
) -> list[float]:
    """Flow ratio of every green phase: the highest flow per lane over the saturation flow.

    Args:
        program: Program of a junction.
        flows: Vehicles per hour of each approach.
        saturation_flow: Vehicles per hour that one lane passes during green.

    Returns:
        One ratio per green phase, in the order of the phases.
    """
    return [
        max(flows.get(approach, 0.0) / lanes for approach, lanes in phase.approaches.items())
        / saturation_flow
        for phase in program.phases
        if phase.approaches
    ]


def webster_cycle(
    programs: list[Program],
    flows: dict[str, float],
    saturation_flow: float = SATURATION_FLOW_VPH,
    lost_time: float = LOST_TIME_S,
    min_green: int = MIN_GREEN_S,
    max_cycle: int = MAX_CYCLE_S,
) -> int:
    """Cycle length of Webster for the busiest junction, used by all junctions.

    The optimal cycle is ``(1.5 L + 5) / (1 - Y)``, with the lost time ``L`` of a cycle
    and the sum ``Y`` of the flow ratios of its green phases. It is kept between the
    shortest cycle that the minimum greens allow and ``max_cycle``. At ``Y`` of 1 or more
    the formula has no answer, and ``max_cycle`` is used.

    Args:
        programs: Programs of the network.
        flows: Vehicles per hour of each approach.
        saturation_flow: Vehicles per hour that one lane passes during green.
        lost_time: Seconds per green phase in which no vehicle passes.
        min_green: Shortest green of a phase in seconds.
        max_cycle: Longest cycle in seconds.

    Returns:
        The cycle length in whole seconds.
    """
    cycle = 0.0
    for program in programs:
        ratios = flow_ratios(program, flows, saturation_flow)
        shortest = _fixed_time(program) + min_green * len(ratios)
        total = sum(ratios)
        optimal = (1.5 * lost_time * len(ratios) + 5) / (1 - total) if total < 1 else math.inf
        cycle = max(cycle, shortest, min(optimal, max_cycle))
    # Whole seconds, rounded up. The margin keeps 70.00000000000001 at 70.
    return math.ceil(cycle - 1e-9)


def retime(
    program: Program,
    flows: dict[str, float],
    cycle: int,
    saturation_flow: float = SATURATION_FLOW_VPH,
    min_green: int = MIN_GREEN_S,
) -> Program:
    """Give the green phases of a program new durations for a cycle length.

    The green time of the cycle is split in proportion to the flow ratios of the phases,
    in whole seconds and with at least ``min_green`` for every phase. Without any flow it
    is split equally. Other phases keep their duration.

    Args:
        program: Program of a junction.
        flows: Vehicles per hour of each approach.
        cycle: Cycle length in seconds.
        saturation_flow: Vehicles per hour that one lane passes during green.
        min_green: Shortest green of a phase in seconds.

    Returns:
        The program with the new green times.

    Raises:
        ValueError: If the cycle is too short for the minimum greens.
    """
    ratios = flow_ratios(program, flows, saturation_flow)
    spare = cycle - _fixed_time(program) - min_green * len(ratios)
    if spare < 0:
        raise ValueError(f"a cycle of {cycle} s is too short for {program.junction}")

    # Every phase gets its minimum, and the phases that need more share the rest.
    targets = [ratio / sum(ratios) if sum(ratios) > 0 else 1 / len(ratios) for ratio in ratios]
    needs = [max(target * (cycle - _fixed_time(program)) - min_green, 0.0) for target in targets]
    shares = [need / sum(needs) * spare if sum(needs) > 0 else 0.0 for need in needs]
    extra = [math.floor(share) for share in shares]
    by_remainder = sorted(range(len(shares)), key=lambda i: shares[i] - extra[i], reverse=True)
    for i in by_remainder[: spare - sum(extra)]:
        extra[i] += 1

    greens = iter(min_green + seconds for seconds in extra)
    phases = tuple(
        Phase(phase.state, next(greens), phase.approaches) if phase.approaches else phase
        for phase in program.phases
    )
    return Program(program.junction, phases)


def _fixed_time(program: Program) -> int:
    """Seconds of a cycle that are not green: the yellow and all-red phases."""
    return sum(phase.duration for phase in program.phases if not phase.approaches)


def tune(
    programs: list[Program],
    flows: dict[str, float],
    saturation_flow: float = SATURATION_FLOW_VPH,
    lost_time: float = LOST_TIME_S,
    min_green: int = MIN_GREEN_S,
    max_cycle: int = MAX_CYCLE_S,
) -> list[Program]:
    """Tune the programs of a network for the flows of a design hour.

    Args:
        programs: Programs of the network.
        flows: Vehicles per hour of each approach.
        saturation_flow: Vehicles per hour that one lane passes during green.
        lost_time: Seconds per green phase in which no vehicle passes.
        min_green: Shortest green of a phase in seconds.
        max_cycle: Longest cycle in seconds.

    Returns:
        The programs with one cycle length and new green times, without offsets.
    """
    cycle = webster_cycle(programs, flows, saturation_flow, lost_time, min_green, max_cycle)
    return [retime(program, flows, cycle, saturation_flow, min_green) for program in programs]


def write_programs(path: Path, programs: list[Program], name: str, comment: str) -> None:
    """Write programs as a SUMO additional file.

    Args:
        path: File to write.
        programs: Programs of the junctions.
        name: Id of the programs. A program loaded with a new id replaces the one of the
            network.
        comment: Text for the comment at the top of the file.
    """
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "", f"<!-- {comment} -->", "<additional>"]
    for program in programs:
        lines.append(
            f'    <tlLogic id="{program.junction}" type="static" programID="{name}" '
            f'offset="{program.offset:g}">'
        )
        lines += [
            f'        <phase duration="{phase.duration}" state="{phase.state}"/>'
            for phase in program.phases
        ]
        lines.append("    </tlLogic>")
    path.write_text("\n".join([*lines, "</additional>", ""]), encoding="utf-8", newline="\n")


def coordinate(
    programs: list[Program], name: str, net_file: Path, route_file: Path
) -> list[Program]:
    """Add offsets that let vehicles of the given routes pass several junctions on green.

    The offsets come from tlsCoordinator.py of the SUMO tools.

    Args:
        programs: Programs with one cycle length.
        name: Id of the programs.
        net_file: SUMO network file.
        route_file: Routes of the run that the programs are tuned for.

    Returns:
        The programs with offsets between 0 and the cycle length.

    Raises:
        SystemExit: If SUMO is not installed or the tool fails.
    """
    try:
        import sumo  # pyright: ignore[reportMissingImports]
    except ImportError:
        sys.exit("SUMO is needed for the offsets. Install it with: uv sync")
    sumo_home = sumo.SUMO_HOME  # pyright: ignore[reportAttributeAccessIssue]

    with tempfile.TemporaryDirectory() as directory:
        plain, offsets = Path(directory) / "programs.add.xml", Path(directory) / "offsets.add.xml"
        write_programs(plain, programs, name, "input of tlsCoordinator.py")
        command = [
            sys.executable, str(Path(sumo_home) / "tools" / "tlsCoordinator.py"),
            "--net-file", str(net_file),
            "--route-file", str(route_file),
            "--additional-file", str(plain),
            "--output-file", str(offsets),
        ]  # fmt: skip
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "SUMO_HOME": sumo_home},
        )
        if result.returncode != 0:
            sys.exit(f"tlsCoordinator.py failed:\n{result.stderr}")
        offset_of = {
            logic.attrib["id"]: float(logic.attrib["offset"])
            for logic in ET.parse(offsets).getroot().iter("tlLogic")
        }

    return [
        Program(
            program.junction, program.phases, offset_of.get(program.junction, 0.0) % program.cycle
        )
        for program in programs
    ]


def main() -> None:
    """Tune the programs for a run and write them next to the network of its scenario."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="directory of a run of the traffic generator")
    parser.add_argument("--name", required=True, help="id of the programs, for example fixed-x12")
    parser.add_argument("--hour", help="design hour as in flows/turn_flows.csv (default: busiest)")
    parser.add_argument(
        "--output", type=Path, help="file to write (default: tls.<name>.add.xml of the scenario)"
    )
    parser.add_argument("--saturation-flow", type=float, default=SATURATION_FLOW_VPH)
    parser.add_argument("--lost-time", type=float, default=LOST_TIME_S)
    parser.add_argument("--min-green", type=int, default=MIN_GREEN_S)
    parser.add_argument("--max-cycle", type=int, default=MAX_CYCLE_S)
    parser.add_argument("--no-offsets", action="store_true", help="leave all offsets at 0")
    args = parser.parse_args()

    config_file = args.run / "sumo" / "run.sumocfg"
    turn_flows_file = args.run / "flows" / "turn_flows.csv"
    for path in (config_file, turn_flows_file):
        if not path.is_file():
            sys.exit(f"Not a run of the traffic generator, missing: {path}")
    inputs = ET.parse(config_file).getroot().find("input")
    assert inputs is not None
    net_file, route_file = (
        (config_file.parent / inputs.find(option).attrib["value"]).resolve()  # pyright: ignore[reportOptionalMemberAccess]
        for option in ("net-file", "route-files")
    )

    try:
        hour, flows = design_flows(turn_flows_file, args.hour)
    except ValueError as error:
        sys.exit(str(error))
    programs = tune(
        read_programs(net_file),
        flows,
        args.saturation_flow,
        args.lost_time,
        args.min_green,
        args.max_cycle,
    )
    if not args.no_offsets:
        programs = coordinate(programs, args.name, net_file, route_file)

    output = args.output or net_file.parent / f"tls.{args.name}.add.xml"
    comment = (
        f"Fixed-time programs from scripts/tune_fixed_time.py, design hour {hour}, "
        f"saturation flow {args.saturation_flow:g} veh/h, lost time {args.lost_time:g} s per "
        f"phase, minimum green {args.min_green} s, maximum cycle {args.max_cycle} s. "
        "See docs/sumo.md."
    )
    write_programs(output, programs, args.name, comment)

    print(f"design hour {hour}, cycle {programs[0].cycle} s")
    for program in programs:
        greens = ", ".join(f"{phase.duration} s" for phase in program.phases if phase.approaches)
        print(f"  {program.junction}: green {greens}, offset {program.offset:g} s")
    print(f"written to {output}")


if __name__ == "__main__":
    main()

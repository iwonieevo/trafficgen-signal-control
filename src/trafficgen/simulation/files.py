"""SUMO input files written from the network flows, without running SUMO.

Simulation second 0 is the start of the first hour, and every hour of the flows is one
interval of 3600 seconds.
"""

import os
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import numpy as np
import pandas as pd

from trafficgen.simulation.config import Departures
from trafficgen.timeutils import SECONDS_PER_HOUR

# Random departures need a positive rate: smaller flows are left out of their hour.
MIN_POISSON_VEHICLES_PER_HOUR = 0.01
VEHICLE_ATTRIBUTES = {"departLane": "best", "departSpeed": "max"}


def simulation_seconds(times: pd.Series, start: pd.Timestamp) -> pd.Series:
    """Convert times to whole seconds of the simulation.

    Args:
        times: Times of the flows.
        start: Time of simulation second 0.

    Returns:
        Seconds since ``start``.
    """
    return ((times - start) // pd.Timedelta(seconds=1)).astype(int)


def write_entry_flows(
    entry_flows: pd.DataFrame, start: pd.Timestamp, path: Path, departures: Departures
) -> None:
    """Write one SUMO ``<flow>`` per entry road and hour.

    Args:
        entry_flows: The ``entry_flows`` table of the network flows.
        start: Time of simulation second 0.
        path: Route file to write.
        departures: ``poisson`` for random departures with the rate of the flow, ``uniform``
            for evenly spaced departures. With ``uniform``, every hour gets a whole number of
            vehicles, and the fractions are carried over to the next hour of the same road.
    """
    table = entry_flows.sort_values("datetime", kind="stable")
    begins: list[int] = simulation_seconds(table["datetime"], start).tolist()
    if departures == "uniform":
        total = table.groupby("road")["vehicles_per_hour"].cumsum()
        previous_total = total.groupby(table["road"]).shift(fill_value=0.0)
        numbers = (_round_half_up(total) - _round_half_up(previous_total)).astype(int)
        amounts = [{"number": str(number)} if number > 0 else None for number in numbers]
    else:
        amounts = [
            {"period": f"exp({rate / SECONDS_PER_HOUR:.8g})"}
            if rate >= MIN_POISSON_VEHICLES_PER_HOUR
            else None
            for rate in table["vehicles_per_hour"].to_numpy(dtype=float)
        ]

    root = ElementTree.Element("routes")
    roads = table["road"].astype(str)
    for road, begin, amount in zip(roads, begins, amounts, strict=True):
        if amount is None:
            continue
        ElementTree.SubElement(
            root,
            "flow",
            {
                "id": f"{road}_{begin}",
                "from": road,
                "begin": str(begin),
                "end": str(begin + SECONDS_PER_HOUR),
                **amount,
                **VEHICLE_ATTRIBUTES,
            },
        )
    _write(root, path)


def write_turn_ratios(turn_flows: pd.DataFrame, start: pd.Timestamp, path: Path) -> None:
    """Write the used turn shares of every hour as a ``jtrrouter`` turn file.

    Args:
        turn_flows: The ``turn_flows`` table of the network flows.
        start: Time of simulation second 0.
        path: Turn file to write.
    """
    begins: list[int] = simulation_seconds(turn_flows["datetime"], start).tolist()
    root = ElementTree.Element("turns")
    intervals = {
        begin: ElementTree.SubElement(
            root, "interval", begin=str(begin), end=str(begin + SECONDS_PER_HOUR)
        )
        for begin in sorted(set(begins))
    }
    for begin, from_road, to_road, share in zip(
        begins,
        turn_flows["from_road"].astype(str),
        turn_flows["to_road"].astype(str),
        turn_flows["share"].to_numpy(dtype=float),
        strict=True,
    ):
        ElementTree.SubElement(
            intervals[begin],
            "edgeRelation",
            {"from": from_road, "to": to_road},
            probability=f"{share:.8g}",
        )
    _write(root, path)


def write_sumo_config(path: Path, net_file: Path, route_file: Path) -> None:
    """Write a SUMO config that loads a network with a route file.

    Paths are written relative to the config, so a run directory can be moved together
    with its scenario. The simulation starts at second 0 and ends when every vehicle has
    left the network.

    Args:
        path: SUMO config file to write.
        net_file: SUMO network file.
        route_file: Route file.
    """
    root = ElementTree.Element("configuration")
    files = ElementTree.SubElement(root, "input")
    ElementTree.SubElement(files, "net-file", value=_relative_path(net_file, path.parent))
    ElementTree.SubElement(files, "route-files", value=_relative_path(route_file, path.parent))
    _write(root, path)


def _round_half_up(values: pd.Series) -> pd.Series:
    """Round to whole numbers, with halves rounded up."""
    return np.floor(values + 0.5)


def _relative_path(target: Path, directory: Path) -> str:
    """Return the path of a file relative to a directory, or the absolute path if there is none.

    On Windows, a file on another drive has no relative path.
    """
    try:
        return Path(os.path.relpath(target.resolve(), directory.resolve())).as_posix()
    except ValueError:
        return target.resolve().as_posix()


def _write(root: ElementTree.Element, path: Path) -> None:
    """Write an XML file with indentation."""
    ElementTree.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

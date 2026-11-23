"""Tests of the network flows: spreading junction counts over roads and turns."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trafficgen import (
    FlowSettings,
    FlowSolver,
    FlowWarning,
    NetworkConfig,
    NetworkFlows,
    RoadConfig,
    TurnConfig,
    load_network_config,
)

CONFIGS_DIR = Path(__file__).parents[2] / "configs"


def hours(count: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=count, freq="h", name="datetime")


def line_network(
    through_share: float = 0.9, entry_at_b: bool = True, **settings: float
) -> NetworkConfig:
    """Two junctions in a line. With the preferred shares: T_A = E_A, T_B = E_B + 0.36 E_A."""
    entry_b = (RoadConfig("in_B", to_junction="B", preference=1.0),) if entry_at_b else ()
    turn_b = (TurnConfig("in_B", "B_out", 1.0),) if entry_at_b else ()
    return NetworkConfig(
        junction_ids=("A", "B"),
        roads=(
            RoadConfig("in_A", to_junction="A", preference=1.0),
            RoadConfig(
                "A_B",
                "A",
                "B",
                length_m=300,
                lanes=1,
                speed_limit_kmh=50,
                through_share=through_share,
            ),
            RoadConfig("A_out", from_junction="A"),
            *entry_b,
            RoadConfig("B_out", from_junction="B"),
        ),
        turns=(
            TurnConfig("in_A", "A_B", 0.4),
            TurnConfig("in_A", "A_out", 0.6),
            TurnConfig("A_B", "B_out", 1.0),
            *turn_b,
        ),
        settings=FlowSettings(**settings),
    )


def counts_table(**columns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(columns, index=hours(len(next(iter(columns.values())))))


def flow(table: pd.DataFrame, column: str = "vehicles_per_hour", **keys: str) -> np.ndarray:
    mask = np.logical_and.reduce([table[key] == value for key, value in keys.items()])
    return table.loc[mask, column].to_numpy()


def wide(table: pd.DataFrame, column: str, values: str = "vehicles_per_hour") -> pd.DataFrame:
    return table.pivot_table(index="datetime", columns=column, values=values, aggfunc="sum")


def assert_consistent(config: NetworkConfig, flows: NetworkFlows) -> None:
    """Check that the tables describe one valid set of flows."""
    for table in (flows.road_flows, flows.turn_flows, flows.entry_flows):
        assert (table["vehicles_per_hour"].to_numpy() >= -1e-9).all()

    roads = wide(flows.road_flows, "road")
    achieved = wide(flows.junction_balance, "junction", "achieved")
    for junction in config.junction_ids:
        incoming = [road.id for road in config.roads if road.to_junction == junction]
        np.testing.assert_allclose(
            roads[incoming].to_numpy().sum(axis=1), achieved[junction].to_numpy(), atol=1e-6
        )

    turned_from = wide(flows.turn_flows, "from_road")
    for road in turned_from.columns:
        np.testing.assert_allclose(turned_from[road].to_numpy(), roads[road].to_numpy(), atol=1e-6)
    turned_to = wide(flows.turn_flows, "to_road")
    for road in turned_to.columns:
        share = config.roads_by_id[str(road)].through_share
        np.testing.assert_allclose(
            share * turned_to[road].to_numpy(), roads[road].to_numpy(), atol=1e-6
        )

    np.testing.assert_allclose(wide(flows.turn_flows, "from_road", "share").to_numpy(), 1)
    np.testing.assert_allclose(wide(flows.entry_flows, "junction", "share").to_numpy(), 1)


def test_single_junction_reproduces_its_count_with_the_preferred_shares():
    config = load_network_config(CONFIGS_DIR / "single_intersection.toml")
    counts = counts_table(J1=[0, 37, 120, 5])
    flows = FlowSolver(config).solve(counts)

    np.testing.assert_allclose(flows.junction_balance["achieved"], counts["J1"])
    np.testing.assert_allclose(flow(flows.entry_flows, road="-E0"), counts["J1"] * 0.25)
    np.testing.assert_allclose(
        flow(flows.turn_flows, from_road="-E0", to_road="E3"), counts["J1"] * 0.25 * 0.7
    )
    assert flows.adjusted_hours.empty
    assert flows.warnings == ()
    assert_consistent(config, flows)


def test_known_line_network_gives_known_flows():
    config = line_network()
    flows = FlowSolver(config).solve(counts_table(A=[100.0], B=[50.0]))

    # E_A = 100, E_B = 50 - 0.36 * 100 = 14.
    expected = {"in_A": 100, "A_B": 36, "A_out": 60, "in_B": 14, "B_out": 50}
    for road, value in expected.items():
        assert flow(flows.road_flows, road=road) == pytest.approx([value])
    np.testing.assert_allclose(
        flows.turn_flows["share"], flows.turn_flows["preferred_share"], atol=1e-9
    )
    assert flows.adjusted_hours.empty
    assert_consistent(config, flows)


def test_shares_are_adjusted_when_the_preferred_ones_miss_a_total():
    config = line_network()
    # With the preferred 0.4, A alone sends 36 vehicles to B, more than its count of 20.
    counts = counts_table(A=[100.0, 100.0], B=[50.0, 20.0])
    flows = FlowSolver(config).solve(counts)

    np.testing.assert_allclose(
        flows.junction_balance["achieved"], flows.junction_balance["requested"], atol=1e-6
    )
    assert list(flows.adjusted_hours) == [hours(2)[1]]
    assert flows.unbalanced_hours.empty
    assert flows.warnings == ()
    late_share = flow(flows.turn_flows, "share", from_road="in_A", to_road="A_B")[1]
    assert late_share < 0.4
    assert_consistent(config, flows)


def test_impossible_totals_are_reported_without_negative_flows():
    # B can only be reached from A, and even all of A cannot give B 50 vehicles.
    config = line_network(entry_at_b=False)
    with pytest.warns(FlowWarning, match="1 of 1 hours could not be balanced"):
        flows = FlowSolver(config).solve(counts_table(A=[10.0], B=[50.0]))

    assert len(flows.unbalanced_hours) == 1
    assert flows.adjusted_hours.empty
    assert_consistent(config, flows)


def test_lower_through_share_needs_no_adjustment():
    flows = FlowSolver(line_network(through_share=0.5)).solve(counts_table(A=[100.0], B=[20.0]))
    assert flows.adjusted_hours.empty
    assert flow(flows.road_flows, road="A_B") == pytest.approx([20])


def test_grid_with_equal_counts_uses_the_preferred_shares():
    config = load_network_config(CONFIGS_DIR / "grid_2x2.toml")
    counts = pd.DataFrame(
        {junction: [50.0, 80.0] for junction in config.junction_ids}, index=hours(2)
    )
    flows = FlowSolver(config).solve(counts)

    assert flows.adjusted_hours.empty
    np.testing.assert_allclose(
        flows.turn_flows["share"], flows.turn_flows["preferred_share"], atol=1e-9
    )
    # Every vehicle passes two junctions on average, so half of the traffic enters.
    entering = wide(flows.entry_flows, "junction").sum(axis=1).to_numpy()
    np.testing.assert_allclose(entering, counts.sum(axis=1).to_numpy() / 2, rtol=0.01)
    assert_consistent(config, flows)


def test_grid_with_random_counts_meets_every_total():
    config = load_network_config(CONFIGS_DIR / "grid_2x2.toml")
    rng = np.random.default_rng(0)
    counts = pd.DataFrame(
        rng.integers(0, 150, size=(24, 4)), index=hours(24), columns=list(config.junction_ids)
    )
    flows = FlowSolver(config).solve(counts)

    assert flows.unbalanced_hours.empty
    assert len(flows.adjusted_hours) > 0
    assert_consistent(config, flows)


def test_solve_is_deterministic():
    config = load_network_config(CONFIGS_DIR / "grid_2x2.toml")
    counts = counts_table(J1=[90.0], J2=[30.0], J3=[20.0], J4=[10.0])
    first, second = FlowSolver(config).solve(counts), FlowSolver(config).solve(counts)
    pd.testing.assert_frame_equal(first.turn_flows, second.turn_flows)


def test_output_tables_have_the_documented_columns():
    flows = FlowSolver(line_network()).solve(counts_table(A=[100.0], B=[50.0]))
    assert list(flows.output_tables) == [
        "entry_flows",
        "road_flows",
        "turn_flows",
        "junction_balance",
        "roads",
    ]
    assert list(flows.entry_flows) == [
        "datetime",
        "road",
        "junction",
        "preferred_share",
        "share",
        "vehicles_per_hour",
    ]
    assert list(flows.road_flows) == [
        "datetime",
        "road",
        "from_junction",
        "to_junction",
        "kind",
        "vehicles_per_hour",
    ]
    assert list(flows.turn_flows) == [
        "datetime",
        "junction",
        "from_road",
        "to_road",
        "preferred_share",
        "share",
        "vehicles_per_hour",
    ]
    assert list(flows.junction_balance) == [
        "datetime",
        "junction",
        "requested",
        "achieved",
        "difference",
    ]
    assert {"road", "length_m", "lanes", "speed_limit_kmh", "free_flow_time_s"} <= set(flows.roads)
    assert flows.roads.set_index("road").loc["A_B", "free_flow_time_s"] == pytest.approx(21.6)


def test_capacity_warning_reports_hours_over_capacity():
    config = line_network(lane_capacity_vph=30)
    with pytest.warns(FlowWarning) as record:
        flows = FlowSolver(config).solve(counts_table(A=[100.0, 10.0], B=[50.0, 5.0]))
    messages = " ".join(str(item.message) for item in record)
    assert "'A_B' has more than 30 vehicles per hour per lane in 1 of 2 hours" in messages
    assert flows.warnings == (messages,)
    roads = flows.roads.set_index("road")
    assert roads.loc["A_B", "max_flow_per_lane"] == pytest.approx(36)
    assert roads.loc["A_B", "hours_over_capacity"] == 1


def test_travel_time_warning_comes_with_the_result_not_the_config():
    config = line_network(max_travel_time_fraction=0.005)
    with pytest.warns(FlowWarning, match="'A_B' takes 22 s"):
        flows = FlowSolver(config).solve(counts_table(A=[100.0], B=[50.0]))
    assert len(flows.warnings) == 1


def test_counts_must_cover_every_junction():
    with pytest.raises(ValueError, match=r"no column for junctions \['B'\]"):
        FlowSolver(line_network()).solve(counts_table(A=[1.0]))


def test_other_count_columns_are_ignored():
    flows = FlowSolver(line_network()).solve(counts_table(C=[5.0], A=[100.0], B=[50.0]))
    assert set(flows.junction_balance["junction"]) == {"A", "B"}

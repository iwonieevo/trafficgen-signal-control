"""Tests of layer 2: balancing junction counts over the roads and turns of a network."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trafficgen import (
    BalanceSettings,
    JunctionConfig,
    NetworkBalancer,
    NetworkConfig,
    RoadConfig,
    RoadDemand,
    RoadDemandModel,
    RoadDemandWarning,
    TurnConfig,
    build_road_demand_generator,
    load_network_config,
)

CONFIGS_DIR = Path(__file__).parents[2] / "configs"
DATA = Path("data.csv")


def hours(count: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=count, freq="h", name="datetime")


def line_network(through_share: float = 0.9, **balance) -> NetworkConfig:
    """Junction totals: T_A = E_A and T_B = E_B + 0.36 E_A."""
    return NetworkConfig(
        junctions=(JunctionConfig("A", DATA), JunctionConfig("B", DATA)),
        roads=(
            RoadConfig("in_A", to_junction="A", weight=1.0),
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
            RoadConfig("in_B", to_junction="B", weight=1.0),
            RoadConfig("B_out", from_junction="B"),
        ),
        turns=(
            TurnConfig("in_A", "A_B", 0.4),
            TurnConfig("in_A", "A_out", 0.6),
            TurnConfig("A_B", "B_out", 1.0),
            TurnConfig("in_B", "B_out", 1.0),
        ),
        balance=BalanceSettings(**balance),
    )


def flow(table: pd.DataFrame, **keys) -> np.ndarray:
    mask = np.logical_and.reduce([table[key] == value for key, value in keys.items()])
    return table.loc[mask, "vehicles_per_hour"].to_numpy()


def mean_junctions_passed_per_vehicle(balancer: NetworkBalancer) -> np.ndarray:
    return balancer.junction_traffic_per_entering_vehicle.sum(axis=0)


def junction_totals_without_balancing(
    balancer: NetworkBalancer, counts: pd.DataFrame
) -> np.ndarray:
    counts_as_entry_flows = counts[balancer.entry_junction_ids].to_numpy(dtype=float)
    return counts_as_entry_flows @ balancer.junction_traffic_per_entering_vehicle.T


def wide(table: pd.DataFrame, column: str, values: str = "vehicles_per_hour") -> pd.DataFrame:
    return table.pivot_table(index="datetime", columns=column, values=values, aggfunc="sum")


def assert_consistent(config: NetworkConfig, demand: RoadDemand) -> None:
    assert (demand.road_flows["vehicles_per_hour"].to_numpy() >= 0).all()
    assert (demand.turn_flows["vehicles_per_hour"].to_numpy() >= 0).all()

    roads = wide(demand.road_flows, "road")
    achieved = wide(demand.junction_balance, "junction", "achieved")
    for junction in config.junction_ids:
        incoming = [road.id for road in config.roads if road.to_junction == junction]
        np.testing.assert_allclose(
            roads[incoming].to_numpy().sum(axis=1), achieved[junction].to_numpy(), rtol=1e-9
        )

    turned_from = wide(demand.turn_flows, "from_road")
    for road in turned_from.columns:
        np.testing.assert_allclose(turned_from[road].to_numpy(), roads[road].to_numpy())

    turned_to = wide(demand.turn_flows, "to_road")
    for road in turned_to.columns:
        share = config.roads_by_id[str(road)].through_share
        np.testing.assert_allclose(share * turned_to[road].to_numpy(), roads[road].to_numpy())


def test_single_junction_reproduces_its_count_exactly():
    config = load_network_config(CONFIGS_DIR / "network_single.toml")
    counts = pd.DataFrame({"J1": [0, 37, 120, 5]}, index=hours(4))
    demand = NetworkBalancer(config).balance(counts)

    np.testing.assert_allclose(demand.junction_balance["achieved"], counts["J1"])
    assert (np.abs(demand.junction_balance["difference"].to_numpy()) < 1e-9).all()
    np.testing.assert_allclose(flow(demand.entry_flows, road="-E0"), counts["J1"] * 0.25)
    np.testing.assert_allclose(
        flow(demand.turn_flows, from_road="-E0", to_road="E3"), counts["J1"] * 0.25 * 0.7
    )
    assert demand.warnings == ()
    assert_consistent(config, demand)


def test_known_line_network_gives_known_flows():
    config = line_network()
    demand = NetworkBalancer(config).balance(
        pd.DataFrame({"A": [100.0], "B": [50.0]}, index=hours(1))
    )

    # E_A = 100, E_B = 50 - 0.36 * 100 = 14.
    expected = {"in_A": 100, "A_B": 36, "A_out": 60, "in_B": 14, "B_out": 50}
    for road, value in expected.items():
        assert flow(demand.road_flows, road=road) == pytest.approx([value])
    assert flow(demand.turn_flows, from_road="A_B", to_road="B_out") == pytest.approx([36])
    assert demand.unbalanced_hours.empty
    assert_consistent(config, demand)


def test_infeasible_network_is_reported_without_negative_flows():
    config = line_network()
    counts = pd.DataFrame({"A": [100.0, 100.0], "B": [50.0, 20.0]}, index=hours(2))
    with pytest.warns(RoadDemandWarning, match="1 of 2 hours could not be balanced"):
        demand = NetworkBalancer(config).balance(counts)

    assert list(demand.unbalanced_hours) == [hours(2)[1]]
    assert flow(demand.entry_flows, road="in_B")[1] == 0
    # E_B = 0 and x = E_A minimises (x - 100)^2 + (0.36 x - 20)^2.
    x = 107.2 / 1.1296
    late = demand.junction_balance.iloc[2:]
    np.testing.assert_allclose(late["achieved"], [x, 0.36 * x])
    np.testing.assert_allclose(late["difference"], [x - 100, 0.36 * x - 20])
    assert len(demand.warnings) == 1
    assert_consistent(config, demand)


def test_relative_weighting_shifts_the_error_to_the_large_junction():
    counts = pd.DataFrame({"A": [100.0], "B": [20.0]}, index=hours(1))
    with pytest.warns(RoadDemandWarning):
        absolute = NetworkBalancer(line_network()).balance(counts).junction_balance
    with pytest.warns(RoadDemandWarning):
        relative = (
            NetworkBalancer(line_network(weighting="relative")).balance(counts).junction_balance
        )

    assert abs(relative["difference"].iloc[1]) < abs(absolute["difference"].iloc[1])
    assert abs(relative["difference"].iloc[0]) > abs(absolute["difference"].iloc[0])


def test_lower_through_share_makes_the_network_feasible():
    counts = pd.DataFrame({"A": [100.0], "B": [20.0]}, index=hours(1))
    demand = NetworkBalancer(line_network(through_share=0.5)).balance(counts)
    assert demand.unbalanced_hours.empty
    assert flow(demand.road_flows, road="A_B") == pytest.approx([20])


def test_grid_with_equal_counts_is_balanced_and_halves_the_totals_without_balancing():
    config = load_network_config(CONFIGS_DIR / "network_grid_2x2.toml")
    model = NetworkBalancer(config)
    counts = pd.DataFrame(
        {junction: [50.0, 80.0] for junction in config.junction_ids}, index=hours(2)
    )
    demand = model.balance(counts)

    np.testing.assert_allclose(mean_junctions_passed_per_vehicle(model), 2.0)
    np.testing.assert_allclose(junction_totals_without_balancing(model, counts), 2 * counts)
    assert demand.unbalanced_hours.empty
    assert_consistent(config, demand)


def test_grid_with_random_counts_never_has_negative_flows():
    config = load_network_config(CONFIGS_DIR / "network_grid_2x2.toml")
    rng = np.random.default_rng(0)
    counts = pd.DataFrame(
        rng.integers(0, 150, size=(48, 4)), index=hours(48), columns=config.junction_ids
    )
    with pytest.warns(RoadDemandWarning):
        demand = NetworkBalancer(config).balance(counts)
    assert len(demand.unbalanced_hours) > 0
    assert_consistent(config, demand)


def test_balance_is_deterministic():
    config = load_network_config(CONFIGS_DIR / "network_grid_2x2.toml")
    counts = pd.DataFrame({"J1": [90], "J2": [30], "J3": [20], "J4": [10]}, index=hours(1))
    with pytest.warns(RoadDemandWarning):
        first = NetworkBalancer(config).balance(counts)
    with pytest.warns(RoadDemandWarning):
        second = NetworkBalancer(config).balance(counts)
    pd.testing.assert_frame_equal(first.road_flows, second.road_flows)


def test_output_tables_have_the_documented_columns():
    demand = NetworkBalancer(line_network()).balance(
        pd.DataFrame({"A": [100.0], "B": [50.0]}, index=hours(1))
    )
    assert list(demand.entry_flows) == ["datetime", "road", "junction", "vehicles_per_hour"]
    assert list(demand.road_flows) == [
        "datetime",
        "road",
        "from_junction",
        "to_junction",
        "kind",
        "vehicles_per_hour",
    ]
    assert list(demand.turn_flows) == [
        "datetime",
        "junction",
        "from_road",
        "to_road",
        "ratio",
        "vehicles_per_hour",
    ]
    assert list(demand.junction_balance) == [
        "datetime",
        "junction",
        "requested",
        "achieved",
        "difference",
    ]
    assert {"road", "length_m", "lanes", "speed_limit_kmh", "free_flow_time_s"} <= set(demand.roads)
    assert demand.roads.set_index("road").loc["A_B", "free_flow_time_s"] == pytest.approx(21.6)


def test_capacity_warning_reports_hours_over_capacity():
    config = line_network(lane_capacity_vph=30)
    with pytest.warns(RoadDemandWarning) as record:
        demand = NetworkBalancer(config).balance(
            pd.DataFrame({"A": [100.0, 10.0], "B": [50.0, 5.0]}, index=hours(2))
        )
    messages = " ".join(str(item.message) for item in record)
    assert "'A_B' has more than 30 vehicles per hour per lane in 1 of 2 hours" in messages
    assert demand.warnings == (messages,)
    roads = demand.roads.set_index("road")
    assert roads.loc["A_B", "max_flow_per_lane"] == pytest.approx(36)
    assert roads.loc["A_B", "hours_over_capacity"] == 1


def test_travel_time_warning_is_raised_once_when_the_config_is_created():
    with pytest.warns(RoadDemandWarning, match="'A_B' takes 22 s"):
        config = line_network(max_travel_time_fraction=0.005)
    demand = NetworkBalancer(config).balance(
        pd.DataFrame({"A": [100.0], "B": [50.0]}, index=hours(1))
    )
    assert demand.warnings == ()


def test_counts_must_cover_every_junction():
    with pytest.raises(ValueError, match=r"no column for junctions \['B'\]"):
        NetworkBalancer(line_network()).balance(pd.DataFrame({"A": [1.0]}, index=hours(1)))


@pytest.fixture
def grid_config_with_synthetic_data(tmp_path, hourly_counts) -> NetworkConfig:
    hourly_counts.to_csv(tmp_path / "data.csv")
    grid = load_network_config(CONFIGS_DIR / "network_grid_2x2.toml")
    return NetworkConfig(
        junctions=tuple(JunctionConfig(j.id, tmp_path / "data.csv") for j in grid.junctions),
        roads=grid.roads,
        turns=grid.turns,
    )


@pytest.mark.filterwarnings("ignore::trafficgen.RoadDemandWarning")
def test_road_demand_generator_is_reproducible(grid_config_with_synthetic_data):
    generator = build_road_demand_generator(grid_config_with_synthetic_data)

    def sample(seed: int) -> RoadDemand:
        return generator.sample("2024-03-04", "2024-03-05", seed=seed)

    first, second, other = sample(1), sample(1), sample(2)
    pd.testing.assert_frame_equal(first.road_flows, second.road_flows)
    assert not first.road_flows.equals(other.road_flows)


def test_road_demand_generator_gives_each_junction_its_own_seed(grid_config_with_synthetic_data):
    generator = build_road_demand_generator(grid_config_with_synthetic_data)
    counts = generator.sample_junction_counts("2024-03-04", "2024-03-05", seed=1)

    assert len(counts) == 24
    assert not np.array_equal(counts["J1"].to_numpy(), counts["J2"].to_numpy())


def test_road_demand_model_must_be_fitted_before_sampling():
    with pytest.raises(RuntimeError, match="fit the model before sampling"):
        RoadDemandModel(line_network()).sample("2024-03-04", "2024-03-05")


def test_road_demand_model_needs_counts_for_every_junction(hourly_counts):
    with pytest.raises(ValueError, match=r"no historical counts for junctions \['B'\]"):
        RoadDemandModel(line_network()).fit({"A": hourly_counts})

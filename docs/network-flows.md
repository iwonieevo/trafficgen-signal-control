# Network flows

The network flows turn hourly counts per junction into hourly flows on every road and turn of a network, so that the traffic through every junction matches its count. The counts can come from the [junction counts](junction-counts.md) or from anywhere else. How the two parts fit together is described in [traffic-generation.md](traffic-generation.md).

The network flows do not need SUMO, but they can read the network from a SUMO network file, so that road ids are SUMO edge ids, and the output is meant to be turned into SUMO input: entry flows into `<flow>` definitions and turn shares into turn definitions for `jtrrouter`.

## The problem

A count is the number of vehicles that pass a junction in an hour. In a network, a vehicle passes several junctions and is counted at each of them, so the traffic that leaves one junction towards a neighbour is already part of the neighbour's count. The counts therefore cannot simply be inserted on the outer roads: in the 2x2 grid, a vehicle passes two junctions on average, and that would double the traffic.

The data has no roads, lanes, directions or turns, so the network and the preferred way vehicles move through it are modelling assumptions in the config.

## Model

The flow `f_r` of a road is the number of vehicles per hour that reach its end. Every turn `q` from road `a` onto road `b` carries `t_q` vehicles per hour, and its share is `t_q / f_a`. For every hour:

```
entry road r:              f_r = vehicles entering the network on r
internal or exit road r:   f_r = through_share_r * sum of t_q over the turns onto r
every road r into a junction:  f_r = sum of t_q over the turns from r
junction j:                T_j = sum of f_r over the roads that end at j  =  count of j
```

The config gives preferences for the turns from each road and for the entry roads of each junction. They are divided by their sum per road or junction, which gives the preferred shares. The flows of an hour are found in two steps:

1. **Preferred flows.** Vehicles enter at the boundary and follow the preferred shares. In matrix form `f = A f + B E`, so `f = (I - A)^-1 B E`, and the junction totals are `T = C f = M E`. `M[i, j]` is how often a vehicle entering at junction `j` passes junction `i`. The entry flows `E >= 0` are fitted with non-negative least squares, `min ||M E - counts||` (`scipy.optimize.nnls`).
2. **Exact totals.** If a junction total is missed by more than `tolerance_vph`, the flows closest to those of step 1, in the sum of squared differences, that meet every total exactly and are not negative are used instead (`scipy.optimize.minimize` with SLSQP). Only the shares change, never the totals.

Step 2 is needed whenever neighbouring counts differ a lot. With the preferred 70% straight, a busy junction next to a quiet one would send the quiet one more vehicles than its own count. Step 2 then lowers the shares towards the quiet junction, so that vehicles leave the network sooner. The output reports, for every turn and entry road and every hour, both the preferred and the used share.

The totals cannot be met at all only when a junction cannot receive enough traffic: for example a junction without entry roads whose count is above what its neighbours can send it. Then the flows of step 1 are kept, no flow is negative, and the difference is reported in `junction_balance`, in `NetworkFlows.unbalanced_hours` and as a warning.

Flows are rates and need not be integers. Given the counts, the result is deterministic. Travel times between junctions are ignored, since they are far below an hour; they are reported, with a warning when a road takes more than `max_travel_time_fraction` of an hour. Flows per lane are reported with a warning above `lane_capacity_vph`, but are not limited: queues are measured by the simulation.

`notebooks/network_flows.ipynb` shows the result for a week of counts on both scenarios, how far the used shares are from the preferred ones, and how the result reacts to the config.

## Config

The network flows read `id` and `node` of `[[junctions]]`, and `[network]`, `[flows]`, `[[roads]]` and `[[turns]]` of the [shared config](traffic-generation.md#config). The `data` of the junctions is not used.

The network comes from one of two places.

### From a SUMO network file

This is how the scenarios are set up:

```toml
[[junctions]]
id = "J1"
node = "A0"            # the SUMO node of this junction

[network]
file = "grid.net.xml"  # relative to the config file
turn_preferences = { right = 0.15, straight = 0.7, left = 0.15 }

[flows]
tolerance_vph = 0.5

[[turns]]              # optional: change the preference of one turn
from_road = "left0A0"
to_road = "A0B0"
preference = 0.5

[[roads]]              # optional: change values of one road
id = "left0A0"
preference = 2.0
```

Every edge that is not internal becomes a road with the edge id, the length, lanes and speed limit of its lanes, and the junctions of its end nodes. Dead-end nodes are the boundary of the network, so an edge from a dead end is an entry road and an edge to one is an exit road. Every other node needs a junction with its `node`, otherwise the config is rejected. Every connection between two roads becomes a turn, with the preference of its SUMO direction (`dir`); U-turns are left out, and several turns of one direction from one road share its preference. Entry roads get preference 1, so the entry roads of a junction share its entry traffic equally.

`[[roads]]` and `[[turns]]` then only change single roads and turns, which must exist in the network. A road can change `preference`, `through_share`, `length_m`, `lanes` and `speed_limit_kmh`, and a turn only its `preference`. SUMO itself is not needed: the file is only read.

### Written by hand

Without `[network]`, `[[roads]]` and `[[turns]]` describe the whole network, and junctions need no `node`. This is useful for small examples and tests, or for a network that is not in SUMO:

```toml
[[junctions]]
id = "J1"

[[roads]]
id = "in_1"           # no 'from': the road enters the network
to = "J1"
preference = 1.0

[[roads]]
id = "J1_J2"          # a road between two junctions
from = "J1"
to = "J2"
length_m = 285.6
lanes = 1
speed_limit_kmh = 50.0

[[turns]]
from_road = "in_1"
to_road = "J1_J2"
preference = 0.7
```

### Keys

| Key | Where | Default | Meaning |
|---|---|---|---|
| `id` | `[[junctions]]` | required | Unique name of the junction |
| `node` | `[[junctions]]` | required with `[network]` | The node of the network file that is this junction |
| `file` | `[network]` | required | SUMO network file, relative to the config file |
| `turn_preferences` | `[network]` | 0.15, 0.7, 0.15 | Preferences of the `right`, `straight` and `left` turns. Directions that are left out keep their default |
| `tolerance_vph` | `[flows]` | 0.5 | Largest difference between requested and achieved totals that counts as met |
| `max_travel_time_fraction` | `[flows]` | 0.1 | Warn when the travel time at the speed limit is above this share of an hour |
| `lane_capacity_vph` | `[flows]` | 1800 | Warn when the flow per lane is above this |
| `id` | `[[roads]]` | required | Unique name of the road, the SUMO edge id |
| `from`, `to` | `[[roads]]`, by hand only | none | Junctions where the road starts and ends. Without `from` the road enters the network, without `to` it leaves it |
| `preference` | entry roads | required by hand, 1 from a file | Relative weight of the road among the entry roads of its junction |
| `through_share` | roads between junctions | 1 | Share of the vehicles that reach the end of the road, the rest leave on the way, for example to park |
| `length_m`, `lanes`, `speed_limit_kmh` | `[[roads]]` | none by hand, from a file | Only used for travel times and the capacity warnings |
| `from_road`, `to_road` | `[[turns]]` | required | A road that ends at a junction and a road that starts at the same junction |
| `preference` | `[[turns]]` | required by hand | Relative weight of the turn among the turns from `from_road` |

Preferences are relative: 0.15/0.7/0.15 and 3/14/3 give the same shares. Invalid configs fail with a message naming the file and the problem, for example an unknown road or node, a turn between roads that do not meet, a junction with no way in or out, preferences that are all 0, or roads that only lead back to each other.

## Running

```bash
uv run python scripts/generate_flows.py --config scenarios/grid-2x2/scenario.toml --counts scenarios/grid-2x2/runs/week-14/counts.csv --output-dir scenarios/grid-2x2/runs/week-14/flows
```

| Option | Meaning |
|---|---|
| `--config` | Config file, required |
| `--counts` | CSV file with a `datetime` column and one column per junction id, as written by `scripts/generate_counts.py`. Other columns are ignored |
| `--output-dir` | Directory for the five CSV files |

The script prints how many hours use shares other than the preferred ones, and writes warnings to stderr.

From Python:

```python
from trafficgen import FlowSolver, load_junction_counts, load_network_config

flows = FlowSolver(load_network_config("scenarios/grid-2x2/scenario.toml")).solve(
    load_junction_counts("scenarios/grid-2x2/runs/week-14/counts.csv")
)
flows.turn_flows, flows.junction_balance, flows.adjusted_hours, flows.unbalanced_hours
```

## Output

Every table except `roads` has one row per hour and item.

| Table | Columns |
|---|---|
| `entry_flows` | `datetime, road, junction, preferred_share, share, vehicles_per_hour`: vehicles entering the network on each entry road |
| `road_flows` | `datetime, road, from_junction, to_junction, kind, vehicles_per_hour`: vehicles reaching the end of each road. `kind` is `entry`, `internal` or `exit` |
| `turn_flows` | `datetime, junction, from_road, to_road, preferred_share, share, vehicles_per_hour`: vehicles of each turn |
| `junction_balance` | `datetime, junction, requested, achieved, difference`: how well the counts were met, `difference = achieved - requested` |
| `roads` | `road, kind, from_junction, to_junction, preference, length_m, lanes, speed_limit_kmh, through_share, free_flow_time_s, max_flow_per_lane, hours_over_capacity` |

`share` is the share actually used. When no vehicles reach a road or junction in an hour, it is the preferred share.

## Code

| Module | Contents |
|---|---|
| `trafficgen.flows.network` | `RoadConfig`, `TurnConfig`, `FlowSettings`, `NetworkConfig` |
| `trafficgen.flows.sumo_network` | Reading roads and turns from a SUMO network file |
| `trafficgen.flows.config` | `load_network_config`: the config sections above |
| `trafficgen.flows.validation` | Checks of the network config |
| `trafficgen.flows.solver` | `FlowSolver`: the two steps above |
| `trafficgen.flows.result` | `NetworkFlows`: the output tables and warnings, `FlowWarning` |

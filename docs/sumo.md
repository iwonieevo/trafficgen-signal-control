# SUMO scenarios

The simulations run in [Eclipse SUMO](https://eclipse.dev/sumo/), installed into `.venv` by `uv sync` (see the README). Each scenario is a directory in `scenarios/`.

## Running a scenario

From the repository root, on any platform:

```bash
uv run python scripts/run_sumo.py <scenario> [--gui] [--controller <name>]
```

- `<scenario>`: name of a directory in `scenarios/`, or the path of a `.sumocfg` file, for example `scenarios/grid-2x2/runs/<run>/sumo/run.sumocfg` of a run of the traffic generator.
- `--gui`: open the simulation in `sumo-gui`. Without it, SUMO runs headless, which is what the tests and training use.
- `--controller <name>`: use the signal programs in `tls.<name>.add.xml` of the scenario instead of the ones in the network, for example `--controller fixed-x12` on the grid. This also works for the `.sumocfg` of a run, so any run can be combined with any controller. An unknown name lists the available ones.

The `.rou.xml` files of the scenarios hold a small fixed demand, so that every scenario runs without data. Generated traffic is run from the `.sumocfg` of a run, see [traffic-generation.md](traffic-generation.md#running).

## Scenario layout

A scenario directory holds exactly one `.sumocfg` file, which `scripts/run_sumo.py` starts, and the files it lists:

| File | Contents |
|---|---|
| `*.sumocfg` | SUMO configuration: which network and route files to load |
| `*.net.xml` | Road network: edges, lanes, junctions and traffic light programs |
| `*.rou.xml` | Traffic demand: vehicles, routes and flows. In the committed scenarios this is a small fixed demand, so that each scenario runs without data |
| `tls.<name>.add.xml` | Optional: the signal programs of the controller `<name>`, loaded with `--controller <name>`. They are not listed in the `.sumocfg` |
| `scenario.toml` | Optional: the traffic generator config of the scenario, see [traffic-generation.md](traffic-generation.md#config) |
| `runs/` | Generated traffic and outputs of runs, ignored by git. Each run has its own `sumo/run.sumocfg` with the network of the scenario and the generated routes |

A new scenario directory is picked up by the tests automatically: `tests/main/test_scenarios.py` checks that its files exist and are valid XML, and `tests/sumo/` runs it in SUMO.

## Scenarios

### hello-world

A minimal road network with basic vehicle movement, based on the [SUMO Hello World tutorial](https://sumo.dlr.de/docs/Tutorials/Hello_World.html).

### single-intersection

A four-way signalized intersection with bidirectional roads and one lane per direction. It uses fixed-time traffic light control and straight-through flows only: 180 vehicles over 600 seconds.

![Single intersection in SUMO-GUI](images/single-intersection.png)

### grid-2x2

Four signalized junctions in a 2x2 grid, 300 m apart, with one lane per direction, 50 km/h and 300 m roads leading in and out of the grid. The network holds the default fixed-time programs of SUMO, and tuned ones are loaded as a [controller](#fixed-time-baselines). The demand is a placeholder: six flows, straight and with turns, over 600 seconds.

The network was generated with [netgenerate](https://sumo.dlr.de/docs/netgenerate.html); the options are also stored at the top of `grid.net.xml`:

```bash
uv run netgenerate --grid --grid.number 2 --grid.length 300 --grid.attach-length 300 --default.lanenumber 1 --default.speed 13.89 --default-junction-type traffic_light --no-turnarounds -o scenarios/grid-2x2/grid.net.xml
```

`netgenerate` prints a warning that it could not build a program for the traffic light `top1`. It can be ignored: `top1` is a dead end with nothing to control, and the four junctions get their programs.

Junction ids are `A0`, `A1`, `B0` and `B1` (column letter, row number from the bottom), and the outer nodes are `left0`, `top1` and so on. Edge ids join the ids of their start and end node, for example `A0B0`.

The traffic generator and the RL environment rely on these ids, on the turns of every approach and on one signal program per junction. `tests/main/test_grid_network.py` checks them on the network file, so a rebuilt network cannot change them unnoticed.

#### Fixed-time baselines

The fixed-time baseline has one set of programs for each traffic level of the experiments: `fixed-x1`, `fixed-x7`, `fixed-x12` and `fixed-x16`, for the scales 1, 7, 12 and 16 of the traffic generator. Each one is a file `tls.<name>.add.xml` with a program for every junction, so any run can be combined with any of them:

```bash
uv run python scripts/run_sumo.py scenarios/grid-2x2/runs/weekday-x12/sumo/run.sumocfg --controller fixed-x12
```

Without `--controller`, the 90 s programs of the network are used. Code that starts SUMO itself passes the file as `--additional-files`: a program with a new `programID` replaces the one of the network.

| Controller | Cycle | Green at `A0` | `A1` | `B0` | `B1` | Offset of `A0`, `A1`, `B0`, `B1` |
|---|---|---|---|---|---|---|
| `fixed-x1` | 22 s | 8 / 8 s | 8 / 8 s | 8 / 8 s | 8 / 8 s | 0, 3.7, 3.7, 18.4 s |
| `fixed-x7` | 28 s | 11 / 11 s | 14 / 8 s | 8 / 14 s | 11 / 11 s | 0, 25.7, 0.7, 9.4 s |
| `fixed-x12` | 65 s | 29 / 30 s | 51 / 8 s | 8 / 51 s | 30 / 29 s | 0, 25.7, 47.7, 18.4 s |
| `fixed-x16` | 120 s | 57 / 57 s | 106 / 8 s | 8 / 106 s | 58 / 56 s | 0, 25.7, 74.7, 110.4 s |

Green times are for north and south / west and east. The phases are those of the network, two greens with 3 s of yellow after each, so every controller and the RL agent work with the same phases. `tests/main/test_grid_network.py` checks this.

**How they are tuned.** `scripts/tune_fixed_time.py` applies the method of Webster to a run of the traffic generator:

1. *Design hour.* The run of a level is a Monday morning from the Kaggle data, 2017-04-03 from 07:00 to 13:00, with seed 1 and the scale of the level. The design hour is its busiest hour, 11:00 to 12:00. The flow of every approach in that hour comes from `flows/turn_flows.csv` of the run.
2. *Flow ratios.* The flow ratio of a green phase is the highest flow per lane among its approaches, divided by the saturation flow. `Y` is the sum over the phases of a junction.
3. *Cycle.* The busiest junction, `A0`, sets the cycle `C = (1.5 L + 5) / (1 - Y)`, with the lost time `L` of a cycle. It is rounded up to whole seconds and kept between 22 s, which the minimum greens need, and 120 s. All junctions use this cycle, because offsets only hold between equal cycles.
4. *Green split.* At every junction the green time of the cycle is split in proportion to the flow ratios of its phases, with at least the minimum green for each.
5. *Offsets.* `tlsCoordinator.py` of the SUMO tools sets the offsets for the routes of the run, so that vehicles that leave `A0` on green arrive at the next junction on green.

| Assumption | Value | Source |
|---|---|---|
| Saturation flow | 1580 vehicles per hour and lane | Measured in SUMO on the entry lanes of `A0`: vehicles passed per cycle under more demand than capacity, for greens of 12 to 57 s. The slope gives 1570 to 1600 |
| Lost time | 3.3 s per phase, 6.6 s per cycle | Same measurement: about the 3 s of yellow |
| Minimum green | 8 s | Assumed |
| Maximum cycle | 120 s | Assumed |

| Level | Flow on each entry road of `A0` | `Y` at `A0` | Cycle of the formula | Cycle used |
|---|---|---|---|---|
| x1 | 50 vehicles per hour | 0.06 | 15.9 s | 22 s |
| x7 | 355 | 0.45 | 27.1 s | 28 s |
| x12 | 608 | 0.77 | 64.7 s | 65 s |
| x16 | 811 | 1.03 | none | 120 s |

To tune the programs again, for example after a change of the network:

```bash
uv run python scripts/generate_traffic.py --config scenarios/grid-2x2/scenario.toml --start 2017-04-03T07:00 --end 2017-04-03T13:00 --seed 1 --scale 12 --run weekday-x12
uv run python scripts/tune_fixed_time.py scenarios/grid-2x2/runs/weekday-x12 --name fixed-x12
```

**What they achieve.** Mean waiting time of every set of programs on the run of every level, in brackets the mean depart delay where it is 1 s or more. One run each, with 445, 3210, 5487 and 7281 vehicles:

| Programs | x1 run | x7 run | x12 run | x16 run |
|---|---|---|---|---|
| Network, 90 s | 17.8 s | 21.3 s | 28.6 s | 62.2 s (199 s) |
| `fixed-x1` | **3.6 s** | 5.6 s | 23.6 s (197 s) | 29.4 s (1231 s) |
| `fixed-x7` | 3.9 s | **5.1 s** | 20.6 s (13 s) | 28.8 s (647 s) |
| `fixed-x12` | 9.0 s | 9.9 s | **14.6 s** | 43.3 s (254 s) |
| `fixed-x16` | 15.6 s | 19.0 s | 22.3 s | **52.7 s (167 s)** |

The programs of a level are the best ones for its run. No run had collisions, emergency braking or teleports.

**Limits.** This is what an RL agent is compared against, so it matters what the method cannot do:

- *One design hour.* The programs fit the busiest hour of one morning. The same run starts at 07:00 with 40% of that traffic, and gets the long cycle all the same. The table shows what a wrong level costs: `fixed-x16` on the x7 run waits almost four times as long as `fixed-x7`, and `fixed-x7` on the x16 run lets the queues grow out of the network.
- *Blind to the queues.* Durations are fixed. The side roads of `A1` and `B0` get 8 s of green in every cycle, used or not, and a queue on the main road gets no second more.
- *Undefined near saturation.* At x16 the flow ratios of `A0` add up to 1.03, so no cycle serves the design hour and the formula has no answer. `fixed-x16` uses the maximum cycle as a best effort, and the queues still grow out of the network. A longer cycle only moves the wait: in a test without offsets, 180 s instead of 120 s lowered the depart delay from 143 s to 108 s and raised the waiting time from 53 s to 67 s.
- *One junction at a time.* The formula treats a junction on its own, with random arrivals. `A0` sets the cycle for all, so the quiet junctions wait longer than they would with a cycle of their own. Without offsets, the cycle of the formula was the best of five tried at x7, and 2 s behind the best at x12, where 50 s gave 15.0 s against 16.8 s.
- *Coordination is static.* The offsets assume free travel between the junctions for the routes of the design run. They lower the waiting time at x12 from 16.8 s to 14.6 s and by less than 0.5 s at x1 and x7. At x16, where queues decide, runs with different SUMO seeds show no clear difference.
- *Assumptions of the tuning.* The saturation flow depends on the share of turning vehicles and was measured for the entry roads of `A0`. The script also takes all lanes of an approach as served by the same phases, so a network with turn lanes needs an extension.

#### Validation

The network and its signal programs were checked with SUMO 1.28.0 ([#17](https://github.com/iwonieevo/trafficgen-signal-control/issues/17)). One thing changed because of it: the roads in and out of the grid were 100 m long at first and are 300 m now. Ids, lanes, connections and signal programs are the same as before.

**Network.** The `netgenerate` command above recreates `grid.net.xml` exactly, apart from the header comment.

- Nodes: four signalized junctions and eight dead ends, where vehicles enter and leave.
- Edges: 24, one per direction, each with one lane at 13.89 m/s (50 km/h). Lanes are 285.6 m long between junctions and 292.8 m on the roads in and out, because the junction area is cut off the 300 m.
- Connections: every approach turns right, straight and left, which gives 12 connections per junction. There are no U-turns.
- `--no-turnarounds` stays. The traffic generator leaves U-turns out, and its routes go from an entry road to an exit road, so U-turn connections would only add signal links that no vehicle uses.

**Signal programs.** All four junctions have the same fixed-time program with a 90 s cycle, and all start at offset 0:

| Phase | Duration | State | Meaning |
|---|---|---|---|
| 0 | 42 s | `GGgrrrGGgrrr` | Green for north and south |
| 1 | 3 s | `yyyrrryyyrrr` | Yellow |
| 2 | 42 s | `rrrGGgrrrGGg` | Green for west and east |
| 3 | 3 s | `rrryyyrrryyy` | Yellow |

Left turns are permitted, not protected (`g`): they give way to oncoming traffic. There is no all-red phase. Every green is followed by 3 s of yellow, and the runs below had no collisions, emergency braking or teleports.

**Behaviour under load.** Measured with generated traffic: two hours of constant junction counts of 90, 30, 30 and 13 vehicles per hour for J1 to J4, about twice the Kaggle means, times a scale. Departures are `poisson`, and each number is the mean of one run with seed 1, so they show a direction and are not results.

| Scale | Vehicles | Waiting time, 90 s cycle | Waiting time, 40 s cycle |
|---|---|---|---|
| 1 | 182 | 15.5 s | 9.7 s |
| 10 | 1891 | 23.7 s | 11.5 s |
| 15 | 2752 | 45.5 s (8 s) | 43.3 s (90 s) |
| 20 | 3662 | 85.1 s (607 s) | 62.6 s (1053 s) |

In brackets: the mean depart delay, the time a vehicle waits outside the network because its entry lane is full. It is below 1 s where it is not shown. The 40 s cycle is the same program with 17 s of green.

What follows from this:

- **The entry roads have to hold the queues.** Almost all traffic enters at `A0`, on `left0A0` and `bottom0A0`: 675 vehicles per hour each at scale 15. One lane with 42 s of green in 90 s passes about 735, measured under more demand than capacity, so at scale 15 queues build up whenever vehicles arrive in bunches. A 100 m entry road holds about 12 standing vehicles, and the rest of the queue waits outside the network, where the waiting time, detectors and the lane observations of an RL agent do not see it: at scale 15 the waiting time was 33.7 s with a depart delay of 28 s. A 300 m entry road holds about 39, so the same queue stands in the network and is counted: 45.5 s and 8 s. Up to scale 10 both lengths give the same waiting time within 1 s.
- **One lane per approach carries up to about scale 15.** Longer roads add no capacity. At scale 20, each entry road of `A0` gets 900 vehicles per hour, more than the 735 that its lane passes, and the queue grows out of the network again.
- **The 90 s cycle is long for light traffic.** Up to scale 10, a 40 s cycle halves the waiting time. At scale 15 it has too little capacity: the depart delay grows from 8 s to 90 s. The cycle has to be tuned to the load that the experiments use.
- **The junctions are not coordinated.** With offsets from `tlsCoordinator.py` of the SUMO tools, the waiting time at scale 10 drops from 23.7 s to 16.1 s with the same 90 s cycle.
- **The Kaggle volume alone is too low to compare controllers.** At scale 1 the network is almost empty: 182 vehicles in two hours.

The tuned and coordinated programs are the [fixed-time baselines](#fixed-time-baselines) above. Detectors and an actuated controller follow in the next changes for #17.

## Traffic generator configs

A scenario that the traffic generator can feed has a `scenario.toml`, which names the network file and the node of each junction. The traffic generator reads the roads and turns from the network file itself, so road ids are the edge ids of the scenario and a changed network needs no change in the config, unless a node was renamed or added. See [traffic-generation.md](traffic-generation.md#config).

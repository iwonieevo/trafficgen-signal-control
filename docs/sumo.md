# SUMO scenarios

The simulations run in [Eclipse SUMO](https://eclipse.dev/sumo/), installed into `.venv` by `uv sync` (see the README). Each scenario is a directory in `scenarios/`.

## Running a scenario

From the repository root, on any platform:

```bash
uv run python scripts/run_sumo.py <scenario> [--gui]
```

- `<scenario>`: name of a directory in `scenarios/`, or the path of a `.sumocfg` file, for example `scenarios/grid-2x2/runs/<run>/sumo/run.sumocfg` of a run of the traffic generator.
- `--gui`: open the simulation in `sumo-gui`. Without it, SUMO runs headless, which is what the tests and training use.

The `.rou.xml` files of the scenarios hold a small fixed demand, so that every scenario runs without data. Generated traffic is run from the `.sumocfg` of a run, see [traffic-generation.md](traffic-generation.md#running).

## Scenario layout

A scenario directory holds exactly one `.sumocfg` file, which `scripts/run_sumo.py` starts, and the files it lists:

| File | Contents |
|---|---|
| `*.sumocfg` | SUMO configuration: which network and route files to load |
| `*.net.xml` | Road network: edges, lanes, junctions and traffic light programs |
| `*.rou.xml` | Traffic demand: vehicles, routes and flows. In the committed scenarios this is a small fixed demand, so that each scenario runs without data |
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

Four signalized junctions in a 2x2 grid, 300 m apart, with one lane per direction, 50 km/h and 100 m roads leading in and out of the grid. The traffic lights use the default fixed-time programs of SUMO. The demand is a placeholder: six flows, straight and with turns, over 600 seconds.

The network was generated with [netgenerate](https://sumo.dlr.de/docs/netgenerate.html); the options are also stored at the top of `grid.net.xml`:

```bash
uv run netgenerate --grid --grid.number 2 --grid.length 300 --grid.attach-length 100 --default.lanenumber 1 --default.speed 13.89 --default-junction-type traffic_light --no-turnarounds -o scenarios/grid-2x2/grid.net.xml
```

Junction ids are `A0`, `A1`, `B0` and `B1` (column letter, row number from the bottom), and the outer nodes are `left0`, `top1` and so on. Edge ids join the ids of their start and end node, for example `A0B0`.

The traffic generator and the RL environment rely on these ids, on the turns of every approach and on one signal program per junction. `tests/main/test_grid_network.py` checks them on the network file, so a rebuilt network cannot change them unnoticed.

#### Validation

The network and its signal programs were checked as generated, with SUMO 1.28.0 ([#17](https://github.com/iwonieevo/trafficgen-signal-control/issues/17)).

**Network.** The `netgenerate` command above recreates `grid.net.xml` exactly, apart from the header comment.

- Nodes: four signalized junctions and eight dead ends, where vehicles enter and leave.
- Edges: 24, one per direction, each with one lane at 13.89 m/s (50 km/h). Lanes are 285.6 m long between junctions and 92.8 m on the roads in and out, because the junction area is cut off the 300 m and 100 m.
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
| 1 | 182 | 16.3 s | 10.0 s |
| 10 | 1891 | 23.9 s | 12.0 s |
| 15 | 2752 | 33.7 s (28 s) | 26.5 s (139 s) |
| 20 | 3662 | 40.2 s (726 s) | |

In brackets: the mean depart delay, the time a vehicle waits outside the network because its entry lane is full. It is below 1 s where it is not shown. The 40 s cycle is the same program with 17 s of green.

What follows from this:

- **The entry roads are too short for heavier traffic.** Almost all traffic enters at `A0`, on `left0A0` and `bottom0A0`: 675 vehicles per hour each at scale 15. One lane with 42 s of green in 90 s passes roughly 800, so from scale 15 the queues grow. An entry lane holds about 12 standing vehicles, and the rest of the queue waits outside the network, where the waiting time, detectors and the lane observations of an RL agent do not see it.
- **The 90 s cycle is long for light traffic.** Up to scale 10, a 40 s cycle halves the waiting time. At scale 15 it has too little capacity: the depart delay grows from 28 s to 139 s. The cycle has to be tuned to the load that the experiments use.
- **The junctions are not coordinated.** With offsets from `tlsCoordinator.py` of the SUMO tools, the waiting time at scale 10 drops from 23.9 s to 16.6 s with the same 90 s cycle.
- **The Kaggle volume alone is too low to compare controllers.** At scale 1 the network is almost empty: 182 vehicles in two hours.

Longer entry roads, tuned and coordinated fixed-time programs, detectors and an actuated controller follow in the next changes for #17.

## Traffic generator configs

A scenario that the traffic generator can feed has a `scenario.toml`, which names the network file and the node of each junction. The traffic generator reads the roads and turns from the network file itself, so road ids are the edge ids of the scenario and a changed network needs no change in the config, unless a node was renamed or added. See [traffic-generation.md](traffic-generation.md#config).

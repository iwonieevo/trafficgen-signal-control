# Traffic generation

The traffic generator turns historical junction counts into traffic that runs in SUMO. It is built from three steps, which can be used on their own or one after the other:

| Step | Input | Output | Details |
|---|---|---|---|
| Junction counts | Historical hourly counts of each junction | Hourly vehicle counts per junction, for any time range | [junction-counts.md](junction-counts.md) |
| Network flows | Hourly counts per junction, from any source, and a road network | Hourly flows on every road and turn of the network | [network-flows.md](network-flows.md) |
| SUMO input | Network flows and the SUMO network | Vehicles with departure times and routes, and a SUMO config to run them | [below](#sumo-input) |

```
historical counts --> junction counts --> network flows --> SUMO input --> SUMO, RL environment, ...
  data/processed/     counts.csv          flows/*.csv       sumo/routes.rou.xml, sumo/run.sumocfg
```

`scripts/generate_traffic.py` and `trafficgen.generate_traffic` run all three steps with one seed. The junction counts are random: they are sampled from models fitted on the data. The network flows are deterministic: the same counts always give the same flows. The SUMO input is random again: the departure times and the turns of every vehicle are drawn. One seed fixes both random steps, so a run can be reproduced exactly.

## What you provide, configure and get

| Stage | What | Where |
|---|---|---|
| Provide | Historical hourly counts per junction, one CSV file per junction with `datetime` and `vehicles` columns. `scripts/download_kaggle_data.py` writes them for the Kaggle data | `data/` (ignored by git) |
| Configure | The road network, a SUMO `.net.xml` file | `scenarios/<name>/` |
| Configure | The traffic generator config: which data each junction is fitted on, which node of the network it is, the preferred turns and the settings of every step | `scenarios/<name>/scenario.toml` |
| Get | Generated counts, flows and SUMO input of one run, and later simulation outputs and measures of the controllers | `scenarios/<name>/runs/<run>/` (ignored by git) |

A scenario is one directory in `scenarios/`: a SUMO setup that runs on its own (see [sumo.md](sumo.md)) and, when the traffic generator can feed it, a `scenario.toml`. The generated files are never edited by hand: change the config or the network and generate them again.

| Scenario | Junctions |
|---|---|
| `single-intersection` | J1 (node `J0`) |
| `grid-2x2` | J1 (`A0`, bottom left), J2 (`B0`, bottom right), J3 (`A1`, top left), J4 (`B1`, top right) |

## Running

Download the Kaggle data first, as described in the README. Then, from the repository root:

```bash
# Counts, flows and SUMO input for one week of the grid, in scenarios/grid-2x2/runs/week-14/.
uv run python scripts/generate_traffic.py --config scenarios/grid-2x2/scenario.toml --start 2017-04-03T00:00 --end 2017-04-10T00:00 --seed 42 --run week-14

# Run it in SUMO, headless or with --gui.
uv run python scripts/run_sumo.py scenarios/grid-2x2/runs/week-14/sumo/run.sumocfg --gui
```

| Option | Meaning |
|---|---|
| `--config` | Config file, required |
| `--start`, `--end` | First hour and the hour after the last one |
| `--counts` | CSV file of counts per junction, instead of `--start` and `--end`: the junction counts step is skipped, and the counts can come from anywhere |
| `--seed` | Seed of the whole run. Without it, a random seed is drawn and printed |
| `--scale` | Multiplier of the volume, instead of `scale` in `[counts]` |
| `--run` | Name of the run directory, in `runs/` next to the config. By default it is made of the time range or counts file and the seed |
| `--output-dir` | Any other run directory, instead of `--run` |

A run directory holds:

| File | Contents |
|---|---|
| `counts.csv` | Hourly counts per junction |
| `flows/*.csv` | The five tables of the network flows |
| `sumo/entry_flows.xml`, `sumo/turn_ratios.xml` | Entry flows per road and hour, and turn shares per hour, the input of `jtrrouter` |
| `sumo/routes.rou.xml` | Every vehicle with its departure time and route |
| `sumo/run.sumocfg` | The network of the scenario with the routes, ready to run |
| `run.json` | Config, time range, seed, scale, departures and number of vehicles |

Each step also has its own script, which takes any input and output path:

```bash
uv run python scripts/generate_counts.py --config scenarios/grid-2x2/scenario.toml --start 2017-04-03T00:00 --end 2017-04-10T00:00 --seed 42 --output scenarios/grid-2x2/runs/week-14/counts.csv
uv run python scripts/generate_flows.py --config scenarios/grid-2x2/scenario.toml --counts scenarios/grid-2x2/runs/week-14/counts.csv --output-dir scenarios/grid-2x2/runs/week-14/flows
```

Their options and output are described in the doc of each step.

## Using it from code

```python
from trafficgen import generate_traffic

run = generate_traffic(
    "scenarios/grid-2x2/scenario.toml", "2017-04-03", "2017-04-10",
    output_dir="scenarios/grid-2x2/runs/week-14", seed=42,
)
run.counts             # hourly counts per junction
run.flows.turn_flows   # network flows, see network-flows.md
run.sumo.net_file      # SUMO network of the scenario
run.sumo.route_file    # vehicles and routes
run.sumo.config_file   # both together, for sumo -c
run.sumo.end_s         # end of the last hour in simulation seconds
```

This is what a simulation, an RL environment or an experiment needs: for example, `run.sumo.net_file` and `run.sumo.route_file` are what sumo-rl's `SumoEnvironment` takes, and `sumo -c run.sumo.config_file` starts the run with TraCI. `trafficgen.find_sumo_program("sumo")` finds the SUMO program on every platform. Each episode or experiment can use its own run, generated with another time range or seed.

`traffic_from_counts(config, counts, output_dir, seed)` does the same for given counts, and the steps can be called one by one:

```python
from trafficgen import (
    FlowSolver,
    fit_count_models,
    load_counts_config,
    load_network_config,
    load_sumo_config,
    sample_junctions,
    write_sumo_input,
)

config = "scenarios/grid-2x2/scenario.toml"
counts = sample_junctions(fit_count_models(load_counts_config(config)), "2017-04-03", "2017-04-10", seed=42)
flows = FlowSolver(load_network_config(config)).solve(counts)
sumo = write_sumo_input(flows, load_sumo_config(config).net_file, "runs/week-14/sumo", seed=42)
```

## Config

One TOML file describes a whole setup. Each step reads and checks only its own sections, so a step never fails because of a section it does not use:

| Section | Read by | Contents |
|---|---|---|
| `[[junctions]]` | counts, flows | `id`, the key of a junction in every step. `data`, the CSV file of historical counts, read by the junction counts. `node`, the node of the network, read by the network flows |
| `[counts]` | junction counts | Settings of the junction counts |
| `[network]` | network flows, SUMO input | The SUMO network file and the preferred turn directions |
| `[flows]` | network flows | Settings of the network flows |
| `[[roads]]`, `[[turns]]` | network flows | Changes to single roads and turns of the network, or a whole network without `[network]` |
| `[sumo]` | SUMO input | Settings of the SUMO input |

A section or junction key that no step knows, for example a typo, is an error. Relative paths are resolved against the directory of the config file.

The config of the grid:

```toml
[[junctions]]
id = "J1"
data = "../../data/processed/kaggle_junction_1.csv"
node = "A0"

# ... J2, J3 and J4 in the same way

[network]
file = "grid.net.xml"
turn_preferences = { right = 0.15, straight = 0.7, left = 0.15 }

[counts]
scale = 1.0

[flows]
tolerance_vph = 0.5

[sumo]
departures = "poisson"
```

Roads and turns are read from the network file each time the config is loaded, so a changed network needs no change in the config, unless a node was renamed. Road ids are the SUMO edge ids.

## SUMO input

The network flows give vehicles per hour on every entry road and the used share of every turn in every hour. The SUMO input turns them into single vehicles:

1. Every entry road gets one SUMO `<flow>` per hour with the vehicles of its entry flow (`sumo/entry_flows.xml`).
2. Every hour gets one interval of turn ratios with the used shares (`sumo/turn_ratios.xml`).
3. [`jtrrouter`](https://sumo.dlr.de/docs/jtrrouter.html) builds one route per vehicle: at every junction it draws the next road with the turn shares of the hour, until the vehicle reaches an exit road (`sumo/routes.rou.xml`). Routes may pass a road twice, as the shares allow.
4. A SUMO config combines the network of the scenario with the routes (`sumo/run.sumocfg`). Its paths are relative, so the run directory stays valid when the repository moves.

Simulation second 0 is the start of the first hour, and every hour is 3600 seconds. The simulation runs until every vehicle has left the network.

| Key | Where | Default | Meaning |
|---|---|---|---|
| `departures` | `[sumo]` | `poisson` | `poisson`: the vehicles of an hour depart at random times, so the number per hour varies around the flow, as in real traffic. `uniform`: they depart evenly spaced, and fractions of a vehicle are carried over to the next hour, so the number per hour follows the flow as closely as whole vehicles can |

Two things in the network flows have no equivalent in this input:

- Roads with `through_share` below 1 are rejected: in SUMO, every vehicle on a road reaches its end.
- Flows are rates. With `poisson`, a flow below 0.01 vehicles per hour is left out of its hour.

### How close the simulation gets to the counts

The traffic through a junction in the simulation is the number of vehicles that leave the roads ending at it. With the Kaggle data on the grid for one day (`notebooks/traffic_generation.ipynb`), the simulated daily totals are within 5% of the requested ones at every junction. Hour by hour they differ, because departures and turns are random and vehicles take some time to reach a junction. With `uniform` departures, J1, where almost all traffic enters, matches within one vehicle per hour on average; the quieter junctions still vary, because their traffic comes from their neighbours through random turns. `tests/sumo/test_generated_traffic.py` checks these bounds with SUMO.

## Code

| Path | Contents |
|---|---|
| `src/trafficgen/config.py` | Reading the shared config file |
| `src/trafficgen/data.py` | Reading count CSV files |
| `src/trafficgen/timeutils.py` | Time constants and hourly ranges |
| `src/trafficgen/counts/` | Junction counts: models, sampling, their config, fit checks |
| `src/trafficgen/flows/` | Network flows: the network and reading it from a SUMO file, their config and checks, the solver, the result tables |
| `src/trafficgen/simulation/` | SUMO input: the `[sumo]` config, the flow, turn and config files, `jtrrouter`, finding the SUMO programs |
| `src/trafficgen/pipeline.py` | `generate_traffic` and `traffic_from_counts`: the steps together, written to one run directory |
| `scripts/generate_traffic.py` | All steps from the command line |
| `scripts/generate_counts.py` | Junction counts from the command line |
| `scripts/generate_flows.py` | Network flows from the command line |

The junction counts and the network flows do not import each other. The SUMO input uses only the output of the network flows. The shared modules know nothing about any step.

## Notebooks

- `notebooks/kaggle_data_eda.ipynb`: exploratory analysis of the Kaggle data.
- `notebooks/junction_counts_fit.ipynb`: how well the junction counts models fit the data.
- `notebooks/network_flows.ipynb`: what the network flows do with a week of counts, on the single intersection and the 2x2 grid.
- `notebooks/traffic_generation.ipynb`: all steps for one day on the 2x2 grid, run in SUMO and compared with the requested counts.

Open them with `uv run jupyter lab`.

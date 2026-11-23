# Traffic generation

The traffic generator turns historical junction counts into traffic for a road network. It has two parts, which can be used on their own or one after the other:

| Part | Input | Output | Details |
|---|---|---|---|
| Junction counts | Historical hourly counts of each junction | Hourly vehicle counts per junction, for any time range | [junction-counts.md](junction-counts.md) |
| Network flows | Hourly counts per junction, from any source, and a road network | Hourly flows on every road and turn of the network | [network-flows.md](network-flows.md) |

```
historical counts --> junction counts --> counts.csv --> network flows --> flow tables --> SUMO (planned)
  data/processed/     generate_counts.py                 generate_flows.py
```

The junction counts are random: they are sampled from models fitted on the data, and a seed makes them reproducible. The network flows are deterministic: the same counts always give the same flows. Turning the flow tables into SUMO input is planned in [issue #13](https://github.com/iwonieevo/trafficgen-signal-control/issues/13).

## What you provide, configure and get

| Stage | What | Where |
|---|---|---|
| Provide | Historical hourly counts per junction, one CSV file per junction with `datetime` and `vehicles` columns. `scripts/download_kaggle_data.py` writes them for the Kaggle data | `data/` (ignored by git) |
| Configure | The road network, a SUMO `.net.xml` file | `scenarios/<name>/` |
| Configure | The traffic generator config: which data each junction is fitted on, which node of the network it is, the preferred turns and the settings of both parts | `scenarios/<name>/scenario.toml` |
| Get | Generated counts and flows, and later SUMO input, simulation outputs and measures of the controllers | `scenarios/<name>/runs/<run>/` (ignored by git) |

A scenario is one directory in `scenarios/`: a SUMO setup that runs on its own (see [sumo.md](sumo.md)) and, when the traffic generator can feed it, a `scenario.toml`. The generated files are never edited by hand: change the config or the network and generate them again.

| Scenario | Junctions |
|---|---|
| `single-intersection` | J1 (node `J0`) |
| `grid-2x2` | J1 (`A0`, bottom left), J2 (`B0`, bottom right), J3 (`A1`, top left), J4 (`B1`, top right) |

## Running

Download the Kaggle data first, as described in the README. Then, from the repository root:

```bash
# Hourly counts of every junction of the grid, for one week.
uv run python scripts/generate_counts.py --config scenarios/grid-2x2/scenario.toml --start 2017-04-03T00:00 --end 2017-04-10T00:00 --seed 42 --output scenarios/grid-2x2/runs/week-14/counts.csv

# Flows on every road and turn of the grid for those counts.
uv run python scripts/generate_flows.py --config scenarios/grid-2x2/scenario.toml --counts scenarios/grid-2x2/runs/week-14/counts.csv --output-dir scenarios/grid-2x2/runs/week-14/flows
```

Both scripts need `--config` and take any output path; the scenario layout above is a convention, not a requirement. Each script, its options and its output are described in the doc of its part.

From Python:

```python
from trafficgen import (
    FlowSolver,
    fit_count_models,
    load_counts_config,
    load_network_config,
    sample_junctions,
)

config = "scenarios/grid-2x2/scenario.toml"
models = fit_count_models(load_counts_config(config))
counts = sample_junctions(models, "2017-04-03", "2017-04-10", seed=42)
flows = FlowSolver(load_network_config(config)).solve(counts)
flows.turn_flows
```

## Config

One TOML file describes a whole setup. Each part reads and checks only its own sections, so a part never fails because of a section it does not use:

| Section | Read by | Contents |
|---|---|---|
| `[[junctions]]` | both | `id`, the key of a junction in both parts. `data`, the CSV file of historical counts, read by the junction counts. `node`, the node of the network, read by the network flows |
| `[counts]` | junction counts | Settings of the junction counts |
| `[network]` | network flows | The SUMO network file and the preferred turn directions |
| `[flows]` | network flows | Settings of the network flows |
| `[[roads]]`, `[[turns]]` | network flows | Changes to single roads and turns of the network, or a whole network without `[network]` |

A section or junction key that neither part knows, for example a typo, is an error. Relative paths are resolved against the directory of the config file.

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
```

Roads and turns are read from the network file each time the config is loaded, so a changed network needs no change in the config, unless a node was renamed. Road ids are the SUMO edge ids.

## Code

| Path | Contents |
|---|---|
| `src/trafficgen/config.py` | Reading the shared config file |
| `src/trafficgen/data.py` | Reading count CSV files |
| `src/trafficgen/timeutils.py` | Time constants and hourly ranges |
| `src/trafficgen/counts/` | Junction counts: models, sampling, their config, fit checks |
| `src/trafficgen/flows/` | Network flows: the network and reading it from a SUMO file, their config and checks, the solver, the result tables |
| `scripts/generate_counts.py` | Junction counts from the command line |
| `scripts/generate_flows.py` | Network flows from the command line |

The two parts do not import each other. The shared modules know nothing about either part.

## Notebooks

- `notebooks/kaggle_data_eda.ipynb`: exploratory analysis of the Kaggle data.
- `notebooks/junction_counts_fit.ipynb`: how well the junction counts models fit the data.
- `notebooks/network_flows.ipynb`: what the network flows do with a week of counts, on the single intersection and the 2x2 grid.

Open them with `uv run jupyter lab`.

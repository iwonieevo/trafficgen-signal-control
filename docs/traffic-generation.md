# Traffic generation

The traffic generator turns historical junction counts into traffic for a road network. It has two parts, which can be used on their own or one after the other:

| Part | Input | Output | Details |
|---|---|---|---|
| Junction counts | Historical hourly counts of each junction | Hourly vehicle counts per junction, for any time range | [junction-counts.md](junction-counts.md) |
| Network flows | Hourly counts per junction, from any source | Hourly flows on every road and turn of a network | [network-flows.md](network-flows.md) |

```
historical counts --> junction counts --> counts.csv --> network flows --> flow tables --> SUMO (planned)
  data/processed/     generate_counts.py                 generate_flows.py   outputs/
```

The junction counts are random: they are sampled from models fitted on the data, and a seed makes them reproducible. The network flows are deterministic: the same counts always give the same flows. Turning the flow tables into SUMO input is planned in [issue #13](https://github.com/iwonieevo/trafficgen-signal-control/issues/13).

## Running

Download the Kaggle data first, as described in the README. Then, from the repository root:

```bash
# Hourly counts of every junction of the config, for one week.
uv run python scripts/generate_counts.py --start 2017-04-03T00:00 --end 2017-04-10T00:00 --seed 42 --output outputs/counts.csv

# Flows on every road and turn of the network for those counts.
uv run python scripts/generate_flows.py --counts outputs/counts.csv --output-dir outputs/flows
```

Both scripts use `configs/grid_2x2.toml` unless `--config` is given. `outputs/` is ignored by git. Each script, its options and its output are described in the doc of its part.

From Python:

```python
from trafficgen import (
    FlowSolver,
    fit_count_models,
    load_counts_config,
    load_network_config,
    sample_junctions,
)

models = fit_count_models(load_counts_config("configs/grid_2x2.toml"))
counts = sample_junctions(models, "2017-04-03", "2017-04-10", seed=42)
flows = FlowSolver(load_network_config("configs/grid_2x2.toml")).solve(counts)
flows.turn_flows
```

## Config

One TOML file describes a whole setup. Each part reads and checks only its own sections, so a part never fails because of a section it does not use:

| Section | Read by | Contents |
|---|---|---|
| `[[junctions]]` | both | `id`, used by both parts as the key of a junction. `data`, the CSV file of historical counts, used only by the junction counts |
| `[counts]` | junction counts | Settings of the junction counts |
| `[flows]` | network flows | Settings of the network flows |
| `[[roads]]`, `[[turns]]` | network flows | The network |

A section that neither part knows, for example a typo, is an error. Relative paths are resolved against the directory of the config file.

The configs in `configs/` match the SUMO scenarios of the same name in `sumo/scenarios/`:

| Config | SUMO scenario | Junctions |
|---|---|---|
| `single_intersection.toml` | `single-intersection` | J1 |
| `grid_2x2.toml` | `grid-2x2` | J1 (bottom left), J2 (bottom right), J3 (top left), J4 (top right) |

Both are generated from the SUMO network by `scripts/generate_config.py`, so that road ids are the SUMO edge ids. The first lines of each file hold the command that wrote it, and a test checks that the committed files match their command. Regenerate a config instead of editing it by hand, or copy it to a new file for manual changes:

```bash
uv run python scripts/generate_config.py sumo/scenarios/grid-2x2/grid.net.xml --junction A0=J1 --junction B0=J2 --junction A1=J3 --junction B1=J4 --output configs/grid_2x2.toml
```

- `--junction NODE=JUNCTION`: a SUMO node and the junction id it gets. Every node that is not a dead end needs one. Dead ends are the boundary of the network.
- `--turn-preferences RIGHT STRAIGHT LEFT`: preferences of the turn directions, from the `dir` of each SUMO connection (default 0.15 0.7 0.15).
- `--data-template`: data path of each junction relative to the config. `{number}` is the position of its `--junction` option (default `../data/processed/kaggle_junction_{number}.csv`).

## Code

| Path | Contents |
|---|---|
| `src/trafficgen/config.py` | Reading the shared config file |
| `src/trafficgen/data.py` | Reading count CSV files |
| `src/trafficgen/timeutils.py` | Time constants and hourly ranges |
| `src/trafficgen/counts/` | Junction counts: models, sampling, their config, fit checks |
| `src/trafficgen/flows/` | Network flows: their config and checks, the solver, the result tables |
| `scripts/generate_counts.py` | Junction counts from the command line |
| `scripts/generate_flows.py` | Network flows from the command line |
| `scripts/generate_config.py` | Config generation from a SUMO network |

The two parts do not import each other. The shared modules know nothing about either part.

## Notebooks

- `notebooks/kaggle_data_eda.ipynb`: exploratory analysis of the Kaggle data.
- `notebooks/junction_counts_fit.ipynb`: how well the junction counts models fit the data.
- `notebooks/network_flows.ipynb`: what the network flows do with a week of counts, on the single intersection and the 2x2 grid.

Open them with `uv run jupyter lab`.

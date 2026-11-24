# Traffic Generation and Signal Control

The project aims to simulate road traffic and develop intelligent traffic signal control using machine learning.

The system combines:

- Traffic generation based on historical traffic volume data.
- Traffic simulation using Eclipse SUMO.
- Traffic signal control using Reinforcement Learning.
- Evaluation against conventional traffic signal control strategies.

The primary data source is the [Traffic Prediction Dataset](https://www.kaggle.com/datasets/fedesoriano/traffic-prediction-dataset).

## Setup

Requirements:

- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs the Python version from `.python-version` and all Python dependencies
- Git

Clone the repository and install the project dependencies, including SUMO 1.28.0 (about 500 MB), into `.venv`:

```bash
git clone https://github.com/iwonieevo/trafficgen-signal-control.git
cd trafficgen-signal-control
uv sync
```

SUMO is installed from the `eclipse-sumo` package, which has builds for Linux, Windows (x86-64) and macOS 15 or newer on Apple silicon. There is no build for Intel Macs: install [SUMO](https://sumo.dlr.de/docs/Installing/index.html) separately, and add `--no-group sumo` to the `uv` commands. On macOS, the official documentation lists [XQuartz](https://sumo.dlr.de/docs/Installing/index.html) as a requirement for `sumo-gui`.

Download the Kaggle dataset and split it into one file per junction in `data/processed/` (no Kaggle account is needed):

```bash
uv run python scripts/download_kaggle_data.py
```

## Quick start

All commands run from the repository root, on any platform.

Run a SUMO scenario, with or without the GUI:

```bash
uv run python scripts/run_sumo.py single-intersection --gui
```

Generate a week of traffic for the 2x2 grid from the Kaggle data, then run it in SUMO:

```bash
uv run python scripts/generate_traffic.py --config scenarios/grid-2x2/scenario.toml --start 2017-04-03T00:00 --end 2017-04-10T00:00 --seed 42 --run week-14
uv run python scripts/run_sumo.py scenarios/grid-2x2/runs/week-14/sumo/run.sumocfg --gui
```

The first command writes the junction counts, the network flows and the SUMO input of the run to `scenarios/grid-2x2/runs/week-14/`. What goes into a scenario, what is configured and what is generated, how to run each step on its own and how to use a run from Python is described in [docs/traffic-generation.md](docs/traffic-generation.md).

## Documentation

| Doc | Contents |
|---|---|
| [docs/traffic-generation.md](docs/traffic-generation.md) | The traffic generator as a whole: what you provide, configure and get, its steps, the shared config, the SUMO input and using a run from code |
| [docs/junction-counts.md](docs/junction-counts.md) | Junction counts: the model of hourly counts per junction, its data, config, script and output |
| [docs/network-flows.md](docs/network-flows.md) | Network flows: how counts are spread over the roads and turns of a network, config, script and output |
| [docs/sumo.md](docs/sumo.md) | SUMO scenarios: running them, their files, the available scenarios |

Notebooks, opened with `uv run jupyter lab`:

- `notebooks/kaggle_data_eda.ipynb`: exploratory analysis of the Kaggle dataset.
- `notebooks/junction_counts_fit.ipynb`: how well the junction counts models fit the data.
- `notebooks/network_flows.ipynb`: what the network flows do with a week of counts.
- `notebooks/traffic_generation.ipynb`: the whole traffic generator for one day, run in SUMO and compared with the requested counts.

## Development

Add a dependency with `uv add <package>`, or `uv add --group <group> <package>` for a dependency group. Commit the updated `uv.lock`.

Run the same checks as CI before pushing:

```bash
uv run ruff check .
uv run pyright
uv run pytest tests/main
```

Tests are grouped by what they need:

| Group | What it tests | Where it runs |
|---|---|---|
| `tests/main/` | Generator, scripts and scenario files, without SUMO | `CI` workflow, on every pull request |
| `tests/sumo/` | Scenarios and generated traffic in the real simulator | `SUMO` workflow, when the scenarios, the generator, scripts or SUMO tests change |
| `tests/notebooks/` | Runs every notebook, needs the downloaded dataset | Only by hand |

`uv run pytest` runs the first two groups. Run the notebooks with `uv run pytest tests/notebooks` when a change could affect them.

Workflows run on Ubuntu with the Python version from `.python-version`. To check Windows and macOS as well, start the `All platforms` workflow by hand, from the Actions tab or with:

```bash
gh workflow run all-platforms.yml --ref <branch>
```

The project is pinned to Python 3.14, the only version used in development and CI. `pyproject.toml` allows Python 3.12 and newer, so 3.12 should work in theory, but it is not tested.

## Project structure

| Path | Description |
|---|---|
| `src/trafficgen/` | Traffic generator package: junction counts in `counts/`, network flows in `flows/`, SUMO input in `simulation/`, all together in `pipeline.py` |
| `data/` | Downloaded and processed data, ignored by git |
| `scenarios/` | One directory per scenario: SUMO files, traffic generator config, generated runs (ignored by git) |
| `scripts/` | Downloading data, generating traffic, running simulations |
| `notebooks/` | Data analysis, model fit and network flows |
| `tests/` | Automated tests, grouped by what they need |
| `docs/` | Documentation of the project parts |

## License

[MIT](LICENSE)

## References

- [SUMO Documentation](https://sumo.dlr.de/docs/)
- [Traffic Prediction Dataset](https://www.kaggle.com/datasets/fedesoriano/traffic-prediction-dataset)
- [SUMO-RL](https://github.com/LucasAlegre/sumo-rl)

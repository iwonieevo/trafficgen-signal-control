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

Generate a week of hourly counts for the junctions of the 2x2 grid, then the flows on every road and turn of the grid:

```bash
uv run python scripts/generate_counts.py --start 2017-04-03T00:00 --end 2017-04-10T00:00 --seed 42 --output outputs/counts.csv
uv run python scripts/generate_flows.py --counts outputs/counts.csv --output-dir outputs/flows
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/traffic-generation.md](docs/traffic-generation.md) | The traffic generator as a whole: its two parts, the shared config, which script to run when |
| [docs/junction-counts.md](docs/junction-counts.md) | Junction counts: the model of hourly counts per junction, its data, config, script and output |
| [docs/network-flows.md](docs/network-flows.md) | Network flows: how counts are spread over the roads and turns of a network, config, script and output |
| [docs/sumo.md](docs/sumo.md) | SUMO scenarios: running them, their layout, the available scenarios |

Notebooks, opened with `uv run jupyter lab`:

- `notebooks/kaggle_data_eda.ipynb`: exploratory analysis of the Kaggle dataset.
- `notebooks/junction_counts_fit.ipynb`: how well the junction counts models fit the data.
- `notebooks/network_flows.ipynb`: what the network flows do with a week of counts.

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
| `tests/sumo/` | Scenarios in the real simulator | `SUMO` workflow, when SUMO files change |
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
| `src/trafficgen/` | Traffic generator package: junction counts in `counts/`, network flows in `flows/` |
| `configs/` | Traffic generator configs, matching the SUMO scenarios of the same name |
| `sumo/scenarios/` | SUMO simulation scenarios |
| `scripts/` | Downloading data, generating traffic and configs, running simulations |
| `notebooks/` | Data analysis, model fit and network flows |
| `tests/` | Automated tests, grouped by what they need |
| `docs/` | Documentation of the project parts |

## License

[MIT](LICENSE)

## References

- [SUMO Documentation](https://sumo.dlr.de/docs/)
- [Traffic Prediction Dataset](https://www.kaggle.com/datasets/fedesoriano/traffic-prediction-dataset)
- [SUMO-RL](https://github.com/LucasAlegre/sumo-rl)

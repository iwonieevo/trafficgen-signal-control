# Traffic Generation and Signal Control

## Overview

The project aims to simulate road traffic and develop intelligent traffic signal control using machine learning.

The system combines:

- Traffic generation based on historical traffic volume data.
- Traffic simulation using Eclipse SUMO.
- Traffic signal control using Reinforcement Learning.
- Evaluation against conventional traffic signal control strategies.

The primary data source is the [Traffic Prediction Dataset](https://www.kaggle.com/datasets/fedesoriano/traffic-prediction-dataset).

## Getting Started

### Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs the Python version from `.python-version` and all Python dependencies
- Git
- Bash (for the current simulation launcher)

### Installation

Install the project dependencies, including SUMO 1.28.0 (about 500 MB), into `.venv`:

```bash
uv sync
```

The current launcher uses a Bash script and is intended for Linux-based environments. Other platforms may require different commands to launch SUMO.

### Running Simulations

Run the following command from the repository root:

```text
Usage: ./scripts/run-sumo.sh <scenario> [gui]
```

- `<scenario>`: name of a directory in `sumo/scenarios/`.
- `gui`: optional argument to launch the simulation with SUMO-GUI. Without it, the simulation runs headlessly.

Example:

```bash
./scripts/run-sumo.sh single-intersection gui
```

### Generating Traffic

Download the dataset and split it into one file per junction in `data/processed/` (no Kaggle account is needed):

```bash
uv run python scripts/download_data.py
```

Generate hourly vehicle counts for one junction. The start is included, the end is excluded, and both must be whole hours:

```bash
uv run python scripts/generate_traffic.py --junction J1 --start 2017-04-03T00:00 --end 2017-04-10T00:00 --seed 42 --output outputs/j1.csv
```

Junctions and their data files are defined in `configs/traffic.toml`. To use your own data, point a junction to a CSV file like this, with whole hours and no duplicate datetimes:

```text
datetime,vehicles
2017-04-03 00:00:00,48
2017-04-03 01:00:00,37
```

From Python:

```python
from trafficgen import build_generators, load_config

generators = build_generators(load_config("configs/traffic.toml"))
counts = generators["J1"].sample("2017-04-03", "2017-04-10", seed=42)
```

`notebooks/traffic_generation.ipynb` shows how the model is built and compares generated traffic with the real data. Open it with `uv run jupyter lab`.

### Development

Add a dependency with `uv add <package>`, or `uv add --group <group> <package>` for a dependency group. Commit the updated `uv.lock`.

Run the same checks as CI before pushing:

```bash
uv run ruff check .
uv run pytest
```

## Project Structure

The repository is under active development.

| Path | Description |
|---|---|
| `src/trafficgen/` | Traffic generator package |
| `configs/` | Traffic generator configuration |
| `notebooks/` | Model development and validation |
| `sumo/scenarios/` | SUMO simulation scenarios |
| `scripts/` | Utilities for downloading data, generating traffic and running simulations |
| `tests/` | Automated tests |
| `docs/images/` | Images used in project documentation |

## Available Scenarios

### Hello World

A minimal road network demonstrating basic vehicle movement in SUMO.

Based on the [official SUMO Hello World tutorial](https://sumo.dlr.de/docs/Tutorials/Hello_World.html).

### Single Intersection

A four-way signalized intersection with bidirectional roads and one lane per direction.

The initial scenario uses fixed-time traffic light control and straight-through traffic flows only.

Traffic demand consists of 180 vehicles generated over 600 seconds.

Turning movements and additional traffic scenarios may be introduced later.

![Single intersection in SUMO-GUI](docs/images/single-intersection.png)

## References

- [SUMO Documentation](https://sumo.dlr.de/docs/)
- [Traffic Prediction Dataset](https://www.kaggle.com/datasets/fedesoriano/traffic-prediction-dataset)
- [SUMO-RL](https://github.com/LucasAlegre/sumo-rl)

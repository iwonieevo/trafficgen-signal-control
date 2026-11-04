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

- Python 3
- Git
- Bash (for the current simulation launcher)
- SUMO 1.28.0

### Installation

Create a Python virtual environment:

```bash
python -m venv .venv
```

Install the project dependencies:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

The current launcher uses a Bash script and is intended for Linux-based environments. Other platforms may require different commands to launch SUMO.

### Running Simulations

Run the following command from the repository root:

```text
Usage: ./scripts/run-sumo.sh <scenario> [gui]
```

- `<scenario>` — name of a directory in `sumo/scenarios/`.
- `gui` — optional argument to launch the simulation with SUMO-GUI. Without it, the simulation runs headlessly.

Example:

```bash
./scripts/run-sumo.sh single-intersection gui
```

## Project Structure

The repository is under active development.

| Path | Description |
|---|---|
| `sumo/scenarios/` | SUMO simulation scenarios |
| `scripts/` | Utilities for running simulations |
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

# Junction counts

The junction counts generate hourly vehicle counts per junction for any time range. One model is fitted on the historical counts of each junction, and new counts are sampled from it. The models know nothing about roads or turns: spreading the counts over a network is the job of the [network flows](network-flows.md). How the two parts fit together is described in [traffic-generation.md](traffic-generation.md).

## Data

The historical counts of a junction are a CSV file with whole hours, no duplicate datetimes and at least one full week of consecutive hours. Gaps between hours are allowed.

```text
datetime,vehicles
2017-04-03 00:00:00,48
2017-04-03 01:00:00,37
```

`scripts/download_kaggle_data.py` writes one such file per junction of the Kaggle dataset to `data/processed/`. Any other data in this format works the same way, including artificial data.

## Model

The model is a classical decomposition of `y = log(1 + count)`:

```
y[t] = level[t] + profile[weekday, hour] + noise[t]
```

- **Level:** a four week moving average centred on each hour. Near the start and end of the data, the window only covers the hours that exist, at least two weeks.
- **Profile:** the average of `y - level` per weekday and hour.
- **Noise:** what remains, `y - level - profile`, kept as it is.

Sampling adds random one week blocks of the fitted noise to `level + profile` (a block bootstrap) and returns `round(scale * max(exp(...) - 1, 0))`. Blocks keep the persistence of real noise, including bursts over several days. The log scale makes the noise proportional to the volume.

Inside the fitted period, the level follows the data. Outside it, the level stays at its first or last value: less than two years of data cannot separate growth from the time of year, so neither is extrapolated.

`MeanProfileModel` is a simpler baseline: the average count per weekday and hour with Poisson noise. It is only used for comparison in the fit notebook.

Sources are listed in the docstrings of `trafficgen.counts.models`, and `notebooks/junction_counts_fit.ipynb` checks the fit on the data and on months the model has not seen.

## Several junctions

`sample_junctions` samples several junctions together. Each junction keeps its own model, but every week of the output uses the same calendar week of the fitted noise at all junctions. Real junctions are busier or quieter together, for example on holidays, and drawing the same weeks keeps that correlation without a joint model. When a junction has no data for the drawn week, it uses a random week of its own. In the Kaggle data, J4 only covers January to June 2017, so its correlation with the others is kept only for weeks drawn from that period.

One seed gives the whole table. The counts of a junction depend on which junctions are sampled together, so the script always samples every junction of the config and only then selects the requested ones.

## Config

The junction counts read `[[junctions]]` and `[counts]` of the [shared config](traffic-generation.md#config):

| Key | Where | Default | Meaning |
|---|---|---|---|
| `id` | `[[junctions]]` | required | Unique name of the junction |
| `data` | `[[junctions]]` | required | CSV file of historical counts, relative to the config file |
| `scale` | `[counts]` | 1 | Multiplier of the generated volume, for example to create more congestion |

## Running

```bash
uv run python scripts/generate_counts.py --start 2017-04-03T00:00 --end 2017-04-10T00:00 --seed 42 --output outputs/counts.csv
```

| Option | Meaning |
|---|---|
| `--config` | Config file, default `configs/grid_2x2.toml` |
| `--start`, `--end` | First hour and the hour after the last one. Both must be whole hours |
| `--junction` | Junction to write, repeat for several. Default: all |
| `--seed` | Seed for reproducible output. Without it, every run differs |
| `--scale` | Overrides `scale` of the config |
| `--output` | CSV file to write. Default: stdout |

The output has a `datetime` column and one column per junction, the input format of the network flows:

```text
datetime,J1,J2,J3,J4
2017-04-03 00:00:00,48,13,14,8
```

From Python:

```python
from trafficgen import fit_count_models, load_counts_config, sample_junctions

models = fit_count_models(load_counts_config("configs/grid_2x2.toml"))
counts = sample_junctions(models, "2017-04-03", "2017-04-10", seed=42)
one_junction = models["J1"].sample("2017-04-03", "2017-04-10", seed=42)
```

## Code

| Module | Contents |
|---|---|
| `trafficgen.counts.models` | `StatisticalCountModel`, `MeanProfileModel` and their checks of the data |
| `trafficgen.counts.sampling` | `sample_junctions` |
| `trafficgen.counts.config` | `load_counts_config`, `fit_count_models` |
| `trafficgen.counts.fit_quality` | Measures that compare generated and real counts, used by the fit notebook |

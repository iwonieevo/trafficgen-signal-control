"""
Usage:
    python prepare_data.py [--input traffic.csv] [--output data/processed]

Without --input data is derived from Kaggle (kagglehub).
"""
import argparse
import json
from pathlib import Path

import kagglehub
import numpy as np
import pandas as pd

KAGGLE_DATASET = "fedesoriano/traffic-prediction-dataset"
MIN_SCALER_OBS = 24 * 7


def default_input():
    return Path(kagglehub.dataset_download(KAGGLE_DATASET)) / "traffic.csv"


def load_raw(path):
    df = pd.read_csv(path, parse_dates=["DateTime"])
    df = df.drop(columns=["ID"], errors="ignore")
    return df


def to_wide(df):
    dup = df.duplicated(subset=["DateTime", "Junction"]).sum()
    if dup:
        print(f"Duplicates (DateTime, Junction): {dup}, averaging")
    wide = df.pivot_table(
        index="DateTime", columns="Junction", values="Vehicles", aggfunc="mean"
    )
    wide.columns = [f"J{c}" for c in wide.columns]
    full_index = pd.date_range(wide.index.min(), wide.index.max(), freq="h")
    return wide.reindex(full_index).rename_axis("DateTime")


def report(wide):
    print("\nTimespan and missing samples for each junction:")
    for col in wide.columns:
        s = wide[col]
        valid = s.dropna()
        print(
            f"  {col}: {valid.index.min()} -> {valid.index.max()}, "
            f"observations: {len(valid)}, samples missing in range: "
            f"{s.loc[valid.index.min():valid.index.max()].isna().sum()}"
        )


def fill_gaps(wide, max_gap):
    # Interpolacja tylko wewnątrz szeregu, bez uzupełniania początku i końca
    return wide.interpolate(method="time", limit=max_gap, limit_area="inside")


def add_calendar(wide):
    out = wide.copy()
    idx = out.index
    out["hour"] = idx.hour
    out["day_of_week"] = idx.day_of_week
    out["month"] = idx.month
    out["is_weekend"] = (idx.day_of_week >= 5).astype(int)
    out["hour_sin"] = np.sin(2 * np.pi * idx.hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * idx.hour / 24)
    out["dow_sin"] = np.sin(2 * np.pi * idx.day_of_week / 7)
    out["dow_cos"] = np.cos(2 * np.pi * idx.day_of_week / 7)
    return out


def chronological_split(df, train_frac, val_frac):
    n = len(df)
    i_train = int(n * train_frac)
    i_val = int(n * (train_frac + val_frac))
    return df.iloc[:i_train], df.iloc[i_train:i_val], df.iloc[i_val:]


def fit_scaler(train, val, cols):
    scaler = {}
    for c in cols:
        source, fit_on = train[c], "train"
        if source.count() < MIN_SCALER_OBS:
            source, fit_on = pd.concat([train[c], val[c]]), "train+val"
            print(f"{c}: too little samples in train, scaler adjusted for train+val")
        if source.count() < MIN_SCALER_OBS:
            raise ValueError(f"{c}: too little samples to adjust the scaler: {source.count()}")
        scaler[c] = {"mean": float(source.mean()), "std": float(source.std()), "fit_on": fit_on}
    return scaler


def apply_scaler(df, scaler):
    out = df.copy()
    for c, p in scaler.items():
        out[f"{c}_norm"] = (out[c] - p["mean"]) / p["std"]
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default="data/processed")
    parser.add_argument("--max-gap", type=int, default=3)
    parser.add_argument("--train-frac", type=float, default=0.7)
    parser.add_argument("--val-frac", type=float, default=0.15)
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = load_raw(args.input or default_input())
    wide = to_wide(raw)
    report(wide)

    junction_cols = list(wide.columns)
    wide = fill_gaps(wide, args.max_gap)
    wide = add_calendar(wide)

    train, val, test = chronological_split(wide, args.train_frac, args.val_frac)
    scaler = fit_scaler(train, val, junction_cols)

    for name, part in [("train", train), ("val", val), ("test", test)]:
        part = apply_scaler(part, scaler)
        part.to_csv(out_dir / f"{name}.csv")
        print(f"{name}: {part.index.min()} -> {part.index.max()}, rows: {len(part)}")

    with open(out_dir / "scaler.json", "w") as f:
        json.dump(scaler, f, indent=2)

    print(f"\nSaved into {out_dir}")


if __name__ == "__main__":
    main()
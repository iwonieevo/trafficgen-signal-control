"""Download the Kaggle Traffic Prediction Dataset and split it into one file per junction."""

import io
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

DATASET_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/fedesoriano/traffic-prediction-dataset"
)
FILE_NAME = "traffic.csv"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


def download_dataset() -> Path:
    """Download the dataset archive and extract the CSV file.

    Returns:
        Path of the extracted file.
    """
    request = urllib.request.Request(DATASET_URL, headers={"User-Agent": "trafficgen"})
    with urllib.request.urlopen(request, timeout=60) as response:
        archive = response.read()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / FILE_NAME
    with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
        target.write_bytes(zip_file.read(FILE_NAME))
    return target


def split_junctions(source: Path) -> None:
    """Write one CSV file per junction, with the columns ``datetime`` and ``vehicles``.

    Args:
        source: CSV file of the Kaggle dataset.
    """
    frame = pd.read_csv(source)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for junction, rows in frame.groupby("Junction"):
        target = PROCESSED_DIR / f"junction_{junction}.csv"
        renamed = rows.rename(columns={"DateTime": "datetime", "Vehicles": "vehicles"})
        renamed[["datetime", "vehicles"]].to_csv(target, index=False)
        print(f"Saved {target}")


def main() -> None:
    """Download the dataset and split it into junctions."""
    split_junctions(download_dataset())


if __name__ == "__main__":
    main()

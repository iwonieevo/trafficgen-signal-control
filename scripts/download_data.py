"""Download the Kaggle Traffic Prediction Dataset into data/raw."""

import io
import urllib.request
import zipfile
from pathlib import Path

DATASET_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/fedesoriano/traffic-prediction-dataset"
)
FILE_NAME = "traffic.csv"
TARGET_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def main() -> None:
    """Download the dataset archive and extract the CSV file."""
    request = urllib.request.Request(DATASET_URL, headers={"User-Agent": "trafficgen"})
    with urllib.request.urlopen(request, timeout=60) as response:
        archive = response.read()

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    target = TARGET_DIR / FILE_NAME
    with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
        target.write_bytes(zip_file.read(FILE_NAME))
    print(f"Saved {target}")


if __name__ == "__main__":
    main()

"""Shared ENSO index: monthly ONI (NOAA CPC) and El Niño / La Niña phase."""

from io import StringIO
from pathlib import Path

import httpx
import pandas as pd

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
SOURCE = "NOAA CPC ONI"
NINO_THRESHOLD = 0.5
NINA_THRESHOLD = -0.5

# Seasons are labelled by initials; each maps to its central month.
SEASON_CENTER_MONTH = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}  # fmt: skip

# backend/src/clima_nqn/io/enso.py -> repo root is parents[4]
DEFAULT_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "interim" / "enso" / "oni_monthly.parquet"
)


def fetch_oni(url: str = ONI_URL, timeout: float = 30.0) -> str:
    """Download the raw ONI ascii file."""
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.text


def parse_oni(text: str) -> pd.DataFrame:
    """Parse CPC ONI ascii (SEAS YR TOTAL ANOM) into monthly `date`, `oni`."""
    raw = pd.read_csv(StringIO(text), sep=r"\s+")
    month = raw["SEAS"].map(SEASON_CENTER_MONTH)
    if month.isna().any():
        raise ValueError(f"unknown season labels: {sorted(raw['SEAS'][month.isna()].unique())}")
    date = pd.to_datetime({"year": raw["YR"], "month": month, "day": 1})
    return pd.DataFrame({"date": date, "oni": raw["ANOM"].astype(float)})


def classify_phase(oni: pd.Series) -> pd.Series:
    """'nino' if oni >= 0.5, 'nina' if oni <= -0.5, else 'neutral'."""
    phase = pd.Series("neutral", index=oni.index, dtype=object)
    phase[oni >= NINO_THRESHOLD] = "nino"
    phase[oni <= NINA_THRESHOLD] = "nina"
    return phase


def build_enso(text: str) -> pd.DataFrame:
    df = parse_oni(text)
    df["phase"] = classify_phase(df["oni"])
    df.attrs.update({"source": SOURCE, "url": ONI_URL})
    return df


def write_enso(df: pd.DataFrame, path: Path | str = DEFAULT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)  # pandas stores df.attrs in the parquet metadata
    return path


def read_enso(path: Path | str = DEFAULT_PATH) -> pd.DataFrame:
    return pd.read_parquet(path)

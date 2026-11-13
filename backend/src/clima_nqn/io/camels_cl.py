"""CAMELS-CL daily basin series (Chile) for the streamflow LSTM pretraining (F2.5).

Usage (from ``backend/``)::

    uv run clima-nqn flow lstm-train --camels-dir /path/to/camels-cl/zip ...

Source: Alvarez-Garreton et al. (2018), HESS 22, 5817-5846, PANGAEA, DOI 10.1594/PANGAEA.894885,
CC-BY-4.0. The package ships one zip per variable, each with a tab-separated, quoted text file: the
first row is ``"gauge_id"`` followed by the gauge ids, then one row per date (``"YYYY-MM-DD"``) and
one column per gauge; a single space (``" "``) is a missing value. The attributes file is
transposed (rows are attributes, columns are gauges) and its ids and numbers are space-padded.

The loader reads the zips directly and writes a tidy long Parquet (``gauge_id``, ``date``,
``precip_mm``, ``tmin_c``, ``tmax_c``, ``tmean_c``, ``pet_mm``, ``q_mm``) plus a ``.static.json`` with
the basin attributes. Forcing is CR2MET (precipitation and temperature) with Hargreaves PET, which is
a different product from the ERA5 forcing used for Neuquén. Dates before ``FORCING_START`` (the start of
the Neuquén forcing) are dropped. Units are asserted on the data (:func:`check_units`).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_DIR = Path(__file__).resolve().parents[4] / "data" / "raw" / "camels-cl" / "zip"
DEFAULT_OUT = (
    Path(__file__).resolve().parents[4] / "data" / "raw" / "camels-cl" / "camels_cl.parquet"
)
FORCING_START = pd.Timestamp("1980-01-01")
STATIC_SUFFIX = ".static.json"
MIN_YEARS = 10

# variable -> (zip file name, text file inside the zip)
ZIP_FILES = {
    "attributes": ("1_CAMELScl_attributes.zip", "1_CAMELScl_attributes.txt"),
    "q_mm": ("3_CAMELScl_streamflow_mm.zip", "3_CAMELScl_streamflow_mm.txt"),
    "precip_mm": ("4_CAMELScl_precip_cr2met.zip", "4_CAMELScl_precip_cr2met.txt"),
    "tmin_c": ("8_CAMELScl_tmin_cr2met.zip", "8_CAMELScl_tmin_cr2met.txt"),
    "tmax_c": ("9_CAMELScl_tmax_cr2met.zip", "9_CAMELScl_tmax_cr2met.txt"),
    "tmean_c": ("10_CAMELScl_tmean_cr2met.zip", "10_CAMELScl_tmean_cr2met.txt"),
    "pet_mm": ("12_CAMELScl_pet_hargreaves.zip", "12_CAMELScl_pet_hargreaves.txt"),
}
VARIABLES = ["precip_mm", "tmin_c", "tmax_c", "tmean_c", "pet_mm", "q_mm"]
COLUMNS = ["gauge_id", "date", *VARIABLES]
FORCING_VARIABLES = VARIABLES[:-1]

# Plausible ranges (inclusive) per variable, in the units of the column name.
RANGES = {
    "precip_mm": (0.0, 2000.0),  # mm/d
    "tmin_c": (-60.0, 50.0),
    "tmax_c": (-60.0, 60.0),
    "tmean_c": (-60.0, 50.0),
    "pet_mm": (-1.0, 30.0),  # mm/d; Hargreaves gives small negatives, clipped to 0 on load
    "q_mm": (0.0, 1000.0),  # mm/d
}
MEAN_RANGES = {  # plausible basin-mean values: catches a wrong unit that stays inside RANGES
    "precip_mm": (0.0, 30.0),
    "tmean_c": (-25.0, 35.0),
    "pet_mm": (0.0, 12.0),
    "q_mm": (0.0, 50.0),
}

SOURCE = (
    "Alvarez-Garreton, C. et al. (2018), The CAMELS-CL dataset: catchment attributes and "
    "meteorology for large sample studies - Chile dataset, HESS 22, 5817-5846; PANGAEA, "
    "DOI 10.1594/PANGAEA.894885"
)
LICENSE = "CC-BY-4.0"
FORCING = "CR2MET (precipitation, Tmin, Tmax, Tmean); PET Hargreaves; streamflow in mm/d"
FORCING_NOTE = "forzante distinto del ERA5 usado en Neuquén"
UNITS = "precip_mm, pet_mm, q_mm: mm/day (negative Hargreaves PET clipped to 0); tmean_c, tmin_c, tmax_c: degC"

_ATTRIBUTE_ROWS = {
    "gauge_name": "name",
    "gauge_lat": "lat",
    "gauge_lon": "lon",
    "record_period_start": "record_start",
    "n_obs": "n_obs",
    "area": "area_km2",
    "elev_mean": "elev_mean_m",
}


def _open_text(path: Path | str):
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist() if n.endswith(".txt")]
    if len(names) != 1:
        raise ValueError(f"{path}: expected one .txt file, found {z.namelist()}")
    return z.open(names[0])


def read_wide(path: Path | str) -> pd.DataFrame:
    """One variable: a float table indexed by date with one column per gauge (ids stripped)."""
    with _open_text(path) as f:
        df = pd.read_csv(f, sep="\t", quotechar='"', index_col=0, na_values=[" "])
    df.columns = [str(c).strip() for c in df.columns]
    df.index = pd.to_datetime(df.index.astype(str).str.strip(), format="%Y-%m-%d")
    df.index.name = "date"
    bad = [c for c in df.columns if df[c].dtype == object]
    if bad:
        raise ValueError(f"{path}: non-numeric values in gauges {bad[:5]}")
    return df.astype(float)


def read_attributes(path: Path | str) -> pd.DataFrame:
    """Basin attributes (transposed in the file) indexed by gauge id."""
    with _open_text(path) as f:
        raw = pd.read_csv(f, sep="\t", quotechar='"', index_col=0, dtype=str)
    raw = raw.apply(lambda col: col.str.strip())
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = [r for r in _ATTRIBUTE_ROWS if r not in raw.index]
    if missing:
        raise ValueError(f"{path}: attribute rows missing: {missing}")
    # the header row "gauge_id" holds the ids; the first column header was consumed as the index
    ids = list(raw.columns)
    out = raw.loc[list(_ATTRIBUTE_ROWS)].T.rename(columns=_ATTRIBUTE_ROWS)
    out.index = pd.Index(ids, name="gauge_id")
    for col in ("lat", "lon", "area_km2", "elev_mean_m", "n_obs"):
        out[col] = pd.to_numeric(out[col], errors="raise")
    out["n_obs"] = out["n_obs"].astype(int)
    return out


def check_units(df: pd.DataFrame) -> None:
    """Fail loudly if a column is outside its plausible range (wrong unit or corrupt data)."""
    for col, (lo, hi) in RANGES.items():
        v = df[col].to_numpy(dtype=float)
        if not np.isfinite(v).any():
            continue
        vmin, vmax = np.nanmin(v), np.nanmax(v)
        if vmin < lo or vmax > hi:
            raise ValueError(
                f"{col}: values {vmin:.3g}..{vmax:.3g} outside the plausible {lo}..{hi}"
            )
    for col, (lo, hi) in MEAN_RANGES.items():
        m = float(np.nanmean(df[col].to_numpy(dtype=float)))
        if not lo <= m <= hi:
            raise ValueError(f"{col}: mean {m:.3g} outside the plausible {lo}..{hi}")


def build_camels(
    zip_dir: Path | str = DEFAULT_DIR, out_path: Path | str = DEFAULT_OUT
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the zips, write the tidy Parquet and the static JSON; returns ``(table, attributes)``."""
    zip_dir, out_path = Path(zip_dir), Path(out_path)
    for name, _ in ZIP_FILES.values():
        if not (zip_dir / name).is_file():
            raise FileNotFoundError(f"missing CAMELS-CL file {zip_dir / name}")
    attrs = read_attributes(zip_dir / ZIP_FILES["attributes"][0])
    wide = {v: read_wide(zip_dir / ZIP_FILES[v][0]) for v in VARIABLES}
    gauges = list(attrs.index)
    for v, w in wide.items():
        if set(w.columns) != set(gauges):
            raise ValueError(f"{v}: gauge ids differ from the attributes file")
    dates = sorted(set().union(*(w.index for w in wide.values())))
    dates = pd.DatetimeIndex([d for d in dates if d >= FORCING_START], name="date")
    n = len(dates)
    cols = {
        "gauge_id": np.repeat(np.array(gauges, dtype=object), n),
        "date": np.tile(dates.to_numpy(), len(gauges)),
    }
    for v in VARIABLES:
        cols[v] = wide[v].reindex(index=dates, columns=gauges).to_numpy(dtype=float).T.ravel()
    df = pd.DataFrame(cols)[COLUMNS]
    check_units(df)
    df["pet_mm"] = df["pet_mm"].clip(lower=0.0)  # Hargreaves can be slightly negative
    meta = {
        "title": "CAMELS-CL daily series (tidy)",
        "source": SOURCE,
        "license": LICENSE,
        "forcing": FORCING,
        "forcing_note": FORCING_NOTE,
        "units": UNITS,
        "period": f"{dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    table = table.replace_schema_metadata({k.encode(): v.encode() for k, v in meta.items()})
    pq.write_table(table, out_path)
    static = {**meta, "basins": json.loads(attrs.to_json(orient="index"))}
    out_path.with_suffix(STATIC_SUFFIX).write_text(json.dumps(static, indent=2, ensure_ascii=False))
    return df, attrs


def read_camels(path: Path | str = DEFAULT_OUT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The table and attributes written by :func:`build_camels`."""
    path = Path(path)
    df = pd.read_parquet(path)
    basins = json.loads(path.with_suffix(STATIC_SUFFIX).read_text())["basins"]
    attrs = pd.DataFrame.from_dict(basins, orient="index")
    attrs.index.name = "gauge_id"
    return df, attrs


def load_camels(zip_dir: Path | str = DEFAULT_DIR, cache: Path | str | None = None):
    """The cached table if present, else build it from the zips."""
    cache = Path(cache) if cache is not None else None
    if cache is not None and cache.is_file() and cache.with_suffix(STATIC_SUFFIX).is_file():
        return read_camels(cache)
    return build_camels(zip_dir, cache if cache is not None else DEFAULT_OUT)


def select_basins(df: pd.DataFrame, min_years: int = MIN_YEARS) -> list[str]:
    """Gauges with at least ``min_years`` x 365 days of valid flow and complete forcing."""
    ok = df[FORCING_VARIABLES].notna().all(axis=1) & df["q_mm"].notna()
    counts = ok.groupby(df["gauge_id"]).sum()
    return sorted(counts.index[counts >= min_years * 365].tolist())

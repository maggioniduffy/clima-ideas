"""Viewer layer ``ar-events`` (plan/01, F1.6): the AR catalog plus hourly IVT frames for replay.

Output in ``<out>/ar-events/``:

- ``manifest.json``  layer manifest (kind ``events``).
- ``events.parquet`` the catalog as is (schema metadata included).
- ``events.json``    the same rows for the viewer (no Parquet reader in the browser): ISO-8601 UTC
  strings, NaN as null.
- ``enso.json``      optional: the F1.8 ENSO-phase report numbers (``F1.8.json``) copied as is, listed in
  the manifest only when the report is given.
- ``enso-extremes.json`` optional: the F1.9 extreme-rain-days-by-ENSO numbers (``F1.9.json``) copied as is,
  listed in the manifest only when the report is given.
- ``frames/index.json`` grid, units and, per event, ``start``/``n_frames``/``vmin``/``vmax``.
- ``frames/<event_id>.bin`` hourly |IVT| over the regional grid for [start, end): little-endian
  Float32 ``[n_frames, ny, nx]``, row 0 = southernmost latitude, column 0 = westernmost longitude,
  NaN where ERA5 has no hour. Frame ``i`` is valid at ``start + i`` hours.
- ``frames/footprints.bin`` per event, the maximum |IVT| each cell reached during the event: little-endian
  Float32 ``[n_events, ny, nx]`` on the same grid (NaN where the cell has no hour at all). Events come in
  the order of ``footprints.events`` in ``frames/index.json`` (which also holds ``file`` and ``shape``);
  only events that have frames are included. Listed in the manifest so ``GET /layers/ar-events/data?file=``
  serves it.

- ``responses.json`` optional: river response per event and station (``clima-nqn ar response``, see
  ``stages.ar.response``); kept in the manifest when it already exists in the directory.

``GET /layers/ar-events/frames/<event_id>`` serves the ``.bin`` (see ``clima_nqn.api.app``).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.layers.manifest import LayerManifest
from clima_nqn.stages.ar import catalog

LAYER_ID = "ar-events"
TITLE = "Ríos atmosféricos"
SOURCE = "ERA5 (Copernicus) vía ARCO-ERA5 + TECA BARD"
LICENSE = "CC BY 4.0"
UNITS = "kg m-1 s-1"
DEFAULT_OUT = Path("data/processed")
FRAMES_DIR = "frames"
INDEX_NAME = f"{FRAMES_DIR}/index.json"
FOOTPRINTS_NAME = f"{FRAMES_DIR}/footprints.bin"
ENSO_NAME = "enso.json"
ENSO_EXTREMES_NAME = "enso-extremes.json"
RESPONSES_NAME = "responses.json"
DATETIME_COLUMNS = ("start", "end", "ivt_max_time")


def ivt_magnitude(ds: xr.Dataset) -> xr.DataArray:
    """|IVT| in kg m-1 s-1 from the eastward/northward water vapour flux components."""
    return np.hypot(ds["viwve"], ds["viwvn"]).transpose("time", "lat", "lon")


def event_frames(ivt: xr.DataArray, start, end) -> np.ndarray:
    """Hourly frames ``[n, ny, nx]`` float32 for [start, end); missing hours are NaN."""
    stamps = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="h", inclusive="left")
    frames = ivt.reindex(time=stamps).values.astype("<f4")
    return np.ascontiguousarray(frames)


def event_footprint(frames: np.ndarray) -> np.ndarray:
    """Per-cell maximum over the frames ``[n, ny, nx]`` -> ``[ny, nx]`` float32; NaN only where every hour is NaN."""
    return np.fmax.reduce(frames, axis=0).astype("<f4")


def _load_ivt(era5_by_year: dict[int, Path], years: list[int], lo, hi) -> xr.DataArray | None:
    parts = []
    for y in years:
        if y not in era5_by_year:
            continue
        ds = xr.open_zarr(era5_by_year[y], consolidated=False, chunks=None)
        sub = ds[["viwve", "viwvn"]].sel(time=slice(lo, hi)).load()
        ds.close()
        if sub.sizes["time"]:
            parts.append(ivt_magnitude(sub))
    return xr.concat(parts, dim="time") if parts else None


def _jsonable(value):
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def events_records(df: pd.DataFrame) -> list[dict]:
    """Catalog rows as JSON-ready dicts (timestamps as UTC ISO strings, NaN/NaT as None)."""
    rows = []
    for rec in df.to_dict(orient="records"):
        rows.append({k: _jsonable(rec[k]) for k in df.columns})
    return rows


def write_frames(events: pd.DataFrame, era5_paths: Sequence[Path], out_dir: Path) -> dict:
    """Write ``frames/<event_id>.bin`` per event and return the index dict."""
    frames_dir = out_dir / FRAMES_DIR
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    era5_by_year = {catalog._year_of(Path(p)): Path(p) for p in era5_paths}
    entries: dict[str, dict] = {}
    footprints: list[np.ndarray] = []
    grid: dict | None = None
    for year, group in events.groupby(events["start"].dt.year):
        last = group["end"].max().year
        ivt = _load_ivt(
            era5_by_year,
            list(range(int(year), last + 1)),
            group["start"].min(),
            group["end"].max() - pd.Timedelta(hours=1),
        )
        if ivt is None:
            continue
        if grid is None:
            lat, lon = ivt["lat"].values, ivt["lon"].values
            grid = {
                "ny": len(lat),
                "nx": len(lon),
                "lat_min": float(lat.min()),
                "lat_max": float(lat.max()),
                "lon_min": float(lon.min()),
                "lon_max": float(lon.max()),
                "origin": "south-west",
            }
        elif ivt.shape[1:] != (grid["ny"], grid["nx"]):
            raise ValueError("ERA5 grid differs between years")
        for ev in group.itertuples(index=False):
            frames = event_frames(ivt, ev.start, ev.end)
            if frames.shape[0] == 0 or np.isnan(frames).all():
                continue
            (frames_dir / f"{ev.event_id}.bin").write_bytes(frames.tobytes())
            footprints.append(event_footprint(frames))
            entries[ev.event_id] = {
                "start": pd.Timestamp(ev.start).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "n_frames": int(frames.shape[0]),
                "vmin": float(np.nanmin(frames)),
                "vmax": float(np.nanmax(frames)),
            }
    index = {
        "units": UNITS,
        "variable": "|IVT|",
        "dtype": "float32-le",
        "layout": "[n_frames, ny, nx], row 0 = south, column 0 = west",
        "step_hours": 1,
        "grid": grid,
        "events": entries,
    }
    if footprints:
        (out_dir / FOOTPRINTS_NAME).write_bytes(np.stack(footprints).astype("<f4").tobytes())
        index["footprints"] = {
            "file": FOOTPRINTS_NAME,
            "dtype": "float32-le",
            "layout": "[n_events, ny, nx], same grid as the frames; events in the order of `events`",
            "events": list(entries),
            "shape": [len(footprints), grid["ny"], grid["nx"]],
        }
    (out_dir / INDEX_NAME).write_text(json.dumps(index), encoding="utf-8")
    return index


def build_layer(
    events_path: Path,
    era5_dir: Path,
    out_root: Path = DEFAULT_OUT,
    enso_report: Path | None = None,
    extremes_report: Path | None = None,
) -> tuple[Path, dict]:
    """Publish ``<out_root>/ar-events/``; returns (layer dir, frames index).

    ``enso_report`` (F1.8 JSON from ``clima-nqn ar enso``), when given, is copied as ``enso.json``.
    ``extremes_report`` (F1.9 JSON from ``clima-nqn ar enso-extremes``) is copied as ``enso-extremes.json``.
    """
    events_path = Path(events_path)
    df = pd.read_parquet(events_path)
    meta = catalog.read_metadata(events_path)
    period = meta.get("period", "")
    stores = sorted(p for p in Path(era5_dir).glob("[0-9][0-9][0-9][0-9].zarr") if p.is_dir())
    out_dir = Path(out_root) / LAYER_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for col in DATETIME_COLUMNS:
        df[col] = pd.to_datetime(df[col])

    index = write_frames(df, stores, out_dir)
    shutil.copyfile(events_path, out_dir / "events.parquet")
    (out_dir / "events.json").write_text(json.dumps(events_records(df)), encoding="utf-8")
    files = ["events.json", "events.parquet", INDEX_NAME]
    if "footprints" in index:
        files.append(FOOTPRINTS_NAME)
    if enso_report is not None:
        shutil.copyfile(enso_report, out_dir / ENSO_NAME)
        files.append(ENSO_NAME)
    if extremes_report is not None:
        shutil.copyfile(extremes_report, out_dir / ENSO_EXTREMES_NAME)
        files.append(ENSO_EXTREMES_NAME)
    if (out_dir / RESPONSES_NAME).is_file():  # keep the file of an earlier `ar response`
        files.append(RESPONSES_NAME)
    manifest = LayerManifest(
        id=LAYER_ID,
        title=TITLE,
        kind="events",
        source=SOURCE,
        period=period,
        license=LICENSE,
        updated_at=datetime.now(UTC),
        files=files,
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return out_dir, index

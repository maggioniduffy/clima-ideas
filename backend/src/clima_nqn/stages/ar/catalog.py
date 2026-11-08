"""Atmospheric-river event catalog for the Neuquén cordillera (plan/01, F1.3).

BARD (TECA, 6-hourly ``ar_probability``) decides when an AR touches the cordillera polygon; hourly
regional ERA5 gives the event's IVT, 0 °C level and precipitation over the same polygon.

Conventions:
- A BARD step is an AR step when at least one polygon cell has ``ar_probability >= threshold``.
- An event is a run of AR steps (``max_gap_steps`` non-AR steps may sit inside). ``start`` is the first
  AR step, ``end`` is the last AR step + ``step_hours`` (exclusive), ``n_steps`` counts AR steps only.
- ERA5 statistics use the hourly stamps in [start, end), except ``tp``: it is an hourly accumulation
  that ends at its stamp, so precipitation sums the stamps in (start, end], which cover exactly [start, end).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr

from clima_nqn.stages.ar import geo

# aproximación de la cordillera neuquina, sin verificar: provincia de Neuquén (Natural Earth 1:10m) al oeste de
# 70° O, generada por ``python -m clima_nqn.stages.ar.geo`` (ver geo/README.md); refinar con DEM
CORDILLERA_POLYGON: list[tuple[float, float]] = geo.load_cordillera()  # (lon, lat)
# the rectangle used before F1.3 was refined; it reached into Chile (kept for comparison and tests)
LEGACY_RECTANGLE: list[tuple[float, float]] = [
    (-71.95, -36.0),
    (-70.0, -36.0),
    (-70.0, -41.1),
    (-71.95, -41.1),
]

DEFAULT_THRESHOLD = 0.67
SOURCE = "ERA5 via ARCO-ERA5 + TECA BARD 6.0.0"
LICENSE = "CC-BY 4.0"
DEFAULT_OUT = Path("data/interim/ar/events.parquet")

EVENT_COLUMNS = ["start", "end", "duration_h", "n_steps", "prob_max", "area_frac_max"]
STAT_COLUMNS = [
    "ivt_max", "ivt_max_time", "ivt_max_lat", "ivt_max_lon",
    "deg0l_max", "deg0l_mean", "tp_sum_mm",
]  # fmt: skip
COLUMNS = ["event_id", *EVENT_COLUMNS, *STAT_COLUMNS, "enso_phase"]


# --- polygon mask --------------------------------------------------------------------------


def _points_in_polygon(x: np.ndarray, y: np.ndarray, polygon: Sequence[tuple[float, float]]):
    """Even-odd ray casting for points (x, y); points exactly on an edge are not guaranteed."""
    inside = np.zeros(x.shape, dtype=bool)
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if y1 == y2:
            continue
        crosses = (y1 > y) != (y2 > y)
        x_at_y = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= crosses & (x < x_at_y)
    return inside


def polygon_mask(
    lat: np.ndarray,
    lon: np.ndarray,
    polygon: Sequence[tuple[float, float]]
    | Sequence[Sequence[tuple[float, float]]] = CORDILLERA_POLYGON,
) -> xr.DataArray:
    """Boolean (lat, lon) mask of the grid cells whose centers fall inside ``polygon`` (lon, lat).

    ``polygon`` is one ring of (lon, lat) vertices or, for a multipolygon, a sequence of such rings (union).
    """
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    lon2d, lat2d = np.meshgrid(lon, lat)
    rings = [polygon] if np.ndim(polygon[0]) == 1 else polygon
    values = np.zeros(lon2d.shape, dtype=bool)
    for ring in rings:
        values |= _points_in_polygon(lon2d, lat2d, ring)
    return xr.DataArray(values, dims=("lat", "lon"), coords={"lat": lat, "lon": lon}, name="mask")


def _check_mask(mask: xr.DataArray) -> np.ndarray:
    values = mask.transpose("lat", "lon").values.astype(bool)
    if not values.any():
        raise ValueError("no grid cell falls inside the polygon")
    return values


# --- BARD steps and events -----------------------------------------------------------------


def ar_steps(
    bard_ds: xr.Dataset, mask: xr.DataArray, threshold: float = DEFAULT_THRESHOLD
) -> pd.DataFrame:
    """Per BARD step: ``time``, ``prob_max`` in the polygon, ``area_frac`` >= threshold, ``is_ar``."""
    inside = _check_mask(mask)
    prob = bard_ds["ar_probability"].transpose("time", "lat", "lon").values[:, inside]
    hit = prob >= threshold  # NaN compares False
    prob_max = np.nanmax(np.where(np.isnan(prob), -np.inf, prob), axis=1)
    prob_max = np.where(np.isfinite(prob_max), prob_max, np.nan)
    area_frac = hit.sum(axis=1) / inside.sum()
    return pd.DataFrame(
        {
            "time": pd.DatetimeIndex(bard_ds["time"].values),
            "prob_max": prob_max.astype(float),
            "area_frac": area_frac.astype(float),
            "is_ar": hit.any(axis=1),
        }
    )


def group_events(steps: pd.DataFrame, step_hours: int = 6, max_gap_steps: int = 0) -> pd.DataFrame:
    """Merge AR steps into events; up to ``max_gap_steps`` non-AR steps between steps are bridged."""
    ar = steps[steps["is_ar"]].sort_values("time")
    rows = []
    group: list[int] = []

    def close() -> None:
        part = ar.loc[group]
        start, last = part["time"].iloc[0], part["time"].iloc[-1]
        end = last + pd.Timedelta(hours=step_hours)
        rows.append(
            {
                "start": start,
                "end": end,
                "duration_h": int((end - start) / pd.Timedelta(hours=1)),
                "n_steps": len(part),
                "prob_max": float(part["prob_max"].max()),
                "area_frac_max": float(part["area_frac"].max()),
            }
        )

    prev = None
    for idx, t in ar["time"].items():
        if prev is not None:
            gap = (t - prev) / pd.Timedelta(hours=step_hours) - 1
            if gap > max_gap_steps:
                close()
                group = []
        group.append(idx)
        prev = t
    if group:
        close()
    out = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    out["start"] = pd.to_datetime(out["start"])
    out["end"] = pd.to_datetime(out["end"])
    return out


def assign_event_ids(events: pd.DataFrame) -> pd.Series:
    """``AR-<year of start>-<NNN>``, numbered per year in start order."""
    years = events["start"].dt.year
    seq = events.sort_values("start").groupby(years).cumcount() + 1
    ids = [f"AR-{y}-{n:03d}" for y, n in zip(years[seq.index], seq, strict=True)]
    return pd.Series(ids, index=seq.index).reindex(events.index)


# --- ERA5 statistics -----------------------------------------------------------------------


def event_stats(events: pd.DataFrame, era5_ds: xr.Dataset, mask: xr.DataArray) -> pd.DataFrame:
    """Add IVT, 0 °C level and precipitation statistics over the polygon for each event window.

    ``era5_ds`` may span several years; events without ERA5 hours get NaN/NaT statistics.
    """
    inside = _check_mask(mask)
    lat = era5_ds["lat"].values
    lon = era5_ds["lon"].values
    times = pd.DatetimeIndex(era5_ds["time"].values)
    rows = []
    for ev in events.itertuples(index=False):
        sel = np.flatnonzero((times >= ev.start) & (times < ev.end))
        row = dict.fromkeys(STAT_COLUMNS, np.nan)
        row["ivt_max_time"] = pd.NaT
        if len(sel):
            sub = (
                era5_ds[["viwve", "viwvn", "tp", "deg0l"]]
                .isel(time=sel)
                .transpose("time", "lat", "lon")
            )
            ivt = np.hypot(sub["viwve"].values, sub["viwvn"].values)[:, inside]
            k = int(np.nanargmax(ivt))
            ti, ci = divmod(k, ivt.shape[1])
            cell_lat = np.broadcast_to(lat[:, None], inside.shape)[inside][ci]
            cell_lon = np.broadcast_to(lon[None, :], inside.shape)[inside][ci]
            deg0l = sub["deg0l"].values[:, inside]
            tp_sel = np.flatnonzero((times > ev.start) & (times <= ev.end))
            tp = era5_ds["tp"].isel(time=tp_sel).transpose("time", "lat", "lon").values[:, inside]
            row.update(
                ivt_max=float(ivt[ti, ci]),
                ivt_max_time=pd.Timestamp(times[sel[ti]]),
                ivt_max_lat=float(cell_lat),
                ivt_max_lon=float(cell_lon),
                deg0l_max=float(np.nanmax(deg0l)),
                deg0l_mean=float(np.nanmean(deg0l)),
                tp_sum_mm=float(np.nanmean(np.nansum(tp, axis=0)) * 1000.0),
            )
        rows.append(row)
    stats = pd.DataFrame(rows, columns=STAT_COLUMNS, index=events.index)
    stats["ivt_max_time"] = pd.to_datetime(stats["ivt_max_time"])
    return pd.concat([events, stats], axis=1)


# --- catalog -------------------------------------------------------------------------------


def _year_of(path: Path) -> int:
    return int(Path(path).name.split(".")[0])


def _era5_window(era5_by_year: dict[int, Path], years: list[int], lo, hi) -> xr.Dataset | None:
    """Open the stores of ``years`` and cut [lo, hi] from each before joining them."""
    parts = []
    for y in years:
        if y not in era5_by_year:
            continue
        ds = xr.open_zarr(era5_by_year[y], consolidated=False, chunks=None)
        parts.append(ds.sel(time=slice(lo, hi)).load())
        ds.close()
    parts = [p for p in parts if p.sizes["time"]]
    return xr.concat(parts, dim="time") if parts else None


def _empty_stats(events: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    for col in STAT_COLUMNS:
        out[col] = pd.NaT if col == "ivt_max_time" else np.nan
    out["ivt_max_time"] = pd.to_datetime(out["ivt_max_time"])
    return out


def build_catalog(
    bard_paths: Sequence[Path],
    era5_paths: Sequence[Path],
    threshold: float = DEFAULT_THRESHOLD,
    max_gap_steps: int = 0,
    step_hours: int = 6,
    enso: pd.DataFrame | None = None,
    polygon: Sequence[tuple[float, float]] = CORDILLERA_POLYGON,
) -> pd.DataFrame:
    """Detect events in the BARD files and attach ERA5 statistics (one ERA5 year pair in memory).

    ``enso`` is the ``clima_nqn.io.enso`` table (``date``, ``phase``); without it ``enso_phase`` is null.
    """
    if not bard_paths:
        raise ValueError("no BARD files")
    parts = []
    for path in sorted(Path(p) for p in bard_paths):
        with xr.open_dataset(path) as ds:
            mask = polygon_mask(ds["lat"].values, ds["lon"].values, polygon)
            parts.append(ar_steps(ds[["ar_probability"]].load(), mask, threshold))
    steps = pd.concat(parts, ignore_index=True).sort_values("time")
    steps = steps.drop_duplicates("time").reset_index(drop=True)
    events = group_events(steps, step_hours, max_gap_steps)

    era5_by_year = {_year_of(Path(p)): Path(p) for p in era5_paths}
    chunks = []
    for year, group in events.groupby(events["start"].dt.year):
        group = group.copy()
        last = group["end"].max().year  # tp at ``end`` may sit in the next year's store
        window = _era5_window(
            era5_by_year,
            list(range(int(year), last + 1)),
            group["start"].min(),
            group["end"].max(),
        )
        if window is None:
            chunks.append(_empty_stats(group))
            continue
        era5_mask = polygon_mask(window["lat"].values, window["lon"].values, polygon)
        chunks.append(event_stats(group, window, era5_mask))
    df = pd.concat(chunks) if chunks else _empty_stats(events)
    df = df.sort_values("start").reset_index(drop=True)
    df.insert(0, "event_id", assign_event_ids(df) if len(df) else pd.Series(dtype=object))

    if enso is not None and len(df):
        phase = enso.assign(month=enso["date"].dt.to_period("M")).set_index("month")["phase"]
        df["enso_phase"] = df["start"].dt.to_period("M").map(phase)
    else:
        df["enso_phase"] = pd.Series([None] * len(df), index=df.index, dtype=object)
    df = df[COLUMNS]
    df.attrs.update(
        period=f"{steps['time'].iloc[0]:%Y-%m-%d}/{steps['time'].iloc[-1]:%Y-%m-%d}",
        threshold=threshold,
        max_gap_steps=max_gap_steps,
        polygon=[list(v) for v in polygon],
    )
    return df


def write_catalog(
    df: pd.DataFrame,
    path: Path | str = DEFAULT_OUT,
    threshold: float | None = None,
    max_gap_steps: int | None = None,
) -> Path:
    """Write Parquet; source, license, period, threshold and polygon go in the schema metadata.

    Period, threshold and polygon default to ``df.attrs`` as set by :func:`build_catalog`.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    attrs = df.attrs
    threshold = attrs.get("threshold", DEFAULT_THRESHOLD) if threshold is None else threshold
    gap = attrs.get("max_gap_steps", 0) if max_gap_steps is None else max_gap_steps
    polygon = attrs.get("polygon") or [list(v) for v in CORDILLERA_POLYGON]
    table = pa.Table.from_pandas(df, preserve_index=False)
    meta = dict(table.schema.metadata or {})
    meta.update(
        {
            k.encode(): str(v).encode()
            for k, v in {
                "source": SOURCE,
                "license": LICENSE,
                "period": attrs.get("period", ""),
                "threshold": threshold,
                "max_gap_steps": gap,
                "polygon": json.dumps(polygon),
            }.items()
        }
    )
    pq.write_table(table.replace_schema_metadata(meta), path)
    return path


def read_metadata(path: Path | str) -> dict[str, str]:
    """Catalog metadata stored by :func:`write_catalog`."""
    raw = pq.read_schema(path).metadata or {}
    keys = ("source", "license", "period", "threshold", "max_gap_steps", "polygon")
    return {k: raw[k.encode()].decode() for k in keys if k.encode() in raw}

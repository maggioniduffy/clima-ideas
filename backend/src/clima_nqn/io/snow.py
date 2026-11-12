"""ERA5 snow water equivalent around the flood peaks, from the public ARCO-ERA5 Zarr (F2.3).

Usage (from ``backend/``)::

    uv run clima-nqn flow snow-fetch        # data/raw/era5/snow-floods.parquet

Source: ERA5 ``snow_depth`` (m of water equivalent, 0.25 degrees), Copernicus Climate Change Service,
CC-BY 4.0, via the ARCO-ERA5 Google Cloud public dataset (anonymous). It is ERA5, not ERA5-Land
(no CDS key). One snapshot per day at 00 UTC for every day in ``[peak - 8, peak + 1]`` of each flood,
cropped to the station's upstream box. The file is a long table (``station_id``, ``peak``, ``date``,
``lat``, ``lon``, ``swe_m``) with source, license, units and period in the Parquet schema metadata.
Windows already stored are skipped and the file is rewritten after every batch, so an interrupted
run keeps what was read and a rerun continues.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from clima_nqn.io import era5, flow

VARIABLE = "snow_depth"
UNITS = "m of water equivalent"
DEFAULT_OUT = flow.RAW_DIR.parent / "era5" / "snow-floods.parquet"
DAYS_BEFORE = 8  # window = [peak - 8, peak + 1]: covers w = 0..7 days of AR window plus the peak
DAYS_AFTER = 1
BATCH_WINDOWS = 20
NOTE = (
    "ERA5 at 0.25 degrees (via ARCO-ERA5), not ERA5-Land; cells are coarse for these basins. "
    "Upstream boxes are approximate rectangles, not delineated basins (sin verificar)."
)
# Upstream area of each station as a rectangle (lat south, lat north, lon west, lon east). They are
# approximate rectangles written from memory, NOT a delineated basin: sin verificar.
UPSTREAM_BOXES: dict[int, tuple[float, float, float, float]] = {
    12004: (-38.8, -36.2, -71.2, -70.0),  # Paso de Indios (Neuquén)
    12010: (-38.8, -37.6, -71.2, -70.2),  # Bajada del Agrio (Agrio)
    12012: (-37.3, -36.6, -70.6, -70.1),  # Los Maitenes (Curi Leuvú)
}
BOX_NOTE = "cuenca aproximada por un rectángulo, sin verificar"

Window = tuple[int, pd.Timestamp]


def window_days(peak: pd.Timestamp) -> pd.DatetimeIndex:
    """The days read for a flood: ``[peak - 8, peak + 1]``, at 00 UTC."""
    peak = pd.Timestamp(peak).normalize()
    return pd.date_range(
        peak - pd.Timedelta(days=DAYS_BEFORE), peak + pd.Timedelta(days=DAYS_AFTER), freq="D"
    )


def stored_windows(path: Path | str) -> set[Window]:
    """``(station_id, peak)`` pairs already in the file (empty if it does not exist)."""
    path = Path(path)
    if not path.exists():
        return set()
    df = pd.read_parquet(path, columns=["station_id", "peak"]).drop_duplicates()
    return {(int(s), pd.Timestamp(p)) for s, p in zip(df["station_id"], df["peak"], strict=True)}


def _crop(
    field: np.ndarray, lat: np.ndarray, lon180: np.ndarray, box: tuple[float, float, float, float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cells of a 2-D field (lat x lon) inside the box: flat ``lat``, ``lon``, ``value`` arrays."""
    south, north, west, east = box
    ilat = era5._axis_selection(lat, south, north)
    ilon = era5._axis_selection(lon180, west, east)
    values = field[np.ix_(ilat, ilon)]
    glat, glon = np.meshgrid(lat[ilat], lon180[ilon], indexing="ij")
    return glat.ravel(), glon.ravel(), values.ravel()


def _write(df: pd.DataFrame, path: Path, meta: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    existing = table.schema.metadata or {}
    table = table.replace_schema_metadata(
        {**existing, **{k.encode(): v.encode() for k, v in meta.items()}}
    )
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp)
    tmp.replace(path)


def _meta(df: pd.DataFrame, units: str) -> dict[str, str]:
    return {
        "title": "ERA5 snow water equivalent around flood peaks",
        "source": era5.SOURCE,
        "license": era5.LICENSE,
        "variable": f"{VARIABLE} (ARCO-ERA5 name)",
        "units": units,
        "grid": "0.25 degrees",
        "period": f"{df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}",
        "window": f"[peak - {DAYS_BEFORE}, peak + {DAYS_AFTER}] days at 00 UTC",
        "boxes": str({k: list(v) for k, v in UPSTREAM_BOXES.items()}),
        "note": NOTE,
    }


def fetch_snow(
    windows: Iterable[Window],
    out_path: Path | str = DEFAULT_OUT,
    boxes: dict[int, tuple[float, float, float, float]] = UPSTREAM_BOXES,
    opener: era5.Opener = era5.open_arco,
    retries: int = 3,
    retry_wait: float = 60,
    workers: int = 16,
    batch: int = BATCH_WINDOWS,
    progress=print,
) -> Path:
    """Read the snow window of every pending ``(station_id, peak)`` into ``out_path``.

    A unique day is read once per batch whatever the number of stations that need it (one ARCO chunk
    is the global field). Each read retries on its own. After every batch the file is rewritten
    atomically, so a failure leaves the finished batches stored.
    """
    out_path = Path(out_path)
    wanted = sorted(
        {(int(s), pd.Timestamp(p).normalize()) for s, p in windows}, key=lambda w: (w[1], w[0])
    )
    unknown = {s for s, _ in wanted} - set(boxes)
    if unknown:
        raise KeyError(f"no upstream box for station(s) {sorted(unknown)}")
    done = stored_windows(out_path)
    pending = [w for w in wanted if w not in done]
    skipped = len(wanted) - len(pending)
    progress(f"{len(wanted)} windows: {skipped} stored, {len(pending)} to read")
    if not pending:
        return out_path

    import zarr

    zarr.config.set({"async.concurrency": max(10, workers)})
    raw = era5._retry(opener, retries, retry_wait, "snow open")
    if VARIABLE not in raw:
        raise KeyError(f"{VARIABLE} not in the store")
    units = str(raw[VARIABLE].attrs.get("units", UNITS))
    lat = np.asarray(raw["latitude"].values)
    lon180 = ((np.asarray(raw["longitude"].values) + 180.0) % 360.0) - 180.0
    frames = [pd.read_parquet(out_path)] if out_path.exists() else []
    started = time.monotonic()

    for i in range(0, len(pending), batch):
        part = pending[i : i + batch]
        needs: dict[pd.Timestamp, set[int]] = {}
        for sid, peak in part:
            for day in window_days(peak):
                needs.setdefault(day, set()).add(sid)

        def read(day: pd.Timestamp):
            def load() -> np.ndarray:
                return np.asarray(raw[VARIABLE].sel(time=day).values, dtype="float32")

            return day, era5._retry(load, retries, retry_wait, f"{day:%Y-%m-%d} {VARIABLE}")

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            fields = dict(pool.map(read, sorted(needs)))
        rows = []
        for sid, peak in part:
            for day in window_days(peak):
                glat, glon, vals = _crop(fields[day], lat, lon180, boxes[sid])
                rows.append(
                    pd.DataFrame(
                        {
                            "station_id": np.int32(sid),
                            "peak": peak,
                            "date": day,
                            "lat": glat.astype("float32"),
                            "lon": glon.astype("float32"),
                            "swe_m": vals.astype("float32"),
                        }
                    )
                )
        frames.append(pd.concat(rows, ignore_index=True))
        full = pd.concat(frames, ignore_index=True)
        _write(full, out_path, _meta(full, units))
        frames = [full]
        progress(
            f"{min(i + batch, len(pending))}/{len(pending)} windows, {time.monotonic() - started:.0f}s"
        )
    return out_path


def read_snow(path: Path | str) -> pd.DataFrame:
    """The long table written by :func:`fetch_snow`."""
    return pd.read_parquet(path)


def read_metadata(path: Path | str) -> dict[str, str]:
    raw = pq.read_schema(path).metadata or {}
    keys = ("source", "license", "variable", "units", "grid", "period", "window", "note")
    return {k: raw[k.encode()].decode() for k in keys if k.encode() in raw}

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

import ast
import json
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from clima_nqn.io import era5, flow, forcing

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
BASIN_NOTE = (
    "ERA5 at 0.25 degrees (via ARCO-ERA5), not ERA5-Land; cells are coarse for these basins. "
    "Upstream basins are HydroBASINS level 12 polygons (Lehner & Grill 2013); column w = cos(lat) x "
    "fraction of the cell inside the basin."
)
GEOMETRY_BASINS = "hydrobasins"

Window = tuple[int, pd.Timestamp]
Box = tuple[float, float, float, float]


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


def _parse_boxes(text: str) -> dict[int, Box]:
    """Boxes stored in the file metadata (a dict literal; older files wrote it without quotes)."""
    raw = ast.literal_eval(text)
    return {int(k): tuple(float(x) for x in v) for k, v in raw.items()}


def stored_boxes(path: Path | str) -> dict[int, Box] | None:
    """Boxes recorded in the file, or ``None`` if it has none (they are unknown)."""
    raw = (pq.read_schema(path).metadata or {}).get(b"boxes")
    if raw is None:
        return None
    try:
        return _parse_boxes(raw.decode())
    except (ValueError, SyntaxError, TypeError, AttributeError):
        return None


def _check_boxes(
    path: Path, pending: Iterable[Window], boxes: dict[int, Box], stored: dict[int, Box] | None
) -> None:
    """Refuse to append to a file whose box for a station differs from the requested one (or is unknown)."""
    in_file = {s for s, _ in stored_windows(path)}
    for sid in sorted({s for s, _ in pending} & in_file):
        if stored is None or sid not in stored:
            raise ValueError(
                f"{path} has no stored box for station {sid} (unknown): it cannot be checked "
                "against the requested one. Write to a new output file (--out)."
            )
        if tuple(stored[sid]) != tuple(boxes[sid]):
            raise ValueError(
                f"station {sid}: the box in {path} {list(stored[sid])} differs from the requested "
                f"{list(boxes[sid])}. Write to a new output file (--out) instead of appending."
            )


def stored_basins(path: Path | str) -> dict[int, str] | None:
    """Basin digests recorded in the file (``{station_id: digest}``), or ``None`` if it has none."""
    raw = (pq.read_schema(path).metadata or {}).get(b"basins")
    if raw is None:
        return None
    try:
        return {int(k): str(v) for k, v in json.loads(raw.decode()).items()}
    except (ValueError, TypeError, AttributeError):
        return None


def _check_geometry(
    path: Path,
    pending: Iterable[Window],
    boxes: dict[int, Box],
    digests: dict[int, str],
    stored_b: dict[int, Box] | None,
    stored_d: dict[int, str] | None,
) -> None:
    """Refuse to append to a file whose geometry (box or basin digest) for a station differs or is unknown."""
    in_file = {s for s, _ in stored_windows(path)}
    for sid in sorted({s for s, _ in pending} & in_file):
        if sid in digests:
            if stored_d is None or sid not in stored_d:
                raise ValueError(
                    f"{path} has no stored basin for station {sid} (unknown or stored as a box): "
                    "it cannot be checked against the requested one. Write to a new output file (--out)."
                )
            if stored_d[sid] != digests[sid]:
                raise ValueError(
                    f"station {sid}: the basin in {path} (digest {stored_d[sid]}) differs from the "
                    f"requested one ({digests[sid]}). Write to a new output file (--out) instead of appending."
                )
        else:
            if stored_b is None or sid not in stored_b:
                raise ValueError(
                    f"{path} has no stored box for station {sid} (unknown or stored as a basin): "
                    "it cannot be checked against the requested one. Write to a new output file (--out)."
                )
            _check_boxes(path, [w for w in pending if w[0] == sid], boxes, stored_b)


def _meta(
    df: pd.DataFrame,
    units: str,
    boxes: dict[int, Box],
    digests: dict[int, str] | None = None,
) -> dict[str, str]:
    meta = {
        "title": "ERA5 snow water equivalent around flood peaks",
        "source": era5.SOURCE,
        "license": era5.LICENSE,
        "variable": f"{VARIABLE} (ARCO-ERA5 name)",
        "units": units,
        "grid": "0.25 degrees",
        "period": f"{df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}",
        "window": f"[peak - {DAYS_BEFORE}, peak + {DAYS_AFTER}] days at 00 UTC",
        "boxes": json.dumps({str(k): list(v) for k, v in sorted(boxes.items())}),
        "note": NOTE,
    }
    if digests:
        meta["basins"] = json.dumps({str(k): v for k, v in sorted(digests.items())})
        meta["geometry"] = GEOMETRY_BASINS if not boxes else f"mixed ({GEOMETRY_BASINS} + boxes)"
        meta["note"] = BASIN_NOTE if not boxes else f"{NOTE} {BASIN_NOTE}"
        if not boxes:
            del meta["boxes"]
    return meta


def fetch_snow(
    windows: Iterable[Window],
    out_path: Path | str = DEFAULT_OUT,
    boxes: dict[int, tuple[float, float, float, float]] = UPSTREAM_BOXES,
    basins: dict[int, object] | None = None,
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

    With ``basins`` (``{station_id: shapely geometry}``) the stations listed there are read over the
    polygon instead of the box: the cells with a positive :func:`forcing.cell_weights` weight are kept
    and the extra column ``w`` (float32) holds that weight. Stations not in ``basins`` use ``boxes``.
    """
    out_path = Path(out_path)
    wanted = sorted(
        {(int(s), pd.Timestamp(p).normalize()) for s, p in windows}, key=lambda w: (w[1], w[0])
    )
    basins = basins or {}
    unknown = {s for s, _ in wanted} - set(boxes) - set(basins)
    if unknown:
        raise KeyError(f"no upstream box for station(s) {sorted(unknown)}")
    digests = {int(s): forcing.basin_digest(g) for s, g in basins.items()}
    done = stored_windows(out_path)
    pending = [w for w in wanted if w not in done]
    stored = stored_boxes(out_path) if out_path.exists() else None
    stored_d = stored_basins(out_path) if out_path.exists() else None
    if pending and out_path.exists():
        if basins or stored_d:
            _check_geometry(out_path, pending, boxes, digests, stored, stored_d)
        else:
            _check_boxes(out_path, pending, boxes, stored)
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
    grids: dict[int, tuple] = {}  # station -> (index, lat, lon, w) of the cells with weight > 0
    for sid in sorted({s for s, _ in pending} & set(basins)):
        ilat, ilon, wgt = forcing.cell_weights(lat, lon180, basins[sid])
        glat, glon = np.meshgrid(lat[ilat], lon180[ilon], indexing="ij")
        keep = wgt > 0
        grids[sid] = (
            np.ix_(ilat, ilon),
            keep,
            glat[keep].astype("float32"),
            glon[keep].astype("float32"),
            wgt[keep].astype("float32"),
        )

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
                if sid in grids:
                    ix, keep, glat, glon, wgt = grids[sid]
                    cols = {
                        "lat": glat,
                        "lon": glon,
                        "swe_m": fields[day][ix][keep].astype("float32"),
                        "w": wgt,
                    }
                else:
                    glat, glon, vals = _crop(fields[day], lat, lon180, boxes[sid])
                    cols = {
                        "lat": glat.astype("float32"),
                        "lon": glon.astype("float32"),
                        "swe_m": vals.astype("float32"),
                    }
                rows.append(
                    pd.DataFrame({"station_id": np.int32(sid), "peak": peak, "date": day, **cols})
                )
        frames.append(pd.concat(rows, ignore_index=True))
        full = pd.concat(frames, ignore_index=True)
        used = {**(stored or {}), **{s: boxes[s] for s, _ in wanted if s not in basins}}
        used_d = {**(stored_d or {}), **{s: digests[s] for s, _ in wanted if s in basins}}
        in_file = {int(s) for s in full["station_id"].unique()}
        _write(
            full,
            out_path,
            _meta(
                full,
                units,
                {s: b for s, b in used.items() if s in in_file and s not in used_d},
                {s: d for s, d in used_d.items() if s in in_file},
            ),
        )
        frames = [full]
        progress(
            f"{min(i + batch, len(pending))}/{len(pending)} windows, {time.monotonic() - started:.0f}s"
        )
    return out_path


def read_snow(path: Path | str) -> pd.DataFrame:
    """The long table written by :func:`fetch_snow`."""
    return pd.read_parquet(path)


def read_metadata(path: Path | str) -> dict:
    """Schema metadata as strings, plus ``boxes`` (``{station_id: box}``) when the file records them."""
    raw = pq.read_schema(path).metadata or {}
    keys = ("source", "license", "variable", "units", "grid", "period", "window", "note")
    meta: dict = {k: raw[k.encode()].decode() for k in keys if k.encode() in raw}
    boxes = stored_boxes(path)
    if boxes is not None:
        meta["boxes"] = boxes
    digests = stored_basins(path)
    if digests is not None:
        meta["basins"] = digests
    if b"geometry" in raw:
        meta["geometry"] = raw[b"geometry"].decode()
    return meta

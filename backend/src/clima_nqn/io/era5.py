"""Regional ERA5 for Neuquén read from the public ARCO-ERA5 Zarr (anonymous, no CDS account).

Usage (from ``backend/``)::

    uv run clima-nqn era5 fetch --year 2023                    # data/raw/era5/neuquen/2023.zarr
    uv run clima-nqn era5 fetch --year 2023 --months 1 --hours 0,12   # tiny smoke run
    uv run clima-nqn era5 combine                              # data/raw/era5/neuquen.zarr

Source: ERA5, Copernicus Climate Change Service, CC-BY 4.0, via the ARCO-ERA5 Google Cloud public
dataset. Variables (ARCO name -> short name): ``viwve``/``viwvn`` (vertical integral of eastward /
northward water vapour flux, kg m-1 s-1), ``tp`` (total precipitation, m, hourly accumulation that
ends at the valid time, so the daily total of day D is hours D 01:00 .. D+1 00:00) and ``deg0l``
(zero-degree level, m). Output grid: ascending latitude, longitudes in -180..180, float32.

ARCO chunks are one global hour per variable (~1.9 MB), so every requested hour downloads the
global field whatever the area; days are therefore fetched on a thread pool. A year is written to
``<year>.zarr.tmp`` and renamed once complete; a year whose store is complete is skipped, an
incomplete one is rebuilt. ERA5T (preliminary data) starts after the store's ``valid_time_stop``
attribute (2026-06-30 at the time of writing) and is flagged with the ``era5t`` attribute.
"""

from __future__ import annotations

import shutil
import time
from calendar import monthrange
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ARCO_STORE = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
# North, West, South, East: the province plus margin.
NEUQUEN_BOX = (-34.0, -74.0, -43.0, -66.0)
VARIABLES = {
    "vertical_integral_of_eastward_water_vapour_flux": "viwve",
    "vertical_integral_of_northward_water_vapour_flux": "viwvn",
    "total_precipitation": "tp",
    "zero_degree_level": "deg0l",
}
DEFAULT_OUT = Path("data/raw/era5/neuquen")
COMBINED = Path("data/raw/era5/neuquen.zarr")
SOURCE = "ERA5 (Copernicus Climate Change Service) via ARCO-ERA5 (Google Cloud public dataset)"
LICENSE = "CC-BY 4.0"
FINAL_ERA5_STOP = "2026-06-30"  # fallback when the store lacks valid_time_stop
TP_NOTE = (
    "Hourly accumulation ending at the valid time; the daily total for day D is the sum of "
    "hours D 01:00 .. D+1 00:00."
)
TIME_ENCODING = {"units": "hours since 1900-01-01 00:00:00", "dtype": "int64"}
DEFAULT_WORKERS = 64  # concurrent hour-chunk reads; ~5x the throughput of 8 in measurements
YEAR_TIME_CHUNK = 720
COMBINED_CHUNKS = (8760, 10, 10)  # long time axis, small tiles: cheap point time series

Opener = Callable[[], xr.Dataset]


def open_arco() -> xr.Dataset:
    """Lazily open the ARCO-ERA5 store (anonymous, consolidated metadata, no dask)."""
    return xr.open_zarr(
        ARCO_STORE, consolidated=True, chunks=None, storage_options={"token": "anon"}
    )


# --- pure helpers ---------------------------------------------------------------------------


def _axis_selection(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Indices of ``values`` inside [lo, hi], ordered by ascending value."""
    idx = np.flatnonzero((values >= lo) & (values <= hi))
    return idx[np.argsort(values[idx], kind="stable")]


def crop_to_area(ds: xr.Dataset, area: tuple[float, float, float, float]) -> xr.Dataset:
    """Crop a raw ARCO-like dataset to ``area`` = (N, W, S, E) in degrees.

    Input has longitudes 0..360 and descending latitudes with long variable names; the result has
    ascending latitudes, longitudes in -180..180 (ascending) and the short names of ``VARIABLES``.
    Selection uses integer indices only, so a lazy store reads just the needed cells (not that
    it helps with global-hour chunks) and nothing is loaded here.
    """
    north, west, south, east = area
    ds = ds[[name for name in VARIABLES if name in ds.data_vars]]
    lat = ds["latitude"].values
    lon180 = ((ds["longitude"].values + 180.0) % 360.0) - 180.0
    ilat = _axis_selection(lat, south, north)
    ilon = _axis_selection(lon180, west, east)
    out = ds.isel(latitude=ilat, longitude=ilon)
    out = out.assign_coords(latitude=lat[ilat], longitude=lon180[ilon])
    out = out.rename(
        {**{k: v for k, v in VARIABLES.items() if k in out}, "latitude": "lat", "longitude": "lon"}
    )
    return out


def expected_times(
    year: int,
    months: Iterable[int] = range(1, 13),
    hours: Iterable[int] = range(24),
    days: Iterable[int] | None = None,
) -> pd.DatetimeIndex:
    """Hourly timestamps a complete store holds, in order. ``days`` restricts days of month."""
    stamps = []
    for month in sorted(set(months)):
        ndays = monthrange(year, month)[1]
        for day in sorted(set(days)) if days is not None else range(1, ndays + 1):
            if day > ndays:
                continue
            for hour in sorted(set(hours)):
                stamps.append(pd.Timestamp(year, month, day, hour))
    return pd.DatetimeIndex(stamps)


def _parse_ranges(text: str, lo: int, hi: int, label: str) -> list[int]:
    values: set[int] = set()
    try:
        for part in text.split(","):
            part = part.strip()
            if part:
                a, _, b = part.partition("-")
                values.update(range(int(a), int(b or a) + 1))
    except ValueError:
        raise ValueError(f"invalid {label}: {text!r}") from None
    if not values or min(values) < lo or max(values) > hi:
        raise ValueError(f"invalid {label}: {text!r} (allowed {lo}-{hi})")
    return sorted(values)


def parse_months(text: str) -> list[int]:
    """Parse "1-12", "3" or "1,2,5-7" into sorted months."""
    return _parse_ranges(text, 1, 12, "months")


def parse_hours(text: str) -> list[int]:
    """Parse "0-23", "0,12" or "0,6-18" into sorted UTC hours."""
    return _parse_ranges(text, 0, 23, "hours")


def parse_area(text: str) -> tuple[float, float, float, float]:
    """Parse "N,W,S,E" (degrees, W/E in -180..180)."""
    try:
        north, west, south, east = (float(x) for x in text.split(","))
    except ValueError:
        raise ValueError(f"expected N,W,S,E (4 numbers), got {text!r}") from None
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError(f"need -90 <= S < N <= 90 and -180 <= W < E <= 180, got {text!r}")
    return north, west, south, east


def parse_years(text: str) -> list[int]:
    """Parse "2023", "1980-1985,1990" into sorted years."""
    return _parse_ranges(text, 1940, 2100, "years")


def is_complete(
    path: Path,
    year: int,
    months: Iterable[int] = range(1, 13),
    hours: Iterable[int] = range(24),
    days: Iterable[int] | None = None,
) -> bool:
    """True if ``path`` holds exactly the expected steps and all variables, with no gaps."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        ds = xr.open_zarr(path, consolidated=False, chunks=None)
        want = expected_times(year, months, hours, days)
        have = pd.DatetimeIndex(ds["time"].values)
        if not have.equals(want) or not set(VARIABLES.values()) <= set(ds.data_vars):
            return False
        # a rename only happens after a full write, but a cheap data check catches truncation
        return all(not bool(ds[v].isel(time=-1).isnull().all()) for v in VARIABLES.values())
    except Exception:  # noqa: BLE001 - any unreadable store counts as incomplete
        return False


# --- fetching -------------------------------------------------------------------------------


def _retry(fn: Callable, retries: int, retry_wait: float, label: str):
    """Call ``fn``; on error wait ``retry_wait * attempt`` seconds (linear backoff) and retry."""
    attempt = 1
    while True:
        try:
            return fn()
        except Exception as exc:
            print(f"{label} attempt {attempt} failed: {exc}", flush=True)
            if attempt >= retries:
                raise
            time.sleep(retry_wait * attempt)
            attempt += 1


def fetch_month(
    year: int,
    month: int,
    hours: Iterable[int],
    area: tuple[float, float, float, float],
    opener: Opener = open_arco,
    retries: int = 3,
    retry_wait: float = 60,
    workers: int = DEFAULT_WORKERS,
    days: Iterable[int] | None = None,
    stats: dict | None = None,
) -> xr.Dataset:
    """Read one month at ``hours`` UTC over ``area``; chunks are read concurrently.

    Every (hour, variable) chunk is one task on a pool of ``workers`` threads and retries on its
    own, so a transient error does not redo the month.
    ``stats["bytes"]`` accumulates the decompressed global fields that were read.
    """
    import zarr

    zarr.config.set({"async.concurrency": max(10, workers)})
    label = f"{year}-{month:02d}"
    raw = _retry(opener, retries, retry_wait, f"{label} open")
    stop = raw.attrs.get("valid_time_stop", FINAL_ERA5_STOP)
    steps = expected_times(year, [month], hours, days)

    names = list(VARIABLES)

    def one_chunk(task: tuple[int, str]) -> xr.Dataset:
        i, name = task

        def load() -> xr.Dataset:
            lazy = raw[[name]].sel(time=[steps[i]])
            if stats is not None:
                stats["bytes"] = stats.get("bytes", 0) + lazy[name].nbytes
            return crop_to_area(lazy, area).load()

        return _retry(load, retries, retry_wait, f"{steps[i]:%Y-%m-%d %H:00} {name}")

    tasks = [(i, name) for i in range(len(steps)) for name in names]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one_chunk, tasks))
    per_var = {}
    for (_, name), part in zip(tasks, results, strict=True):
        per_var.setdefault(VARIABLES[name], []).append(part)
    out = xr.merge([xr.concat(parts, dim="time") for parts in per_var.values()])
    out.attrs = {"valid_time_stop": stop}
    return out


def _encoding(ds: xr.Dataset, chunks: tuple[int, int, int]) -> dict:
    enc: dict = {"time": dict(TIME_ENCODING)}
    for name in ds.data_vars:
        shape = (ds.sizes["time"], ds.sizes["lat"], ds.sizes["lon"])
        enc[name] = {"dtype": "float32", "chunks": tuple(min(c, s) for c, s in zip(chunks, shape))}
    return enc


def _global_attrs(first: pd.Timestamp, last: pd.Timestamp, area, era5t: bool) -> dict:
    north, west, south, east = area
    return {
        "title": "ERA5 regional subset for Neuquén",
        "source": SOURCE,
        "license": LICENSE,
        "period": f"{first:%Y-%m-%d} to {last:%Y-%m-%d}",
        "area": f"N={north:g} W={west:g} S={south:g} E={east:g}",
        "era5t": bool(era5t),
    }


def _swap_into_place(tmp: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)


def fetch_year(
    year: int,
    months: Iterable[int] = range(1, 13),
    hours: Iterable[int] = range(24),
    area: tuple[float, float, float, float] = NEUQUEN_BOX,
    out_dir: Path = DEFAULT_OUT,
    opener: Opener = open_arco,
    retries: int = 3,
    retry_wait: float = 60,
    workers: int = DEFAULT_WORKERS,
    days: Iterable[int] | None = None,
) -> Path:
    """Fetch one year month by month into ``<out_dir>/<year>.zarr`` (atomic, idempotent)."""
    months, hours = sorted(set(months)), sorted(set(hours))
    days = None if days is None else sorted(set(days))
    out_dir = Path(out_dir)
    target = out_dir / f"{year}.zarr"
    if is_complete(target, year, months, hours, days):
        print(f"skip {target} (complete)", flush=True)
        return target
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"{year}.zarr.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)

    stats: dict = {}
    started = time.monotonic()
    parts, stop = [], FINAL_ERA5_STOP
    for month in months:
        t0 = time.monotonic()
        before = stats.get("bytes", 0)
        ds = fetch_month(
            year, month, hours, area, opener, retries, retry_wait, workers, days, stats
        )
        stop = ds.attrs.pop("valid_time_stop", stop)
        parts.append(ds)
        mb = (stats.get("bytes", 0) - before) / 1e6
        dt = max(time.monotonic() - t0, 1e-9)
        print(f"{year}-{month:02d}: {ds.sizes['time']} steps, {mb / dt:.1f} MB/s", flush=True)

    ds = xr.concat(parts, dim="time").astype("float32")
    ds.attrs = _global_attrs(
        pd.Timestamp(ds["time"].values[0]),
        pd.Timestamp(ds["time"].values[-1]),
        area,
        era5t=pd.Timestamp(ds["time"].values[-1]) > pd.Timestamp(stop),
    )
    for name, short in ((n, s) for n, s in VARIABLES.items() if s in ds.data_vars):
        ds[short].attrs.setdefault("arco_name", name)
    if "tp" in ds:
        ds["tp"].attrs["note"] = TP_NOTE
    ds.to_zarr(
        tmp, mode="w", consolidated=False, encoding=_encoding(ds, (YEAR_TIME_CHUNK, 10**6, 10**6))
    )
    _swap_into_place(tmp, target)
    total = max(time.monotonic() - started, 1e-9)
    print(
        f"wrote {target}: {ds.sizes['time']} steps in {total:.0f}s, "
        f"{stats.get('bytes', 0) / 1e6 / total:.1f} MB/s of decompressed global fields",
        flush=True,
    )
    return target


def combine(in_dir: Path = DEFAULT_OUT, out: Path = COMBINED) -> Path:
    """Concatenate every ``<year>.zarr`` in ``in_dir`` into one store (rewritten each time).

    Years are appended one at a time, so memory stays at one year.
    """
    in_dir, out = Path(in_dir), Path(out)
    years = sorted(p for p in in_dir.glob("[0-9][0-9][0-9][0-9].zarr") if p.is_dir())
    if not years:
        raise FileNotFoundError(f"no <year>.zarr stores in {in_dir}")
    opened = [xr.open_zarr(p, consolidated=False, chunks=None) for p in years]
    first, last = opened[0]["time"].values[0], opened[-1]["time"].values[-1]
    grid = [(d["lat"].values, d["lon"].values) for d in opened]
    if any(
        not (np.array_equal(g[0], grid[0][0]) and np.array_equal(g[1], grid[0][1])) for g in grid
    ):
        raise ValueError("per-year stores have different grids")
    attrs = dict(opened[0].attrs)
    attrs.update(
        _global_attrs(
            pd.Timestamp(first),
            pd.Timestamp(last),
            _parse_area_attr(opened[0].attrs.get("area")),
            era5t=any(bool(d.attrs.get("era5t")) for d in opened),
        )
    )
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    for i, ds in enumerate(opened):
        ds = ds.load()
        if i == 0:
            ds.attrs = attrs
            ds.to_zarr(tmp, mode="w", consolidated=False, encoding=_encoding(ds, COMBINED_CHUNKS))
        else:
            ds.attrs = attrs
            ds.to_zarr(tmp, mode="a", append_dim="time", consolidated=False)
    for d in opened:
        d.close()
    _swap_into_place(tmp, out)
    print(f"wrote {out}: {len(years)} years, {first} .. {last}", flush=True)
    return out


def _parse_area_attr(text: str | None) -> tuple[float, float, float, float]:
    if not text:
        return NEUQUEN_BOX
    parts = dict(item.split("=") for item in text.split())
    return float(parts["N"]), float(parts["W"]), float(parts["S"]), float(parts["E"])

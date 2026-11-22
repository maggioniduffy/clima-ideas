"""ERA5 daily precipitation for the hindcast valid dates (F5.2, F5.3).

Day D = ERA5 hourly ``tp`` ending D 01:00 .. D+1 00:00 UTC (24 steps), the same window as lead L
hours (24(L-1), 24L] of the 00 UTC run, cropped to the F5.1 box (or the F5.3 wide box), in mm.
Optionally also ``convective_precipitation`` (``cp_mm``), same window and units.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.io import era5
from clima_nqn.stages.hindcast import forecasts as fc

TP_NAME = "total_precipitation"
CP_NAME = "convective_precipitation"
# short variable code -> (ARCO name, output variable)
OBS_VARIABLES = {"tp": (TP_NAME, "precip_mm"), "cp": (CP_NAME, "cp_mm")}
WINDOW_NOTE = (
    "day D = ERA5 hourly tp ending D 01:00..D+1 00:00 UTC, same window as lead L hours "
    "(24(L-1), 24L] of the 00 UTC run"
)
LOG_EVERY_DAYS = 25


def eligible_dates(cases: pd.DataFrame) -> list[pd.Timestamp]:
    """Sorted unique valid dates inside the period of at least one model of ``fc.MODELS``."""
    days: set[pd.Timestamp] = set()
    for spec in fc.MODELS.values():
        days.update(pd.Timestamp(d) for d in fc.eligible_cases(cases, spec)["valid_date"])
    return sorted(days)


def observed_days(
    dates: Iterable,
    opener: era5.Opener = era5.open_arco,
    workers: int = era5.DEFAULT_WORKERS,
    retries: int = 3,
    retry_wait: float = 60,
    log_fn: Callable[[str], None] = lambda m: None,
    grid: fc.Grid = fc.F51_GRID,
    variables: Iterable[str] = ("tp",),
) -> xr.Dataset:
    """``precip_mm`` (date, lat, lon) float32: ERA5 daily total over ``grid`` for each date.

    ``variables`` may add ``cp`` (convective precipitation) -> ``cp_mm``, same window and units.
    """
    import zarr

    zarr.config.set({"async.concurrency": max(10, workers)})
    days = sorted({pd.Timestamp(d).normalize() for d in dates})
    if not days:
        raise ValueError("no dates")
    raw = era5._retry(opener, retries, retry_wait, "era5 open")
    stop = pd.Timestamp(raw.attrs.get("valid_time_stop", era5.FINAL_ERA5_STOP))
    codes = list(dict.fromkeys(variables))
    unknown = [c for c in codes if c not in OBS_VARIABLES]
    if unknown or not codes:
        raise ValueError(f"variables must be among {sorted(OBS_VARIABLES)}, got {codes}")
    names = {OBS_VARIABLES[c][0]: c for c in codes}
    lazy = raw[list(names)]
    lat_t, lon_t = grid.lat, grid.lon

    def one_hour(stamp: pd.Timestamp) -> dict[str, np.ndarray]:
        def load() -> dict[str, np.ndarray]:
            part = era5.crop_to_area(lazy.sel(time=[stamp]), grid.area, names).load()
            lat, lon = part["lat"].values, part["lon"].values
            same = lat.shape == lat_t.shape and lon.shape == lon_t.shape
            assert same and np.allclose(lat, lat_t) and np.allclose(lon, lon_t), (
                f"ERA5 grid != {grid.name} grid"
            )
            return {c: part[c].values[0].astype("float64") for c in codes}

        return era5._retry(load, retries, retry_wait, f"{stamp:%Y-%m-%d %H:00} {'+'.join(codes)}")

    out = {c: np.empty((len(days), *grid.shape), dtype=np.float32) for c in codes}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for start in range(0, len(days), LOG_EVERY_DAYS):
            chunk = days[start : start + LOG_EVERY_DAYS]
            stamps = [d + pd.Timedelta(hours=h) for d in chunk for h in range(1, 25)]
            fields = list(pool.map(one_hour, stamps))
            for c in codes:
                for i in range(len(chunk)):
                    hours = [f[c] for f in fields[24 * i : 24 * (i + 1)]]
                    out[c][start + i] = (np.sum(hours, axis=0) * 1000.0).astype("float32")
            log_fn(f"era5 observed {start + len(chunk)}/{len(days)} days")
    era5t = bool(days[-1] + pd.Timedelta(days=1) > stop)
    return xr.Dataset(
        {OBS_VARIABLES[c][1]: (("date", "lat", "lon"), out[c], {"units": "mm"}) for c in codes},
        coords={
            "date": np.array(days, dtype="datetime64[ns]"),
            "lat": lat_t,
            "lon": lon_t,
        },
        attrs={
            "source": era5.SOURCE,
            "license": era5.LICENSE,
            "window": WINDOW_NOTE,
            "valid_time_stop": str(stop.date()),
            "era5t": era5t,
            "grid": grid.description,
            "grid_name": grid.name,
            "area": list(grid.area),
            "variables": ",".join(OBS_VARIABLES[c][0] for c in codes),
        },
    )


def write_obs(ds: xr.Dataset, path: Path) -> None:
    """Atomic replace of the zarr directory ``path``."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(tmp, mode="w", consolidated=False)
    if path.exists():
        shutil.rmtree(path)
    tmp.rename(path)


def read_obs(path: Path) -> xr.Dataset:
    with xr.open_zarr(path, chunks=None, consolidated=False) as ds:
        return ds.load()

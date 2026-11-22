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
IVT_CODE = "ivt"  # F5.10: |Q| from viwve / viwvn at D 06, 12, 18 and D+1 00 UTC -> ``ivt``
IVT_NAMES = {
    "vertical_integral_of_eastward_water_vapour_flux": "viwve",
    "vertical_integral_of_northward_water_vapour_flux": "viwvn",
}
IVT_HOURS = (6, 12, 18, 24)
VALID_CODES = (*OBS_VARIABLES, IVT_CODE)
IVT_NOTE = (
    "ivt = mean of |Q| (ERA5 viwve, viwvn, full column) at D 06:00, 12:00, 18:00 and D+1 00:00 UTC, "
    "the same four hours as the forecast steps 24(L-1)+6..24L"
)
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

    ``variables`` may add ``cp`` (convective precipitation) -> ``cp_mm``, same window and units, and
    ``ivt`` -> ``ivt`` (kg m-1 s-1): mean of |Q| at D 06, 12, 18 and D+1 00 UTC (F5.10).
    """
    import zarr

    zarr.config.set({"async.concurrency": max(10, workers)})
    days = sorted({pd.Timestamp(d).normalize() for d in dates})
    if not days:
        raise ValueError("no dates")
    raw = era5._retry(opener, retries, retry_wait, "era5 open")
    stop = pd.Timestamp(raw.attrs.get("valid_time_stop", era5.FINAL_ERA5_STOP))
    codes = list(dict.fromkeys(variables))
    unknown = [c for c in codes if c not in VALID_CODES]
    if unknown or not codes:
        raise ValueError(f"variables must be among {sorted(VALID_CODES)}, got {codes}")
    pcodes = [c for c in codes if c in OBS_VARIABLES]
    want_ivt = IVT_CODE in codes
    names = {OBS_VARIABLES[c][0]: c for c in pcodes}
    lazy = raw[[*names, *(IVT_NAMES if want_ivt else ())]]
    lat_t, lon_t = grid.lat, grid.lon

    def hour_fields(stamp: pd.Timestamp, mapping: dict[str, str]) -> dict[str, np.ndarray]:
        def load() -> dict[str, np.ndarray]:
            part = era5.crop_to_area(lazy[list(mapping)].sel(time=[stamp]), grid.area, mapping)
            part = part.load()
            lat, lon = part["lat"].values, part["lon"].values
            same = lat.shape == lat_t.shape and lon.shape == lon_t.shape
            assert same and np.allclose(lat, lat_t) and np.allclose(lon, lon_t), (
                f"ERA5 grid != {grid.name} grid"
            )
            return {c: part[c].values[0].astype("float64") for c in mapping.values()}

        label = f"{stamp:%Y-%m-%d %H:00} {'+'.join(mapping.values())}"
        return era5._retry(load, retries, retry_wait, label)

    out = {c: np.empty((len(days), *grid.shape), dtype=np.float32) for c in pcodes}
    ivt = np.empty((len(days), *grid.shape), dtype=np.float32) if want_ivt else None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for start in range(0, len(days), LOG_EVERY_DAYS):
            chunk = days[start : start + LOG_EVERY_DAYS]
            if pcodes:
                stamps = [d + pd.Timedelta(hours=h) for d in chunk for h in range(1, 25)]
                fields = list(pool.map(lambda t: hour_fields(t, names), stamps))
                for c in pcodes:
                    for i in range(len(chunk)):
                        hours = [f[c] for f in fields[24 * i : 24 * (i + 1)]]
                        out[c][start + i] = (np.sum(hours, axis=0) * 1000.0).astype("float32")
            if ivt is not None:
                stamps = [d + pd.Timedelta(hours=h) for d in chunk for h in IVT_HOURS]
                fields = list(pool.map(lambda t: hour_fields(t, IVT_NAMES), stamps))
                k = len(IVT_HOURS)
                for i in range(len(chunk)):
                    mags = [np.hypot(f["viwve"], f["viwvn"]) for f in fields[k * i : k * (i + 1)]]
                    ivt[start + i] = np.mean(mags, axis=0).astype("float32")
            log_fn(f"era5 observed {start + len(chunk)}/{len(days)} days")
    era5t = bool(days[-1] + pd.Timedelta(days=1) > stop)
    data_vars = {
        OBS_VARIABLES[c][1]: (("date", "lat", "lon"), out[c], {"units": "mm"}) for c in pcodes
    }
    if ivt is not None:
        data_vars["ivt"] = (("date", "lat", "lon"), ivt, {"units": fc.IVT_UNITS})
    arco_names = [OBS_VARIABLES[c][0] for c in pcodes] + (list(IVT_NAMES) if want_ivt else [])
    return xr.Dataset(
        data_vars,
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
            "variables": ",".join(arco_names),
            **({"ivt_window": IVT_NOTE} if want_ivt else {}),
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

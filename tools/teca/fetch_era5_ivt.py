"""Download ERA5 vertically integrated water vapour flux and write monthly IVT files.

Usage: python fetch_era5_ivt.py --year 2023 --hours 00,06,12,18 --out data/ivt

Output: one CF-compliant netCDF per month (ivt_YYYY-MM.nc) with variable ``IVT``
(kg m-1 s-1) on dims time/lat/lon, ready for ``teca_bayesian_ar_detect``.
Source: ERA5, Copernicus Climate Change Service (CDS), CC-BY 4.0.
"""

from __future__ import annotations

import argparse
import calendar
import shutil
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

DATASET = "reanalysis-era5-single-levels"
VARIABLES = [
    "vertical_integral_of_eastward_water_vapour_flux",
    "vertical_integral_of_northward_water_vapour_flux",
]
# North, West, South, East: Neuquen, the Andes and the Pacific inflow.
AREA = [-15, -95, -60, -40]
TIME_UNITS = "hours since 1900-01-01 00:00:00"


def ivt_magnitude(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Magnitude of the IVT vector, float32."""
    return np.hypot(u, v).astype(np.float32)


def _find_var(ds, short_names: tuple[str, ...], keyword: str) -> str:
    for name in short_names:
        if name in ds.data_vars:
            return name
    for name, var in ds.data_vars.items():
        text = f"{var.attrs.get('long_name', '')} {var.attrs.get('standard_name', '')}".lower()
        if keyword in text and "vapour" in text.replace("vapor", "vapour"):
            return name
    raise KeyError(f"no variable matching '{keyword}' in {list(ds.data_vars)}")


def build_ivt_dataset(ds):
    """Turn a raw ERA5 dataset (u, v flux) into a TECA-friendly IVT dataset."""
    import xarray as xr

    ds = ds.rename(
        {k: v for k, v in {"valid_time": "time", "latitude": "lat", "longitude": "lon"}.items() if k in ds.dims or k in ds.coords}
    )
    u_name = _find_var(ds, ("viwve", "p71.162"), "eastward")
    v_name = _find_var(ds, ("viwvn", "p72.162"), "northward")
    ivt = ivt_magnitude(ds[u_name].values, ds[v_name].values)
    out = xr.Dataset(
        {"IVT": (("time", "lat", "lon"), ivt)},
        coords={"time": ds["time"].values, "lat": ds["lat"].values, "lon": ds["lon"].values},
    )
    out = out.sortby("lat").sortby("time")
    out["IVT"].attrs = {
        "long_name": "integrated water vapor transport magnitude",
        "units": "kg m-1 s-1",
    }
    out["lat"].attrs = {"units": "degrees_north", "standard_name": "latitude", "axis": "Y"}
    out["lon"].attrs = {"units": "degrees_east", "standard_name": "longitude", "axis": "X"}
    out["time"].attrs = {"standard_name": "time", "axis": "T"}
    out.attrs = {
        "Conventions": "CF-1.8",
        "title": "ERA5 IVT magnitude",
        "source": "ERA5 (Copernicus Climate Change Service), CC-BY 4.0",
    }
    return out


def write_ivt(out, path: Path) -> None:
    encoding = {
        "time": {"units": TIME_UNITS, "calendar": "standard", "dtype": "float64"},
        "IVT": {"zlib": True, "complevel": 4, "dtype": "float32"},
    }
    out.to_netcdf(path, encoding=encoding)


def _request(year: int, month: int, hours: list[str]) -> dict:
    days = calendar.monthrange(year, month)[1]
    return {
        "product_type": ["reanalysis"],
        "variable": VARIABLES,
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "day": [f"{d:02d}" for d in range(1, days + 1)],
        "time": [f"{h}:00" for h in hours],
        "area": AREA,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def _open_download(path: Path):
    import xarray as xr

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if n.endswith(".nc")]
            zf.extractall(path.parent / (path.stem + "_unz"))
        parts = [xr.open_dataset(path.parent / (path.stem + "_unz") / n) for n in members]
        return xr.merge(parts, compat="override")
    return xr.open_dataset(path)


def _parse_months(text: str) -> list[int]:
    """Parse "1-12", "3" or "1,2,5-7" into a sorted list of months."""
    months: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        months.update(range(int(lo), int(hi or lo) + 1))
    if not months or not all(1 <= m <= 12 for m in months):
        raise ValueError(f"invalid --months: {text!r}")
    return sorted(months)


def _queue_full(exc: Exception) -> bool:
    """CDS rejects a job outright when the dataset already has too many queued requests."""
    return "queued requests" in str(exc).lower()


def _download_month(
    year: int,
    month: int,
    hours: list[str],
    raw: Path,
    retries: int,
    retry_wait: float = 60,
    queue_wait: float = 300,
    queue_timeout: float = 3600,
) -> Path:
    """Queue and download one month. Runs in a worker thread (own client per thread).

    Waits ``retry_wait * attempt`` seconds between failed attempts. A full CDS queue is not a failure:
    wait ``queue_wait`` and retry without spending an attempt, until ``queue_timeout`` seconds have been
    waited in total. A month that gives up leaves no raw file.
    """
    import cdsapi  # reads ~/.cdsapirc

    client = cdsapi.Client()
    queued = 0.0  # seconds slept on a full queue, summed from the sleeps themselves (no wall clock)
    attempt = 1
    while True:
        try:
            client.retrieve(DATASET, _request(year, month, hours), str(raw))
            return raw
        except Exception as exc:
            if _queue_full(exc):
                if queued + queue_wait > queue_timeout:
                    print(f"month {month:02d} CDS queue still full after {queued:.0f}s: {exc}", file=sys.stderr, flush=True)
                    raw.unlink(missing_ok=True)
                    raise
                print(f"month {month:02d} CDS queue full, waiting {queue_wait:.0f}s", file=sys.stderr, flush=True)
                time.sleep(queue_wait)
                queued += queue_wait
                continue
            print(f"month {month:02d} attempt {attempt} failed: {exc}", file=sys.stderr, flush=True)
            if attempt >= retries:
                raw.unlink(missing_ok=True)
                raise
            time.sleep(retry_wait * attempt)
            attempt += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--hours", default="00,06,12,18", help="comma-separated UTC hours")
    parser.add_argument("--months", default="1-12", help='months to fetch, e.g. "1-12", "3", "1,2,5-7"')
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--retry-wait", type=float, default=60,
        help="base seconds between retries; attempt N waits retry-wait * N (linear backoff)",
    )
    parser.add_argument(
        "--queue-wait", type=float, default=300,
        help="seconds to wait before retrying when the CDS queue is full (does not use up --retries)",
    )
    parser.add_argument(
        "--queue-timeout", type=float, default=3600,
        help="give up on a month after waiting this many seconds in total on a full CDS queue",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="parallel CDS requests; CDS rejects parallel queued requests, so download sequentially",
    )
    args = parser.parse_args(argv)

    hours = [h.strip().zfill(2) for h in args.hours.split(",") if h.strip()]
    args.out.mkdir(parents=True, exist_ok=True)

    # A cancelled run can leave partial downloads behind; they must never be mistaken for data.
    for stale in args.out.glob("raw_*.nc"):
        stale.unlink()
    for stale in args.out.glob("raw_*_unz"):
        shutil.rmtree(stale, ignore_errors=True)

    pending: list[int] = []
    for month in _parse_months(args.months):
        target = args.out / f"ivt_{args.year}-{month:02d}.nc"
        if target.exists():
            print(f"skip {target} (exists)", flush=True)
        else:
            pending.append(month)

    # Months are independent: download them (sequentially by default) and convert each one as it lands,
    # so a later failure or cancel keeps the months already written (and cached by the workflow).
    failed: list[int] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                _download_month,
                args.year, m, hours, args.out / f"raw_{args.year}-{m:02d}.nc", args.retries, args.retry_wait,
                args.queue_wait, args.queue_timeout,
            ): m
            for m in pending
        }
        for fut in as_completed(futures):
            month = futures[fut]
            try:
                raw = fut.result()
            except Exception as exc:
                print(f"month {month:02d} gave up: {exc}", file=sys.stderr, flush=True)
                failed.append(month)
                continue
            target = args.out / f"ivt_{args.year}-{month:02d}.nc"
            ds = _open_download(raw)
            out = build_ivt_dataset(ds)
            write_ivt(out, target)
            ds.close()
            raw.unlink()
            print(f"wrote {target} ({out.sizes['time']} steps)", flush=True)
    if failed:
        print(f"months failed: {sorted(failed)}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

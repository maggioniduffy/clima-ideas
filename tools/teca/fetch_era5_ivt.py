"""Download ERA5 vertically integrated water vapour flux and write monthly IVT files.

Usage: python fetch_era5_ivt.py --year 2023 --hours 00,06,12,18 --out data/ivt

Output: one CF-compliant netCDF per month (ivt_YYYY-MM.nc) with variable ``IVT``
(kg m-1 s-1) on dims time/lat/lon, ready for ``teca_bayesian_ar_detect``.
Source: ERA5, Copernicus Climate Change Service (CDS), CC-BY 4.0.
"""

from __future__ import annotations

import argparse
import calendar
import sys
import zipfile
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--hours", default="00,06,12,18", help="comma-separated UTC hours")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args(argv)

    import cdsapi  # reads ~/.cdsapirc

    hours = [h.strip().zfill(2) for h in args.hours.split(",") if h.strip()]
    args.out.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client()

    for month in range(1, 13):
        target = args.out / f"ivt_{args.year}-{month:02d}.nc"
        if target.exists():
            print(f"skip {target} (exists)", flush=True)
            continue
        raw = args.out / f"raw_{args.year}-{month:02d}.nc"
        for attempt in range(1, args.retries + 1):
            try:
                client.retrieve(DATASET, _request(args.year, month, hours), str(raw))
                break
            except Exception as exc:
                print(f"month {month:02d} attempt {attempt} failed: {exc}", file=sys.stderr, flush=True)
                if attempt == args.retries:
                    raise
        ds = _open_download(raw)
        out = build_ivt_dataset(ds)
        write_ivt(out, target)
        ds.close()
        raw.unlink()
        print(f"wrote {target} ({out.sizes['time']} steps)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

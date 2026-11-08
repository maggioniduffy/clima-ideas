"""Crop BARD (teca_bayesian_ar_detect) monthly netCDFs to a box and write one compressed file per year.

Usage: python crop_bard.py [--area=N,W,S,E] --out bard-crop/ bard_*.nc

Input: monthly files with ``ar_probability`` and ``ar_binary_tag`` on time/lat/lon (lon -180..180 or 0..360,
lat ascending or descending). Output: ``bard_neuquen_<year>.nc`` (time sorted, lat/lon ascending, lon in -180..180),
with the time encoding and global attributes kept, plus ``crop_area`` and ``source_files``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from fetch_era5_ivt import _parse_area  # noqa: E402

# N, W, S, E. Same box as backend clima_nqn.io.era5.NEUQUEN_BOX; keep both in sync.
NEUQUEN_BOX = [-34.0, -74.0, -43.0, -66.0]
VARIABLES = ("ar_probability", "ar_binary_tag")


def _fmt_area(area) -> str:
    return ",".join(f"{v:g}" for v in area)


def crop_dataset(ds, area):
    """Crop one dataset to N,W,S,E; lon is normalised to -180..180 and lat/lon sorted ascending."""
    north, west, south, east = area
    ds = ds.assign_coords(lon=((ds["lon"] + 180) % 360) - 180).sortby("lon").sortby("lat")
    lon_ok = ((ds["lon"] >= west) & (ds["lon"] <= east)).values
    lat_ok = ((ds["lat"] >= south) & (ds["lat"] <= north)).values
    if not lon_ok.any() or not lat_ok.any():
        raise ValueError(f"no grid points inside area {_fmt_area(area)}")
    return ds.isel(lon=np.flatnonzero(lon_ok), lat=np.flatnonzero(lat_ok))


def crop_files(files, area, out_dir) -> list[Path]:
    """Crop and concatenate files; write one bard_neuquen_<year>.nc per year found. Returns the written paths."""
    import xarray as xr

    files = [Path(f) for f in files]
    if not files:
        raise ValueError("no input files")
    parts = []
    time_encoding = None
    attrs = None
    for f in files:
        with xr.open_dataset(f) as raw:
            if time_encoding is None:
                time_encoding = dict(raw["time"].encoding)
                attrs = dict(raw.attrs)
            missing = [v for v in VARIABLES if v not in raw]
            if missing:
                raise KeyError(f"{f}: missing variables {missing}")
            parts.append(crop_dataset(raw[list(VARIABLES)], area).load())
    ds = xr.concat(parts, dim="time").sortby("time")
    _, keep = np.unique(ds["time"].values, return_index=True)
    ds = ds.isel(time=keep)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = ",".join(sorted(f.name for f in files))
    written = []
    for year, sub in ds.groupby("time.year"):
        sub = sub.drop_vars([c for c in ("year",) if c in sub.coords])
        sub.attrs = {**attrs, "crop_area": _fmt_area(area), "source_files": sources}
        sub["time"].encoding = {k: v for k, v in time_encoding.items() if k in ("units", "calendar", "dtype")}
        for name in VARIABLES:
            # Fresh encoding: inherited chunk sizes from the full grid are invalid for the crop.
            dtype = sub[name].encoding.get("dtype", sub[name].dtype)
            sub[name].encoding = {"zlib": True, "complevel": 4, "dtype": dtype}
        path = out_dir / f"bard_neuquen_{int(year)}.nc"
        sub.to_netcdf(path)
        print(f"{path}: {sub.sizes['time']} time steps, {sub.sizes['lat']}x{sub.sizes['lon']} points", flush=True)
        written.append(path)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, help="BARD netCDF files (bard_*.nc)")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--area", type=_parse_area, default=list(NEUQUEN_BOX), metavar="N,W,S,E",
        help='use --area=N,W,S,E (the "=" is needed for negative values); default Neuquen "-34,-74,-43,-66"',
    )
    args = parser.parse_args(argv)
    crop_files(args.files, args.area, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""GRIB decoding shared by the operational ingest (F6.1b) and the hindcast forecasts (F5.1)."""

from __future__ import annotations

import xarray as xr

from clima_nqn.io import era5


def _reduced_to_regular(h, area, step: float = 0.25) -> xr.DataArray:
    """Reduced Gaussian field linearly interpolated onto a regular ``step`` grid inside ``area``."""
    import eccodes
    import numpy as np
    from scipy.interpolate import LinearNDInterpolator

    north, west, south, east = area
    lat = eccodes.codes_get_array(h, "latitudes")
    lon = ((eccodes.codes_get_array(h, "longitudes") + 180.0) % 360.0) - 180.0
    val = eccodes.codes_get_values(h)
    pad = 1.0
    near = (lat >= south - pad) & (lat <= north + pad) & (lon >= west - pad) & (lon <= east + pad)
    tlat = np.round(np.arange(np.ceil(south / step), np.floor(north / step) + 1) * step, 4)
    tlon = np.round(np.arange(np.ceil(west / step), np.floor(east / step) + 1) * step, 4)
    interp = LinearNDInterpolator(np.column_stack([lon[near], lat[near]]), val[near])
    glon, glat = np.meshgrid(tlon, tlat)
    return xr.DataArray(interp(glon, glat), dims=("lat", "lon"), coords={"lat": tlat, "lon": tlon})


def grib_fields(
    data: bytes, area: tuple[float, float, float, float]
) -> list[tuple[dict, xr.DataArray]]:
    """Decode every message of a GRIB blob into ``(keys, field)`` cropped to ``area`` (N, W, S, E).

    ``keys`` has ``shortName``, ``step`` (hours), ``stepRange``, ``units`` and ``gridType`` (reduced Gaussian
    grids are interpolated linearly onto a regular 0.25 deg grid). The field has ascending ``lat``
    and ascending ``lon`` in -180..180, values as stored (ECMWF tp in m, GEFS APCP in kg/m2).
    """
    import eccodes  # lazy: needs the ecCodes C library (wheel `eccodeslib`)

    north, west, south, east = area
    out = []
    handles = []
    try:
        offset = 0
        while offset < len(data):  # split the blob by GRIB message length (bytes 8..16)
            if data[offset : offset + 4] != b"GRIB":
                offset += 1
                continue
            length = int.from_bytes(data[offset + 8 : offset + 16], "big")
            handles.append(eccodes.codes_new_from_message(data[offset : offset + length]))
            offset += length
        for h in handles:
            keys = {
                "shortName": eccodes.codes_get(h, "shortName"),
                "step": int(eccodes.codes_get(h, "endStep")),
                "stepRange": eccodes.codes_get(h, "stepRange"),
                "units": eccodes.codes_get(h, "units"),
                "gridType": eccodes.codes_get(h, "gridType"),
            }
            if keys["gridType"] == "reduced_gg":  # e.g. AIFS before 2024-06: octahedral O320
                da = _reduced_to_regular(h, area)
                out.append((keys, da))
                continue
            ni, nj = int(eccodes.codes_get(h, "Ni")), int(eccodes.codes_get(h, "Nj"))
            lats = eccodes.codes_get_array(h, "latitudes").reshape(nj, ni)[:, 0]
            lons = eccodes.codes_get_array(h, "longitudes").reshape(nj, ni)[0, :]
            vals = eccodes.codes_get_values(h).reshape(nj, ni)
            lons = ((lons + 180.0) % 360.0) - 180.0
            da = xr.DataArray(vals, dims=("lat", "lon"), coords={"lat": lats, "lon": lons})
            da = da.sortby("lat").sortby("lon")
            ilat = era5._axis_selection(da["lat"].values, south, north)
            ilon = era5._axis_selection(da["lon"].values, west, east)
            out.append((keys, da.isel(lat=ilat, lon=ilon).load()))
    finally:
        for h in handles:
            eccodes.codes_release(h)
    return out

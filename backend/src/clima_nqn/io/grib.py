"""GRIB decoding shared by the operational ingest (F6.1b) and the hindcast forecasts (F5.1)."""

from __future__ import annotations

import xarray as xr

from clima_nqn.io import era5


def grib_fields(
    data: bytes, area: tuple[float, float, float, float]
) -> list[tuple[dict, xr.DataArray]]:
    """Decode every message of a GRIB blob into ``(keys, field)`` cropped to ``area`` (N, W, S, E).

    ``keys`` has ``shortName``, ``step`` (hours) and ``stepRange``. The field has ascending ``lat``
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
            }
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

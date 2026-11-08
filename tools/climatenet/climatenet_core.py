"""Pure helpers for the ClimateNet AR run (no network, no torch): regridding, normalization, cropping, baseline.

ClimateNet (CGNet) expects four fields on the CAM5 grid, normalised with the mean/std of its config.json:
TMQ (total column water vapour), U850, V850 (wind at 850 hPa) and PSL (sea level pressure).
"""

from __future__ import annotations

import numpy as np

# N, W, S, E. Same box as tools/teca/crop_bard.py and backend clima_nqn.io.era5.NEUQUEN_BOX; keep in sync.
NEUQUEN_BOX = [-34.0, -74.0, -43.0, -66.0]

# Order and statistics copied from config.json of andregraubner/ClimateNet @ 474bb96 (verified from the file).
# Units: TMQ kg m-2, U850/V850 m s-1, PSL Pa.
FIELDS = ("TMQ", "U850", "V850", "PSL")
STATS = {
    "TMQ": {"mean": 19.21859, "std": 15.81723},
    "U850": {"mean": 1.55302, "std": 8.29764},
    "V850": {"mean": 0.25413, "std": 6.23163},
    "PSL": {"mean": 100814.414, "std": 1461.2227},
}
# Class ids of the model output: labels ["Background", "Tropical Cyclone", "Atmospheric River"] in config.json.
AR_CLASS = 2

# Classic IVT threshold used as the simple baseline (kg m-1 s-1); documented in tools/climatenet/README.md.
IVT_THRESHOLD = 250.0


def model_grid(nlat: int = 768, nlon: int = 1152) -> tuple[np.ndarray, np.ndarray]:
    """Target grid: latitude ascending -90..90 (nlat points), longitude 0..360 exclusive (nlon points).

    The 768 x 1152 size is the CAM5 0.25 deg grid of the ClimateNet data set (sin verificar: not in the repo
    files); the network is fully convolutional, so other sizes divisible by 8 also run.
    """
    lat = np.linspace(-90.0, 90.0, nlat)
    lon = np.arange(nlon) * (360.0 / nlon)
    return lat, lon


def _lat_weights(src: np.ndarray, dst: np.ndarray):
    dst = np.clip(dst, src[0], src[-1])
    i0 = np.clip(np.searchsorted(src, dst, side="right") - 1, 0, len(src) - 2)
    w = (dst - src[i0]) / (src[i0 + 1] - src[i0])
    return i0, i0 + 1, np.clip(w, 0.0, 1.0)


def _lon_weights(src: np.ndarray, dst: np.ndarray):
    """Periodic linear weights; ``src`` ascending within one 360 deg turn."""
    n = len(src)
    ext = np.append(src, src[0] + 360.0)
    d = (dst - src[0]) % 360.0 + src[0]
    i0 = np.clip(np.searchsorted(ext, d, side="right") - 1, 0, n - 1)
    w = (d - ext[i0]) / (ext[i0 + 1] - ext[i0])
    return i0, (i0 + 1) % n, w


def regrid_bilinear(field, src_lat, src_lon, dst_lat, dst_lon) -> np.ndarray:
    """Bilinear regrid of ``field`` (..., lat, lon) to ``dst_lat`` x ``dst_lon``.

    Source latitude may be descending (ERA5) or ascending, source longitude 0..360 or -180..180 (wrapped
    periodically). Output latitude follows ``dst_lat`` order, longitude follows ``dst_lon``. Latitudes outside
    the source range take the edge row (no extrapolation).
    """
    field = np.asarray(field, dtype=np.float32)
    src_lat = np.asarray(src_lat, dtype=float)
    src_lon = np.asarray(src_lon, dtype=float) % 360.0
    if src_lat[0] > src_lat[-1]:
        src_lat = src_lat[::-1]
        field = field[..., ::-1, :]
    order = np.argsort(src_lon)
    src_lon, field = src_lon[order], field[..., order]
    y0, y1, wy = _lat_weights(src_lat, np.asarray(dst_lat, dtype=float))
    x0, x1, wx = _lon_weights(src_lon, np.asarray(dst_lon, dtype=float))
    wy = wy.astype(np.float32)[:, None]
    wx = wx.astype(np.float32)
    rows = field[..., y0, :] * (1 - wy) + field[..., y1, :] * wy
    return (rows[..., x0] * (1 - wx) + rows[..., x1] * wx).astype(np.float32)


def normalize_fields(
    fields: dict[str, np.ndarray], stats: dict = STATS, order=FIELDS
) -> np.ndarray:
    """Stack fields (each (time, lat, lon)) to (time, variable, lat, lon) and apply (x - mean) / std."""
    missing = [k for k in order if k not in fields]
    if missing:
        raise KeyError(f"missing fields {missing}")
    out = np.stack([np.asarray(fields[k], dtype=np.float32) for k in order], axis=1)
    for i, k in enumerate(order):
        out[:, i] = (out[:, i] - stats[k]["mean"]) / stats[k]["std"]
    return out


def crop_box(arr, lat, lon, area=NEUQUEN_BOX):
    """Crop (..., lat, lon) to N,W,S,E; returns (array, lat, lon) with lat/lon ascending and lon in -180..180."""
    north, west, south, east = area
    lat = np.asarray(lat, dtype=float)
    lon = ((np.asarray(lon, dtype=float) + 180.0) % 360.0) - 180.0
    arr = np.asarray(arr)
    lat_order, lon_order = np.argsort(lat), np.argsort(lon)
    arr = arr[..., lat_order, :][..., lon_order]
    lat, lon = lat[lat_order], lon[lon_order]
    lat_ok = (lat >= south) & (lat <= north)
    lon_ok = (lon >= west) & (lon <= east)
    if not lat_ok.any() or not lon_ok.any():
        raise ValueError("no grid points inside area")
    return arr[..., lat_ok, :][..., lon_ok], lat[lat_ok], lon[lon_ok]


def ivt_baseline(viwve, viwvn, threshold: float = IVT_THRESHOLD) -> tuple[np.ndarray, np.ndarray]:
    """IVT magnitude (float32, kg m-1 s-1) and the boolean mask IVT >= threshold (NaN is False)."""
    ivt = np.hypot(viwve, viwvn).astype(np.float32)
    return ivt, ivt >= threshold


CHECKPOINT_KEYS = ("net_state_dict", "model_state_dict", "state_dict")


def extract_state_dict(obj: dict) -> dict:
    """Model weights from a torch.load result: a bare state_dict or a training checkpoint.

    The NERSC ClimateNet weights are a checkpoint (``epoch``, ``net_state_dict``, ``optimizer_state_dict``,
    ...); the weights are under ``net_state_dict``. A ``module.`` prefix (DataParallel) is stripped.
    """
    for key in CHECKPOINT_KEYS:
        if key in obj and isinstance(obj[key], dict):
            obj = obj[key]
            break
    if obj and all(k.startswith("module.") for k in obj):
        obj = {k[len("module."):]: v for k, v in obj.items()}
    return obj

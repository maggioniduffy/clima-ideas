"""Small catchments draining onto target geometries (F4.1, plan/04-debris-flows.md).

``delineate(dem, transform, targets)`` conditions the DEM and computes D8 flow directions with pysheds, then finds
every cell outside the targets whose D8 receiver is a target cell (an *outlet*) and labels all cells upstream of
each outlet. A catchment is kept when its area is within ``[min_area_km2, max_area_km2]``.

Choices (all sin verificar against literature for Neuquén):
- Default "small basin" range: 0.1 to 25 km2 (``DEFAULT_MIN_AREA_KM2``, ``DEFAULT_MAX_AREA_KM2``). Design choice
  for debris-flow-prone fans, not a standard; configurable.
- Targets are rasterised with ``all_touched`` and dilated by one cell (8-neighbourhood) so a diagonal road line
  cannot leak flow through a gap between cells.
- Cell sizes use a spherical Earth (R = 6371008.8 m) per row; slope and flow-path lengths use the same metric
  spacing. pysheds picks the steepest D8 neighbour using degree spacing, a small bias at -39 deg (cos = 0.78).
- Cells flowing out of the DEM, or into nodata, simply end there (catchments touching the DEM edge are
  truncated; the caller should pad the bbox).

Output: Parquet with WKB geometry (EPSG:4326) and ``geo`` metadata, written with pyarrow (geopandas is not a
dependency). Source and period are stored in the file metadata.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from affine import Affine
from pyproj import Proj
from pysheds.grid import Grid
from pysheds.sview import Raster, ViewFinder
from rasterio import features
from shapely import wkb
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

EARTH_RADIUS_M = 6371008.8
DEFAULT_MIN_AREA_KM2 = 0.1
DEFAULT_MAX_AREA_KM2 = 25.0
SOURCE = "Copernicus DEM GLO-30 (ESA); cuencas D8 con pysheds"
PERIOD = "2021-01-01/2021-12-31"  # DEM release period as in io/dem.py (acquisition period sin verificar)
# pysheds default dirmap order: N, NE, E, SE, S, SW, W, NW -> (drow, dcol)
_DIRMAP = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


@dataclass(frozen=True)
class Catchment:
    id: int
    target: str
    geometry: BaseGeometry  # lon/lat polygon
    area_km2: float
    mean_slope_deg: float
    relief_m: float
    longest_flow_path_m: float
    outlet_lon: float
    outlet_lat: float


def cell_area_m2(transform: Affine, nrows: int) -> np.ndarray:
    """Area (m2) of one cell per row, spherical Earth."""
    lat = transform.f + transform.e * (np.arange(nrows) + 0.5)
    dlon, dlat = abs(transform.a), abs(transform.e)
    return np.radians(dlon) * np.radians(dlat) * EARTH_RADIUS_M**2 * np.cos(np.radians(lat))


def _target_ids(targets, shape_, transform: Affine) -> np.ndarray:
    ids = np.zeros(shape_, dtype=np.int32)
    for i, (_, geom) in enumerate(targets, start=1):
        feats = features.rasterize(
            [(geom, i)], out_shape=shape_, transform=transform, fill=0, all_touched=True, dtype="int32"
        )
        ids = np.where(feats > 0, feats, ids)
    out = ids.copy()
    nr, nc = shape_
    for dr in (-1, 0, 1):  # dilate by one cell
        for dc in (-1, 0, 1):
            if dr == dc == 0:
                continue
            sh = np.zeros_like(ids)
            sh[max(dr, 0) : nr + min(dr, 0), max(dc, 0) : nc + min(dc, 0)] = ids[
                max(-dr, 0) : nr + min(-dr, 0), max(-dc, 0) : nc + min(-dc, 0)
            ]
            out = np.where(out == 0, sh, out)
    return out


def _flow_directions(dem: np.ndarray, transform: Affine) -> np.ndarray:
    vf = ViewFinder(affine=transform, shape=dem.shape, crs=Proj("EPSG:4326"), nodata=np.nan)
    raster = Raster(dem.astype("float64"), viewfinder=vf)
    grid = Grid.from_raster(raster)
    cond = grid.fill_pits(raster)
    cond = grid.fill_depressions(cond)
    cond = grid.resolve_flats(cond)
    return np.asarray(grid.flowdir(cond))


def _downstream(fdir: np.ndarray) -> np.ndarray:
    """Flat index of the D8 receiver per cell; -1 for pits, nodata and cells draining out of the grid."""
    nr, nc = fdir.shape
    rr, cc = np.indices(fdir.shape)
    down = np.full(fdir.shape, -1, dtype=np.int64)
    for code, (dr, dc) in _DIRMAP.items():
        m = fdir == code
        r2, c2 = rr + dr, cc + dc
        ok = m & (r2 >= 0) & (r2 < nr) & (c2 >= 0) & (c2 < nc)
        down[ok] = (r2 * nc + c2)[ok]
    return down.ravel()


def delineate(
    dem: np.ndarray,
    transform: Affine,
    targets: Sequence[tuple[str, BaseGeometry]],
    min_area_km2: float = DEFAULT_MIN_AREA_KM2,
    max_area_km2: float = DEFAULT_MAX_AREA_KM2,
) -> list[Catchment]:
    """Catchments whose outlet drains onto a target; see module docstring."""
    dem = np.asarray(dem, dtype="float64")
    nr, nc = dem.shape
    n = nr * nc
    tid = _target_ids(targets, dem.shape, transform).ravel()
    fdir = _flow_directions(dem, transform)
    down = _downstream(fdir)
    areas = np.repeat(cell_area_m2(transform, nr), nc)
    valid = ~np.isnan(dem.ravel())

    # topological order: process upstream cells before downstream ones via accumulated cell counts
    acc = np.ones(n, dtype=np.int64)
    indeg = np.zeros(n, dtype=np.int64)
    has_down = (down >= 0) & valid
    np.add.at(indeg, down[has_down], 1)
    order = []
    stack = list(np.flatnonzero(valid & (indeg == 0)))
    while stack:
        i = stack.pop()
        order.append(i)
        d = down[i]
        if d >= 0 and valid[i]:
            acc[d] += acc[i]
            indeg[d] -= 1
            if indeg[d] == 0:
                stack.append(d)
    order_arr = np.asarray(order, dtype=np.int64)  # upstream first; reversed = downstream first

    inflow = np.zeros(n, dtype=np.float64)  # catchment area upstream of each cell (own cell included)
    inflow[:] = np.where(valid & (tid == 0), areas, 0.0)
    for i in order_arr:
        d = down[i]
        if d >= 0 and tid[i] == 0 and tid[d] == 0:
            inflow[d] += inflow[i]

    is_outlet = valid & (tid == 0) & (down >= 0)
    is_outlet &= np.where(down >= 0, tid[np.clip(down, 0, n - 1)] > 0, False)
    outlets = np.flatnonzero(is_outlet & (inflow >= min_area_km2 * 1e6) & (inflow <= max_area_km2 * 1e6))
    if len(outlets) == 0:
        return []

    label = np.full(n, -1, dtype=np.int64)
    label[outlets] = np.arange(len(outlets))
    dist = np.zeros(n, dtype=np.float64)  # flow-path length (m) to the outlet
    rows = np.arange(n) // nc
    cols = np.arange(n) % nc
    dy = abs(transform.e) * math.pi / 180 * EARTH_RADIUS_M
    lat_c = transform.f + transform.e * (rows + 0.5)
    dx = abs(transform.a) * math.pi / 180 * EARTH_RADIUS_M * np.cos(np.radians(lat_c))
    for i in order_arr[::-1]:
        d = down[i]
        if label[i] == -1 and d >= 0 and tid[i] == 0 and label[d] >= 0:
            label[i] = label[d]
            step = math.hypot(dx[i] * (cols[d] - cols[i]), dy * (rows[d] - rows[i]))
            dist[i] = dist[d] + step

    # slope (degrees) from the original DEM with metric spacing
    gy, gx = np.gradient(dem, dy, axis=0), np.gradient(dem, 1.0, axis=1) / dx.reshape(nr, nc)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).ravel()
    flat_dem = dem.ravel()

    label_img = label.reshape(nr, nc).astype("int32")
    polys: dict[int, list[BaseGeometry]] = {}
    for geom, val in features.shapes(label_img, mask=label_img >= 0, transform=transform):
        polys.setdefault(int(val), []).append(shape(geom))

    out: list[Catchment] = []
    for k, o in enumerate(outlets):
        sel = label == k
        o_lon, o_lat = transform @ (cols[o] + 0.5, rows[o] + 0.5)
        out.append(
            Catchment(
                id=k,
                target=targets[int(tid[down[o]]) - 1][0],
                geometry=unary_union(polys[k]),
                area_km2=float(areas[sel].sum() / 1e6),
                mean_slope_deg=float(np.nanmean(slope[sel])),
                relief_m=float(np.nanmax(flat_dem[sel]) - np.nanmin(flat_dem[sel])),
                longest_flow_path_m=float(dist[sel].max()),
                outlet_lon=float(o_lon),
                outlet_lat=float(o_lat),
            )
        )
    return out


def write_parquet(
    catchments: Sequence[Catchment], path: Path, source: str = SOURCE, period: str = PERIOD
) -> Path:
    """Parquet with WKB geometry column (EPSG:4326), GeoParquet-style ``geo`` metadata."""
    cols = {
        "id": [c.id for c in catchments],
        "target": [c.target for c in catchments],
        "area_km2": [c.area_km2 for c in catchments],
        "mean_slope_deg": [c.mean_slope_deg for c in catchments],
        "relief_m": [c.relief_m for c in catchments],
        "longest_flow_path_m": [c.longest_flow_path_m for c in catchments],
        "outlet_lon": [c.outlet_lon for c in catchments],
        "outlet_lat": [c.outlet_lat for c in catchments],
        "geometry": [wkb.dumps(c.geometry) for c in catchments],
    }
    geo = {
        "version": "1.0.0",
        "primary_column": "geometry",
        "columns": {"geometry": {"encoding": "WKB", "geometry_types": ["Polygon", "MultiPolygon"], "crs": "EPSG:4326"}},
    }
    table = pa.table(cols).replace_schema_metadata(
        {"geo": json.dumps(geo), "source": source, "period": period}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return path

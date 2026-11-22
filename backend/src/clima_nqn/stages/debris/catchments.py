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
- Planar-flow flag (``planar_flow``): on planar terrain (GLO-30 fits a plane with RMSE ~1.4 m, slope ~1 %) D8 routes
  parallel straight lines that never converge, and each line or band becomes a fake catchment shaped like a
  rotated rectangle. ``rectangularity`` (polygon area / minimum rotated rectangle area) and ``elongation`` (long /
  short side of that rectangle) are measured in a local metric frame (longitude scaled by cos(lat)). See
  ``PLANAR_RECTANGULARITY`` / ``PLANAR_ELONGATION``.
- Channel crossing (``channel``, primary criterion since F4.3 "cauces"): D8 alone cannot tell a real channel from a D8
  artifact on planar terrain, and a channel-initiation area threshold does not either (on a plane the accumulation
  at the bottom of a strip equals the slope length in cells, like a compact real catchment of the same area). What
  does differ is convergence along the target. D-infinity accumulation (``dinf_acc_km2``, pysheds
  ``routing='dinf'`` on the same conditioned DEM) at an outlet is compared with the median D-inf accumulation of
  the *feeder cells* of the same target within +-R metres along it (``prominence``): non-target cells 8-adjacent to
  a target cell of the same target that is at or below them in the conditioned DEM, i.e. cells that can feed the
  target. A channel crossing has ``dinf_acc_km2 >= CHANNEL_MIN_ACC_KM2`` and ``prominence >= CHANNEL_MIN_PROMINENCE``.
  Feeder cells are used instead of "cells whose D8 receiver is a target cell" because in a valley with steep lateral
  slope the arms drain sideways to the axis, so the only D8 drainer would be the outlet itself (prominence 1). All
  thresholds and R are criterio propio, sin verificar. pysheds takes the cell size in degrees for D-inf facets
  (bias of the same order as for D8).
- Cells flowing out of the DEM, or into nodata, simply end there (catchments touching the DEM edge are
  truncated; the caller should pad the bbox).

Output: Parquet with WKB geometry (EPSG:4326) and ``geo`` metadata, written with pyarrow (geopandas is not a
dependency). Source and period are stored in the file metadata.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from affine import Affine
from pyproj import Proj
from pysheds.grid import Grid
from pysheds.sview import Raster, ViewFinder
from rasterio import features
from scipy.spatial import cKDTree
from shapely import affinity, wkb
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

EARTH_RADIUS_M = 6371008.8
DEFAULT_MIN_AREA_KM2 = 0.1
DEFAULT_MAX_AREA_KM2 = 25.0
# Planar-flow (D8 artifact) criterion: criterio propio, sin verificar. Sensitivity on the 841 catchments of the
# Routes 5/7 + urban runs: rectangularity >= 0.85 and elongation >= 3 flags 252 (30 %); 0.70 / 3 flags 292, so the
# count is stable. The rectangularity distribution is bimodal (median 0.62, 75th percentile 1.0).
# Second rule: diagonal strips 2-3 cells wide have stair-step edges (rectangularity 0.33-0.75) but extreme
# elongation (45-280). Among catchments not flagged by the first rule, elongation is bimodal with a trough between
# 12 and 20; elongation >= 15 flags 81 more (74 at 20, 86 at 10), all <= 3.5 km2. Also criterio propio, sin verificar.
PLANAR_RECTANGULARITY = 0.85
PLANAR_ELONGATION = 3.0
PLANAR_STRIP_ELONGATION = 15.0
# Channel-crossing criterion (criterio propio, sin verificar; sensitivity in reports/04/F4.3-channels.md).
CHANNEL_MIN_ACC_KM2 = 0.05
CHANNEL_MIN_PROMINENCE = 3.0
PROMINENCE_RADIUS_M = 500.0
PROMINENCE_RADII_M = (
    250,
    500,
    1000,
)  # radii always stored as ``prominence_r<R>`` for sensitivity analysis
SOURCE = "Copernicus DEM GLO-30 (ESA); cuencas D8 con pysheds"
PERIOD = (
    "2021-01-01/2021-12-31"  # DEM release period as in io/dem.py (acquisition period sin verificar)
)
# pysheds default dirmap order: N, NE, E, SE, S, SW, W, NW -> (drow, dcol)
_DIRMAP = {
    64: (-1, 0),
    128: (-1, 1),
    1: (0, 1),
    2: (1, 1),
    4: (1, 0),
    8: (1, -1),
    16: (0, -1),
    32: (-1, -1),
}


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
    rectangularity: float  # polygon area / minimum rotated rectangle area (metric frame), 0..1
    elongation: float  # long / short side of the minimum rotated rectangle (capped at 1000)
    planar_flow: bool  # old shape rule (secondary): likely D8 artifact on planar terrain; see PLANAR_* constants
    dinf_acc_km2: float = float("nan")  # D-infinity accumulated area at the outlet cell
    prominence: float = float(
        "nan"
    )  # dinf acc at the outlet / median dinf acc of feeder cells within +-R m
    channel: bool = (
        False  # dinf_acc_km2 >= A_MIN and prominence >= K: a real channel crossing the target
    )
    prominence_by_r: dict[int, float] = field(
        default_factory=dict
    )  # prominence for each PROMINENCE_RADII_M


def shape_metrics(geom: BaseGeometry) -> tuple[float, float]:
    """``(rectangularity, elongation)`` of a lon/lat polygon, in a local metric frame (lon scaled by cos(lat))."""
    lat0 = geom.centroid.y
    kx = math.cos(math.radians(lat0))
    g = affinity.scale(geom, xfact=kx, yfact=1.0, origin=(0, 0))
    rect = g.minimum_rotated_rectangle
    if rect.geom_type != "Polygon" or rect.area <= 0:
        return 1.0, 1000.0
    rect_area = rect.area
    xs, ys = rect.exterior.coords.xy
    sides = sorted(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2))
    elong = min(sides[1] / sides[0], 1000.0) if sides[0] > 0 else 1000.0
    return min(g.area / rect_area, 1.0), elong


def is_planar_flow(rectangularity: float, elongation: float) -> bool:
    rectangular = rectangularity >= PLANAR_RECTANGULARITY and elongation >= PLANAR_ELONGATION
    return rectangular or elongation >= PLANAR_STRIP_ELONGATION


def cell_area_m2(transform: Affine, nrows: int) -> np.ndarray:
    """Area (m2) of one cell per row, spherical Earth."""
    lat = transform.f + transform.e * (np.arange(nrows) + 0.5)
    dlon, dlat = abs(transform.a), abs(transform.e)
    return np.radians(dlon) * np.radians(dlat) * EARTH_RADIUS_M**2 * np.cos(np.radians(lat))


def _target_ids(targets, shape_, transform: Affine) -> np.ndarray:
    ids = np.zeros(shape_, dtype=np.int32)
    for i, (_, geom) in enumerate(targets, start=1):
        feats = features.rasterize(
            [(geom, i)],
            out_shape=shape_,
            transform=transform,
            fill=0,
            all_touched=True,
            dtype="int32",
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


def _condition(dem: np.ndarray, transform: Affine):
    """pysheds grid and DEM conditioned with pit filling, depression filling and flat resolution."""
    vf = ViewFinder(affine=transform, shape=dem.shape, crs=Proj("EPSG:4326"), nodata=np.nan)
    raster = Raster(dem.astype("float64"), viewfinder=vf)
    grid = Grid.from_raster(raster)
    cond = grid.fill_pits(raster)
    cond = grid.fill_depressions(cond)
    cond = grid.resolve_flats(cond)
    return grid, cond


def _dinf_accumulation_km2(grid, cond, cell_area_m2_rows: np.ndarray) -> np.ndarray:
    """D-infinity accumulated area (km2, own cell included) on the conditioned DEM, flat array."""
    fdir = grid.flowdir(cond, routing="dinf")
    weights = Raster(
        np.repeat(cell_area_m2_rows[:, None], cond.shape[1], axis=1).astype("float64"),
        viewfinder=cond.viewfinder,
    )
    acc = grid.accumulation(fdir, weights=weights, routing="dinf")
    return np.asarray(acc, dtype="float64").ravel() / 1e6


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


def feeder_cells(
    tid: np.ndarray, elev: np.ndarray, valid: np.ndarray, nc: int
) -> tuple[np.ndarray, np.ndarray]:
    """Feeder cells: non-target valid cells 8-adjacent to a target cell at or below them in ``elev``.

    Returns ``(flat cell indices, target id of the lowest adjacent target cell)``.
    """
    n = tid.size
    tcells = np.flatnonzero(tid > 0)
    cand, cand_elev, cand_tid = [], [], []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == dc == 0:
                continue
            r2 = tcells // nc + dr
            c2 = tcells % nc + dc
            ok = (r2 >= 0) & (r2 < n // nc) & (c2 >= 0) & (c2 < nc)
            nb = (r2 * nc + c2)[ok]
            src = tcells[ok]
            keep = (tid[nb] == 0) & valid[nb]
            cand.append(nb[keep])
            cand_elev.append(elev[src[keep]])
            cand_tid.append(tid[src[keep]])
    if not cand or sum(len(c) for c in cand) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int32)
    nb = np.concatenate(cand)
    te = np.concatenate(cand_elev)
    tt = np.concatenate(cand_tid)
    order = np.lexsort((te, nb))  # by cell, then lowest adjacent target elevation first
    nb, te, tt = nb[order], te[order], tt[order]
    first = np.r_[True, nb[1:] != nb[:-1]]
    nb, te, tt = nb[first], te[first], tt[first]
    feeds = elev[nb] >= te
    return nb[feeds], tt[feeds]


def outlet_prominence(
    outlets: np.ndarray,
    outlet_tid: np.ndarray,
    feeders: np.ndarray,
    feeder_tid: np.ndarray,
    acc_km2: np.ndarray,
    xy_m,
    radius_m: float,
) -> np.ndarray:
    """dinf acc at each outlet / median dinf acc of same-target feeder cells within ``radius_m`` (outlet included).

    ``xy_m(flat_idx)`` gives metric ``(n, 2)`` coordinates.
    """
    out = np.full(len(outlets), np.nan)
    if len(feeders) == 0:
        return out
    tree = cKDTree(xy_m(feeders))
    for k, (o, t) in enumerate(zip(outlets, outlet_tid, strict=True)):
        idx = np.asarray(tree.query_ball_point(xy_m(np.array([o]))[0], radius_m), dtype=np.int64)
        idx = idx[feeder_tid[idx] == t]
        vals = acc_km2[feeders[idx]]
        vals = np.append(vals, acc_km2[o]) if not np.any(feeders[idx] == o) else vals
        med = float(np.median(vals)) if len(vals) else float("nan")
        out[k] = acc_km2[o] / med if med > 0 else float("nan")
    return out


def delineate(
    dem: np.ndarray,
    transform: Affine,
    targets: Sequence[tuple[str, BaseGeometry]],
    min_area_km2: float = DEFAULT_MIN_AREA_KM2,
    max_area_km2: float = DEFAULT_MAX_AREA_KM2,
    channel_min_acc_km2: float = CHANNEL_MIN_ACC_KM2,
    channel_min_prominence: float = CHANNEL_MIN_PROMINENCE,
    prominence_radius_m: float = PROMINENCE_RADIUS_M,
) -> list[Catchment]:
    """Catchments whose outlet drains onto a target; see module docstring."""
    dem = np.asarray(dem, dtype="float64")
    nr, nc = dem.shape
    n = nr * nc
    tid = _target_ids(targets, dem.shape, transform).ravel()
    grid, cond = _condition(dem, transform)
    fdir = np.asarray(grid.flowdir(cond))
    down = _downstream(fdir)
    del fdir
    row_areas = cell_area_m2(transform, nr)
    areas = np.repeat(row_areas, nc)
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

    inflow = np.zeros(
        n, dtype=np.float64
    )  # catchment area upstream of each cell (own cell included)
    inflow[:] = np.where(valid & (tid == 0), areas, 0.0)
    for i in order_arr:
        d = down[i]
        if d >= 0 and tid[i] == 0 and tid[d] == 0:
            inflow[d] += inflow[i]

    is_outlet = valid & (tid == 0) & (down >= 0)
    is_outlet &= np.where(down >= 0, tid[np.clip(down, 0, n - 1)] > 0, False)
    outlets = np.flatnonzero(
        is_outlet & (inflow >= min_area_km2 * 1e6) & (inflow <= max_area_km2 * 1e6)
    )
    if len(outlets) == 0:
        return []

    # D-infinity convergence at the outlets (see module docstring)
    acc_km2 = _dinf_accumulation_km2(grid, cond, row_areas)
    cond_flat = np.asarray(cond, dtype="float64").ravel()
    del grid, cond
    feeders, feeder_tid = feeder_cells(tid, cond_flat, valid, nc)
    del cond_flat
    kx = math.cos(math.radians(transform.f + transform.e * nr / 2))
    mx = abs(transform.a) * math.pi / 180 * EARTH_RADIUS_M * kx
    my = abs(transform.e) * math.pi / 180 * EARTH_RADIUS_M

    def xy_m(idx):
        return np.column_stack([(idx % nc) * mx, (idx // nc) * my])

    outlet_tid = tid[down[outlets]]
    radii = sorted({int(r) for r in PROMINENCE_RADII_M} | {round(prominence_radius_m)})
    prom = {
        r: outlet_prominence(outlets, outlet_tid, feeders, feeder_tid, acc_km2, xy_m, float(r))
        for r in radii
    }
    main_prom = prom[round(prominence_radius_m)]

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
        geom = unary_union(polys[k])
        rect, elong = shape_metrics(geom)
        out.append(
            Catchment(
                id=k,
                target=targets[int(tid[down[o]]) - 1][0],
                geometry=geom,
                area_km2=float(areas[sel].sum() / 1e6),
                mean_slope_deg=float(np.nanmean(slope[sel])),
                relief_m=float(np.nanmax(flat_dem[sel]) - np.nanmin(flat_dem[sel])),
                longest_flow_path_m=float(dist[sel].max()),
                outlet_lon=float(o_lon),
                outlet_lat=float(o_lat),
                rectangularity=rect,
                elongation=elong,
                planar_flow=is_planar_flow(rect, elong),
                dinf_acc_km2=float(acc_km2[o]),
                prominence=float(main_prom[k]),
                channel=bool(
                    acc_km2[o] >= channel_min_acc_km2 and main_prom[k] >= channel_min_prominence
                ),
                prominence_by_r={r: float(prom[r][k]) for r in PROMINENCE_RADII_M},
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
        "rectangularity": [c.rectangularity for c in catchments],
        "elongation": [c.elongation for c in catchments],
        "planar_flow": [c.planar_flow for c in catchments],
        "dinf_acc_km2": [c.dinf_acc_km2 for c in catchments],
        "prominence": [c.prominence for c in catchments],
        "channel": [c.channel for c in catchments],
        **{
            f"prominence_r{r}": [c.prominence_by_r.get(r, float("nan")) for c in catchments]
            for r in PROMINENCE_RADII_M
        },
        "geometry": [wkb.dumps(c.geometry) for c in catchments],
    }
    geo = {
        "version": "1.0.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": ["Polygon", "MultiPolygon"],
                "crs": "EPSG:4326",
            }
        },
    }
    table = pa.table(cols).replace_schema_metadata(
        {
            "geo": json.dumps(geo),
            "source": source,
            "period": period,
            "channel_min_acc_km2": str(CHANNEL_MIN_ACC_KM2),
            "channel_min_prominence": str(CHANNEL_MIN_PROMINENCE),
            "prominence_radius_m": str(PROMINENCE_RADIUS_M),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return path

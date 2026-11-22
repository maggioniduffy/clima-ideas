"""Run F4.1 over a bbox: mosaic GLO-30 tiles (io/dem.py), read target GeoJSON, write catchments Parquet.

Targets GeoJSON: LineString/Polygon features (lon/lat) with ``properties.name`` (or ``ref``). Roads can be
exported from OSM with Overpass (e.g. ``way["ref"~"^(RN ?5|RN ?7|5|7)$"]`` inside the Neuquén area; exact tag
values sin verificar). Overpass was not reachable from the dev container, so no run on real roads exists yet.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from shapely.geometry import shape

from clima_nqn.io import dem
from clima_nqn.stages.debris import catchments

OUT_PATH = dem._DATA / "processed" / "debris" / "catchments.parquet"


def load_targets(path: Path) -> list[tuple[str, object]]:
    gj = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i, f in enumerate(gj["features"]):
        props = f.get("properties") or {}
        out.append(
            (str(props.get("name") or props.get("ref") or f"target_{i}"), shape(f["geometry"]))
        )
    return out


def read_dem(bbox: tuple[float, float, float, float], raw_dir: Path = dem.RAW_DIR):
    """Mosaic the tiles covering `bbox` and crop to it; returns (float array with NaN nodata, Affine)."""
    import rasterio
    from rasterio.merge import merge

    paths = dem.fetch_tiles(bbox, raw_dir)
    srcs = [rasterio.open(p) for p in paths]
    try:
        arr, transform = merge(srcs, bounds=bbox, nodata=np.nan, dtype="float32")
    finally:
        for s in srcs:
            s.close()
    return arr[0].astype("float64"), transform


def run(
    bbox: tuple[float, float, float, float],
    targets_path: Path,
    out: Path = OUT_PATH,
    min_area_km2: float = catchments.DEFAULT_MIN_AREA_KM2,
    max_area_km2: float = catchments.DEFAULT_MAX_AREA_KM2,
) -> tuple[Path, int]:
    arr, transform = read_dem(bbox)
    found = catchments.delineate(
        arr, transform, load_targets(targets_path), min_area_km2, max_area_km2
    )
    return catchments.write_parquet(found, out), len(found)

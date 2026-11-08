"""Relief layer: Copernicus DEM GLO-30 decimated to a Float32 point cloud."""

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
from rasterio.enums import Resampling

from clima_nqn.layers.manifest import LayerManifest
from clima_nqn.stages.ar import geo
from clima_nqn.stages.ar.catalog import _points_in_polygon

BUCKET_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
SOURCE = "Copernicus DEM GLO-30 (ESA)"
# Verified on registry.opendata.aws/copernicus-dem: free for the general public under the
# Licence linked there. The licence's formal title was not verified.
LICENSE = (
    "Copernicus DEM licence (free basis for the general public; terms at "
    "https://dataspace.copernicus.eu/explore-data/data-collections/"
    "copernicus-contributing-missions/collections-description/COP-DEM)"
)
# AWS registry: "Copernicus DEM 2021 release" (acquisition period not verified).
PERIOD = "2021-01-01/2021-12-31"
# Bbox (lon_min, lat_min, lon_max, lat_max) containing the province + 10 km band (band extent is
# lon -72.075..-67.895, lat -41.184..-36.039); a search rectangle, not the border.
NEUQUEN_BBOX = (-72.1, -41.2, -67.88, -36.02)
# degrees (~890 m in lat; 1/0.008 = 125 samples per tile degree) -> see build_relief for the point count
DEFAULT_STEP = 0.008
MAX_BYTES = 15_000_000
STRIDE = 3

# backend/src/clima_nqn/io/dem.py -> repo root is parents[4]
_DATA = Path(__file__).resolve().parents[4] / "data"
RAW_DIR = _DATA / "raw" / "glo30"
OUT_DIR = _DATA / "processed" / "relief"


def tile_name(lat: int, lon: int) -> str:
    """Tile name from its south-west corner (integer degrees)."""
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def tile_url(lat: int, lon: int) -> str:
    name = tile_name(lat, lon)
    return f"{BUCKET_URL}/{name}/{name}.tif"


def tiles_for_bbox(bbox: tuple[float, float, float, float]) -> list[tuple[int, int]]:
    """(lat, lon) south-west corners of the 1x1 degree tiles covering the bbox."""
    lon_min, lat_min, lon_max, lat_max = bbox
    return [
        (lat, lon)
        for lat in range(math.floor(lat_min), math.ceil(lat_max))
        for lon in range(math.floor(lon_min), math.ceil(lon_max))
    ]


def fetch_tiles(
    bbox: tuple[float, float, float, float] = NEUQUEN_BBOX,
    dest: Path = RAW_DIR,
    timeout: float = 120.0,
    retries: int = 4,
) -> list[Path]:
    """Stream each tile to `dest`, skipping files that already exist."""
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for lat, lon in tiles_for_bbox(bbox):
            path = dest / f"{tile_name(lat, lon)}.tif"
            paths.append(path)
            if path.exists():
                continue
            tmp = path.with_suffix(".part")
            for attempt in range(1, retries + 1):
                try:
                    with client.stream("GET", tile_url(lat, lon)) as r:
                        r.raise_for_status()
                        with tmp.open("wb") as f:
                            for chunk in r.iter_bytes(1 << 20):
                                f.write(chunk)
                    break
                except httpx.TransportError:
                    if attempt == retries:
                        raise
                    time.sleep(2 * attempt)
            tmp.rename(path)
    return paths


def decimate_tile(ds, step: float) -> np.ndarray:
    """Read an open raster decimated to `step` degrees; return (N, 3) float32 [lon, lat, elev]."""
    left, bottom, right, top = ds.bounds
    width = max(1, round((right - left) / step))
    height = max(1, round((top - bottom) / step))
    band = ds.read(1, out_shape=(height, width), resampling=Resampling.average, masked=True)
    data = np.ma.masked_invalid(band)
    if ds.nodata is not None:
        data = np.ma.masked_equal(data, ds.nodata)
    dx, dy = (right - left) / width, (top - bottom) / height
    lon = left + (np.arange(width) + 0.5) * dx
    lat = top - (np.arange(height) + 0.5) * dy
    lon_g, lat_g = np.meshgrid(lon, lat)
    valid = ~np.ma.getmaskarray(data)
    return np.column_stack([lon_g[valid], lat_g[valid], data.data[valid]]).astype(np.float32)


def clip_bbox(pts: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
    lon_min, lat_min, lon_max, lat_max = bbox
    keep = (
        (pts[:, 0] >= lon_min) & (pts[:, 0] <= lon_max)
        & (pts[:, 1] >= lat_min) & (pts[:, 1] <= lat_max)
    )  # fmt: skip
    return pts[keep]


def clip_polygon(pts: np.ndarray, ring: list[tuple[float, float]]) -> np.ndarray:
    """Keep the points whose (lon, lat) fall inside `ring` (even-odd ray casting, bbox prefilter)."""
    if len(pts) == 0:
        return pts
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    keep = np.zeros(len(pts), dtype=bool)
    in_box = (
        (pts[:, 0] >= min(xs)) & (pts[:, 0] <= max(xs))
        & (pts[:, 1] >= min(ys)) & (pts[:, 1] <= max(ys))
    )  # fmt: skip
    keep[in_box] = _points_in_polygon(pts[in_box, 0], pts[in_box, 1], ring)
    return pts[keep]


def write_relief(
    pts: np.ndarray, out_dir: Path, bbox: tuple[float, float, float, float], step: float
) -> Path:
    """Write relief.bin (interleaved little-endian Float32), meta and a validated manifest."""
    pts = np.ascontiguousarray(pts, dtype="<f4")
    if pts.nbytes >= MAX_BYTES:
        raise ValueError(f"relief.bin would be {pts.nbytes} bytes, limit is 15 MB")
    out_dir.mkdir(parents=True, exist_ok=True)
    bin_path = out_dir / "relief.bin"
    bin_path.write_bytes(pts.tobytes())
    meta = {
        "count": len(pts),
        "stride": STRIDE,
        "fields": ["lon", "lat", "elev_m"],
        "dtype": "float32-le",
        "bbox": list(bbox),
        "elev_min": float(pts[:, 2].min()) if len(pts) else None,
        "elev_max": float(pts[:, 2].max()) if len(pts) else None,
        "step": step,
    }
    (out_dir / "relief.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    manifest = LayerManifest(
        id="relief",
        title="Relieve",
        kind="points",
        source=SOURCE,
        period=PERIOD,
        license=LICENSE,
        updated_at=datetime.now(UTC),
        files=["relief.bin", "relief.meta.json"],
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return bin_path


def build_relief(
    raw_dir: Path = RAW_DIR,
    out_dir: Path = OUT_DIR,
    bbox: tuple[float, float, float, float] = NEUQUEN_BBOX,
    step: float = DEFAULT_STEP,
    clip_ring: list[tuple[float, float]] | None = None,
) -> Path:
    """Decimate each tile in turn (one in memory at a time) and write the layer.

    Points are clipped to the bbox and then to `clip_ring` (default: the Neuquén province outline buffered by 10 km,
    `geo.province_band_ring()`), the same band the viewer clips the IVT raster to. The bbox in relief.meta.json stays the rectangle searched.
    """
    if clip_ring is None:
        clip_ring = geo.province_band_ring()
    import rasterio

    chunks = []
    for lat, lon in tiles_for_bbox(bbox):
        path = raw_dir / f"{tile_name(lat, lon)}.tif"
        if not path.exists():
            raise FileNotFoundError(f"missing tile {path}; run `clima-nqn dem fetch`")
        with rasterio.open(path) as ds:
            chunks.append(clip_polygon(clip_bbox(decimate_tile(ds, step), bbox), clip_ring))
    pts = np.concatenate(chunks) if chunks else np.empty((0, 3), dtype=np.float32)
    return write_relief(pts, out_dir, bbox, step)

# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2"]
# ///
"""Buffer the Neuquén province outline by 10 km -> web/public/geo/neuquen-province-buffer-10km.geojson.

Run from the repo root:  uv run scripts/buffer_province.py

The buffer is computed in a local metric projection (Lambert azimuthal equal-area centred on the province, spherical
earth R = 6371 km) so 10 km is true distance, then projected back to lon/lat (EPSG:4326 order lon, lat).
Source outline: web/public/geo/neuquen-province.geojson (Natural Earth 1:10m, public domain). Approximate, sin verificar.
"""
import json
import math
from pathlib import Path

from shapely.geometry import Polygon, mapping
from shapely.ops import transform

BUFFER_M = 10_000
R = 6_371_000.0
LON0, LAT0 = math.radians(-69.8), math.radians(-38.9)
GEO = Path(__file__).resolve().parent.parent / "web" / "public" / "geo"


def forward(lon, lat):
    lam, phi = math.radians(lon), math.radians(lat)
    k = math.sqrt(2 / (1 + math.sin(LAT0) * math.sin(phi) + math.cos(LAT0) * math.cos(phi) * math.cos(lam - LON0)))
    return (
        R * k * math.cos(phi) * math.sin(lam - LON0),
        R * k * (math.cos(LAT0) * math.sin(phi) - math.sin(LAT0) * math.cos(phi) * math.cos(lam - LON0)),
    )


def inverse(x, y):
    rho = math.hypot(x, y)
    if rho == 0:
        return (math.degrees(LON0), math.degrees(LAT0))
    c = 2 * math.asin(rho / (2 * R))
    phi = math.asin(math.cos(c) * math.sin(LAT0) + y * math.sin(c) * math.cos(LAT0) / rho)
    lam = LON0 + math.atan2(x * math.sin(c), rho * math.cos(LAT0) * math.cos(c) - y * math.sin(LAT0) * math.sin(c))
    return (math.degrees(lam), math.degrees(phi))


def main():
    src = json.loads((GEO / "neuquen-province.geojson").read_text(encoding="utf8"))
    ring = src["features"][0]["geometry"]["coordinates"][0]
    metric = transform(lambda xs, ys, zs=None: tuple(zip(*(forward(x, y) for x, y in zip(xs, ys)))), Polygon(ring))
    buf = metric.buffer(BUFFER_M, quad_segs=8, join_style="round").simplify(100)
    assert buf.geom_type == "Polygon", buf.geom_type
    out = transform(lambda xs, ys, zs=None: tuple(zip(*(inverse(x, y) for x, y in zip(xs, ys)))), buf)
    coords = [[round(x, 3), round(y, 3)] for x, y in out.exterior.coords]
    doc = {
        "type": "FeatureCollection",
        "properties": {
            "source": "neuquen-province.geojson (Natural Earth 1:10m Admin 1, public domain) buffered by 10 km",
            "processing": "shapely buffer 10 km (round joins) in a Lambert azimuthal equal-area projection centred on the "
            "province, simplified at 100 m, outer ring only, coordinates rounded to 3 decimals; script: scripts/buffer_province.py",
        },
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Neuquén + 10 km"},
                "geometry": {"type": "Polygon", "coordinates": [coords]},
            }
        ],
    }
    (GEO / "neuquen-province-buffer-10km.geojson").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf8")
    print(len(coords), "vertices; area ratio", round(buf.area / metric.area, 4))


main()

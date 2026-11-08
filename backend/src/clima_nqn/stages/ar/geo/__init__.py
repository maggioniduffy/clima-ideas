"""Cordillera polygon: Neuquén province (Natural Earth 1:10m) clipped to ``lon <= -70.0``.

``clip_to_rectangle`` is a Sutherland-Hodgman clip against a convex rectangle (works for a non-convex subject;
if the result were several parts they would come joined by zero-width bridges along the clip edge, which the
even-odd point test of ``catalog.polygon_mask`` handles). ``build_cordillera`` regenerates ``cordillera.geojson``::

    uv run python -m clima_nqn.stages.ar.geo
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).parent
PROVINCE_FILE = HERE / "neuquen-province.geojson"
CORDILLERA_FILE = HERE / "cordillera.geojson"

# clip window (lon_min, lon_max, lat_min, lat_max): only the east edge cuts the province in practice
RECTANGLE = (-71.95, -70.0, -41.1, -36.0)
METHOD = "provincia de Neuquén (Natural Earth 1:10m) ∩ lon ≤ -70.0"

Point = tuple[float, float]


def _clip_edge(ring: list[Point], inside, intersect) -> list[Point]:
    out: list[Point] = []
    for i, cur in enumerate(ring):
        prev = ring[i - 1]
        if inside(cur):
            if not inside(prev):
                out.append(intersect(prev, cur))
            out.append(cur)
        elif inside(prev):
            out.append(intersect(prev, cur))
    return out


def clip_to_rectangle(
    ring: Sequence[Point], rect: tuple[float, float, float, float] = RECTANGLE
) -> list[Point]:
    """Clip an open (lon, lat) ring to ``rect = (lon_min, lon_max, lat_min, lat_max)``; [] if nothing remains."""
    x0, x1, y0, y1 = rect
    pts = [(float(x), float(y)) for x, y in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]

    def at_x(x):
        return lambda a, b: (x, a[1] + (x - a[0]) * (b[1] - a[1]) / (b[0] - a[0]))

    def at_y(y):
        return lambda a, b: (a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), y)

    for inside, intersect in (
        (lambda p: p[0] >= x0, at_x(x0)),
        (lambda p: p[0] <= x1, at_x(x1)),
        (lambda p: p[1] >= y0, at_y(y0)),
        (lambda p: p[1] <= y1, at_y(y1)),
    ):
        if not pts:
            break
        pts = _clip_edge(pts, inside, intersect)
    return pts


def ring_area(ring: Sequence[Point]) -> float:
    """Absolute shoelace area in square degrees."""
    n = len(ring)
    s = sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n))
    return abs(s) / 2


def province_ring(path: Path = PROVINCE_FILE) -> list[Point]:
    """Open outer ring (lon, lat) of the province polygon."""
    geo = json.loads(path.read_text(encoding="utf8"))
    ring = geo["features"][0]["geometry"]["coordinates"][0]
    return [(float(x), float(y)) for x, y in ring[:-1]]


def build_cordillera(province: Path = PROVINCE_FILE, out: Path = CORDILLERA_FILE) -> list[Point]:
    """Clip the province to ``RECTANGLE`` and write ``cordillera.geojson``; returns the open ring."""
    src = json.loads(province.read_text(encoding="utf8"))["properties"]
    ring = clip_to_rectangle(province_ring(province))
    if not ring:
        raise ValueError("the clipped polygon is empty")
    closed = [[round(x, 6), round(y, 6)] for x, y in [*ring, ring[0]]]
    doc = {
        "type": "FeatureCollection",
        "properties": {
            "source": src["source"],
            "license": src["license"],
            "method": METHOD,
            "clip_rectangle": list(RECTANGLE),
        },
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Cordillera de Neuquén (aprox., sin verificar)"},
                "geometry": {"type": "Polygon", "coordinates": [closed]},
            }
        ],
    }
    out.write_text(
        json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf8"
    )
    return [(x, y) for x, y in closed[:-1]]


def load_cordillera(path: Path = CORDILLERA_FILE) -> list[Point]:
    """Open (lon, lat) ring of the cordillera polygon from ``cordillera.geojson``."""
    geo = json.loads(path.read_text(encoding="utf8"))
    geom = geo["features"][0]["geometry"]
    if geom["type"] != "Polygon":
        raise ValueError(f"expected a Polygon in {path.name}, got {geom['type']}")
    return [(float(x), float(y)) for x, y in geom["coordinates"][0][:-1]]

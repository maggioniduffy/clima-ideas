import json

import numpy as np
import pytest

from clima_nqn.stages.ar import catalog, geo

WEB_GEO = geo.HERE.parents[4].parent / "web" / "public" / "geo"  # repo root / web/public/geo


def test_clip_square_by_half_plane():
    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    out = geo.clip_to_rectangle(square, (-10.0, 2.0, -10.0, 10.0))
    assert geo.ring_area(out) == pytest.approx(8.0)
    assert max(x for x, _ in out) == 2.0 and min(x for x, _ in out) == 0.0


def test_clip_fully_inside_and_fully_outside():
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert geo.ring_area(geo.clip_to_rectangle(square, (-1.0, 2.0, -1.0, 2.0))) == pytest.approx(
        1.0
    )
    assert geo.clip_to_rectangle(square, (5.0, 6.0, 5.0, 6.0)) == []


def test_clip_non_convex_l_shape():
    # L: 4x4 square minus the upper-right 2x2 block, area 12
    ell = [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)]
    out = geo.clip_to_rectangle(ell, (-1.0, 3.0, -1.0, 5.0))  # cuts x > 3: removes a 1x2 strip
    assert geo.ring_area(out) == pytest.approx(10.0)
    out = geo.clip_to_rectangle(ell, (-1.0, 5.0, -1.0, 3.0))  # cuts y > 3: removes a 2x1 strip
    assert geo.ring_area(out) == pytest.approx(10.0)
    out = geo.clip_to_rectangle(ell, (-1.0, 5.0, 1.0, 5.0))  # cuts y < 1: removes a 4x1 strip
    assert geo.ring_area(out) == pytest.approx(8.0)


def test_cordillera_file_is_reproducible(tmp_path):
    out = tmp_path / "cordillera.geojson"
    geo.build_cordillera(out=out)
    assert out.read_text(encoding="utf8") == geo.CORDILLERA_FILE.read_text(encoding="utf8")


def test_cordillera_metadata():
    props = json.loads(geo.CORDILLERA_FILE.read_text(encoding="utf8"))["properties"]
    assert "Natural Earth" in props["source"]
    assert props["method"] == "provincia de Neuquén (Natural Earth 1:10m) ∩ lon ≤ -70.0"
    assert "public domain" in props["license"].lower()


def test_cordillera_is_inside_province_and_rectangle_and_smaller():
    ring = catalog.CORDILLERA_POLYGON
    assert isinstance(ring, list) and all(len(v) == 2 for v in ring)
    assert all(lon <= -70.0 + 1e-9 for lon, _ in ring)
    x0, x1, y0, y1 = geo.RECTANGLE
    assert all(x0 - 1e-9 <= lon <= x1 + 1e-9 and y0 - 1e-9 <= lat <= y1 + 1e-9 for lon, lat in ring)
    province = geo.province_ring()
    prov = {(round(x, 6), round(y, 6)) for x, y in province}
    # every vertex is a province vertex or lies where the province crosses the clip edge (lon = -70.0 / -71.95)
    assert all(
        (round(lon, 6), round(lat, 6)) in prov or abs(lon - x1) < 1e-9 or abs(lon - x0) < 1e-9
        for lon, lat in ring
    )
    # on a fine mesh the cordillera is exactly the province part with lon <= -70.0 (within the rectangle)
    lat = np.arange(y0 + 0.0123, y1, 0.05)
    lon = np.arange(x0 + 0.0123, x1 + 0.5, 0.05)
    lon2d, lat2d = np.meshgrid(lon, lat)
    in_cord = catalog._points_in_polygon(lon2d, lat2d, ring)
    in_prov = catalog._points_in_polygon(lon2d, lat2d, province)
    assert not (in_cord & ~in_prov).any()
    assert not (in_cord & (lon2d > x1)).any()
    assert (in_prov & (lon2d < x1) & ~in_cord).sum() == 0
    rect_area = (x1 - x0) * (y1 - y0)
    assert 0 < geo.ring_area(ring) < rect_area
    assert geo.ring_area(ring) < geo.ring_area(province)


def test_cordillera_mask_has_fewer_cells_than_the_old_rectangle():
    lat = -41.125 + 0.25 * np.arange(22)  # 0.25 deg grid, centers off the rectangle edges
    lon = -72.125 + 0.25 * np.arange(10)
    new = int(catalog.polygon_mask(lat, lon).sum())
    old = int(catalog.polygon_mask(lat, lon, catalog.LEGACY_RECTANGLE).sum())
    assert 0 < new < old


def test_cordillera_over_the_bard_grid_counts():
    # BARD grid: 0.25 deg, lon on k*0.25, lat on k*0.25 (the old rectangle gave 140 cells)
    lat = np.arange(-43.0, -33.99, 0.25)
    lon = np.arange(-74.0, -65.99, 0.25)
    new = int(catalog.polygon_mask(lat, lon).sum())
    old = int(catalog.polygon_mask(lat, lon, catalog.LEGACY_RECTANGLE).sum())
    assert 0 < new < old


def test_web_copies_are_identical():
    for name in ("cordillera.geojson", "neuquen-province.geojson"):
        assert (WEB_GEO / name).read_bytes() == (geo.HERE / name).read_bytes(), name

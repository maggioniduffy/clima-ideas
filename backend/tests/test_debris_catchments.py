import math

import numpy as np
import pyarrow.parquet as pq
from affine import Affine
from shapely import wkb
from shapely.geometry import LineString, box

from clima_nqn.stages.debris import catchments as C

RES = 0.001
LON0, LAT0 = -68.0, -38.9
TRANSFORM = Affine(RES, 0, LON0, 0, -RES, LAT0)
NROWS, NCOLS, C0 = 40, 21, 10


def v_valley() -> np.ndarray:
    """Tilted V valley: strong lateral slope to column C0, gentle fall to the south (row increases)."""
    south = np.arange(NROWS)[::-1] * 0.2
    return np.add.outer(south, 5.0 * np.abs(np.arange(NCOLS) - C0)) + 1000.0


def row_lat(row: float) -> float:
    return LAT0 - RES * row


def _line(row: int) -> LineString:
    lat = row_lat(row + 0.5)
    return LineString([(LON0, lat), (LON0 + RES * NCOLS, lat)])


def test_cell_area_is_spherical():
    a = C.cell_area_m2(TRANSFORM, NROWS)
    expect = (RES * math.pi / 180) ** 2 * C.EARTH_RADIUS_M**2 * math.cos(math.radians(-38.9))
    assert abs(a[0] - expect) / expect < 0.01
    assert a[-1] < a[0]  # further south, |lat| grows, cos(lat) falls: cells get narrower


def test_v_valley_drains_to_line():
    out = C.delineate(
        v_valley(), TRANSFORM, [("route_x", _line(30))], min_area_km2=0.01, max_area_km2=50
    )
    assert len(out) == 1
    b = out[0]
    assert b.target == "route_x"
    # outlet near the valley axis and within 3 cells of the line (dilated by 1 cell)
    assert abs(b.outlet_lon - (LON0 + RES * (C0 + 0.5))) < 0.5 * RES
    assert abs(b.outlet_lat - row_lat(30.5)) <= 3 * RES
    # catchment = every cell north of the (dilated) line: whole width, rows 0..outlet_row
    out_row = round((LAT0 - b.outlet_lat) / RES - 0.5)
    cells = (out_row + 1) * NCOLS
    areas = C.cell_area_m2(TRANSFORM, NROWS)
    expect_km2 = sum(areas[r] * NCOLS for r in range(out_row + 1)) / 1e6
    assert cells > 0
    assert abs(b.area_km2 - expect_km2) / expect_km2 < 1e-6
    # relief: top row edge (col 0) minus outlet height
    assert b.relief_m > 5.0 * C0
    assert b.mean_slope_deg > 0
    # longest path runs from a corner/edge to the outlet: at least the axis length down to the outlet
    assert b.longest_flow_path_m >= out_row * 100 * 0.9
    assert b.geometry.area > 0
    assert b.geometry.is_valid


def test_area_filter_and_polygon_target():
    small = C.delineate(v_valley(), TRANSFORM, [("r", _line(30))], min_area_km2=0.01, max_area_km2=0.05)
    assert small == []  # catchment is ~0.25 km2 and exceeds max
    poly = box(LON0, row_lat(31), LON0 + RES * NCOLS, row_lat(29))  # polygon strip
    out = C.delineate(v_valley(), TRANSFORM, [("barrio", poly)], min_area_km2=0.01, max_area_km2=50)
    assert [b.target for b in out] == ["barrio"]


def test_two_targets_attribute_to_the_right_one():
    # line in the top half of the valley: its catchment is smaller; the lower line sees flow of the area
    # between them only once the upper line is crossed (road cells block labelling).
    out = C.delineate(
        v_valley(), TRANSFORM, [("upper", _line(10)), ("lower", _line(30))],
        min_area_km2=0.001, max_area_km2=50,
    )  # fmt: skip
    names = {b.target for b in out}
    assert {"upper", "lower"} <= names


def test_geoparquet_roundtrip(tmp_path):
    out = C.delineate(v_valley(), TRANSFORM, [("r", _line(30))], min_area_km2=0.01, max_area_km2=50)
    path = C.write_parquet(out, tmp_path / "c.parquet")
    table = pq.read_table(path)
    assert table.num_rows == 1
    row = table.to_pylist()[0]
    assert wkb.loads(row["geometry"]).equals(out[0].geometry)
    meta = table.schema.metadata
    assert b"geo" in meta and b"source" in meta and b"period" in meta
    assert row["target"] == "r"

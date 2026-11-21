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


def planar_dem(nrows=80, ncols=60) -> np.ndarray:
    """Exact tilted plane (south fall, tiny eastward rise): D8 routes parallel lines that never converge."""
    south = np.arange(nrows)[::-1] * 0.01
    return np.add.outer(south, np.arange(ncols) * 0.003) + 1000.0


def test_planar_terrain_gives_flagged_strips():
    line = LineString([(LON0, row_lat(70.5)), (LON0 + RES * 60, row_lat(70.5))])
    out = C.delineate(planar_dem(), TRANSFORM, [("r", line)], min_area_km2=0.0001, max_area_km2=50)
    assert len(out) >= 30
    assert all(b.planar_flow for b in out)
    assert all(b.rectangularity >= C.PLANAR_RECTANGULARITY and b.elongation >= C.PLANAR_ELONGATION for b in out)


def test_v_valley_catchment_is_not_flagged():
    out = C.delineate(v_valley(), TRANSFORM, [("route_x", _line(30))], min_area_km2=0.01, max_area_km2=50)
    assert len(out) == 1
    b = out[0]
    assert b.rectangularity >= C.PLANAR_RECTANGULARITY  # a box-shaped valley is rectangular...
    assert b.elongation < C.PLANAR_ELONGATION  # ...but not elongated, so it is not an artifact
    assert not b.planar_flow


def test_shape_metrics_use_a_metric_frame():
    # 0.01 deg of longitude at -38 deg is ~0.79 x the length of 0.01 deg of latitude
    rect, elong = C.shape_metrics(box(-69.0, -38.0, -68.99, -37.99))
    assert rect > 0.999 and abs(elong - 1 / math.cos(math.radians(-37.995))) < 0.01
    # an L shape is far from its bounding rectangle
    l_shape = box(0, 0, 3, 1).union(box(0, 0, 1, 3))
    assert C.shape_metrics(l_shape)[0] < 0.7
    assert not C.is_planar_flow(0.62, 8.0) and not C.is_planar_flow(0.95, 2.0) and C.is_planar_flow(0.9, 3.0)
    # stair-stepped diagonal strip: low rectangularity, extreme elongation
    assert C.is_planar_flow(0.4, 150.0) and not C.is_planar_flow(0.4, 14.0)


def test_parquet_stores_planar_fields(tmp_path):
    line = LineString([(LON0, row_lat(70.5)), (LON0 + RES * 60, row_lat(70.5))])
    out = C.delineate(planar_dem(), TRANSFORM, [("r", line)], min_area_km2=0.0001, max_area_km2=50)
    row = pq.read_table(C.write_parquet(out, tmp_path / "p.parquet")).to_pylist()[0]
    assert row["planar_flow"] is True and 0 < row["rectangularity"] <= 1 and row["elongation"] >= 3


def plane_with_gully(nrows=80, ncols=60, gc=30) -> np.ndarray:
    """Planar_dem with a 3-column V gully (2 m deep) incised along column ``gc``."""
    cut = np.maximum(0.0, 2.0 - 1.0 * np.abs(np.arange(ncols) - gc))
    return planar_dem(nrows, ncols) - cut


def _plane_line() -> LineString:
    return LineString([(LON0, row_lat(70.5)), (LON0 + RES * 60, row_lat(70.5))])


def test_plane_has_no_channel_outlets():
    out = C.delineate(planar_dem(), TRANSFORM, [("r", _plane_line())], min_area_km2=0.0001, max_area_km2=50)
    assert len(out) >= 30
    assert not any(b.channel for b in out)
    assert max(b.prominence for b in out) < 1.6  # no convergence along the front (low only at the DEM edge)
    mid = [b for b in out if 3 < (b.outlet_lon - LON0) / RES < 25]
    assert mid and all(abs(b.prominence - 1.0) < 0.1 for b in mid)
    assert all(b.dinf_acc_km2 > 0 for b in out)


def test_v_valley_outlet_is_a_channel():
    out = C.delineate(v_valley(), TRANSFORM, [("route_x", _line(30))], min_area_km2=0.01, max_area_km2=50)
    assert len(out) == 1
    b = out[0]
    assert b.channel and b.prominence >= 10 and b.dinf_acc_km2 >= C.CHANNEL_MIN_ACC_KM2
    assert set(b.prominence_by_r) == set(C.PROMINENCE_RADII_M)


def test_plane_with_one_gully_has_one_channel():
    out = C.delineate(
        plane_with_gully(), TRANSFORM, [("r", _plane_line())], min_area_km2=0.0001, max_area_km2=50
    )
    channels = [b for b in out if b.channel]
    assert len(channels) == 1
    assert abs(channels[0].outlet_lon - (LON0 + RES * 30.5)) <= 2 * RES
    assert channels[0].prominence >= 3 * C.CHANNEL_MIN_PROMINENCE


def test_channel_thresholds_are_parameters():
    kw = {"min_area_km2": 0.01, "max_area_km2": 50}
    strict = C.delineate(v_valley(), TRANSFORM, [("r", _line(30))], channel_min_prominence=1e9, **kw)
    assert not strict[0].channel
    big = C.delineate(v_valley(), TRANSFORM, [("r", _line(30))], channel_min_acc_km2=1e3, **kw)
    assert not big[0].channel


def test_parquet_stores_channel_fields(tmp_path):
    out = C.delineate(v_valley(), TRANSFORM, [("r", _line(30))], min_area_km2=0.01, max_area_km2=50)
    row = pq.read_table(C.write_parquet(out, tmp_path / "c.parquet")).to_pylist()[0]
    assert row["channel"] is True and row["dinf_acc_km2"] > 0 and row["prominence"] >= 3
    assert {"prominence_r250", "prominence_r500", "prominence_r1000", "planar_flow"} <= row.keys()

import json
import math

import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import box, shape
from typer.testing import CliRunner

from clima_nqn import cli
from clima_nqn.io import basins

R = basins.EARTH_RADIUS_KM


def sq(x, y):
    return box(x, y, x + 1, y + 1)


def hybas():
    """Chain A -> B -> C (outlet), branch D -> B, a separate chain E -> F, an endorheic G -> C."""
    rows = [
        # id, next_down, next_sink, sub_area, up_area, geometry
        (1, 2, 3, 10.0, 10.0, sq(0, 0)),  # A
        (2, 3, 3, 10.0, 30.0, sq(1, 0)),  # B
        (3, 0, 3, 10.0, 40.0, sq(2, 0)),  # C
        (4, 2, 3, 10.0, 10.0, sq(1, 1)),  # D
        (5, 6, 6, 10.0, 10.0, sq(10, 0)),  # E
        (6, 0, 6, 10.0, 20.0, sq(11, 0)),  # F
        (7, 3, 7, 10.0, 10.0, sq(2, 1)),  # G: endorheic, own sink, linked to C
    ]
    return pd.DataFrame(
        rows, columns=["HYBAS_ID", "NEXT_DOWN", "NEXT_SINK", "SUB_AREA", "UP_AREA", "geom"]
    )


def km2(w, h, lat_s):  # spherical area of a lon/lat rectangle
    return (
        R**2 * math.radians(w) * (math.sin(math.radians(lat_s + h)) - math.sin(math.radians(lat_s)))
    )


def test_upstream_ids_chain_and_branch():
    nd = {1: 2, 2: 3, 3: 0, 4: 2, 5: 6, 6: 0}
    assert basins.upstream_ids(nd, 3) == {1, 2, 3, 4}
    assert basins.upstream_ids(nd, 2) == {1, 2, 4}
    assert basins.upstream_ids(nd, 1) == {1}
    assert basins.upstream_ids(nd, 6) == {5, 6}


def test_delineate_picks_gauge_polygon_and_everything_upstream():
    b, info = basins.delineate_with_info(
        hybas(), {100: (2.5, 0.5), 101: (1.5, 0.5), 102: (11.5, 0.5)}
    )
    assert info[100]["gauge_hybas_id"] == 3 and info[100]["n_polygons"] == 4  # A B C D, G excluded
    assert info[100]["n_endorheic_excluded"] == 1 and info[100]["up_area_km2"] == 40.0
    assert shapely.equals(b[100], shapely.union_all([sq(0, 0), sq(1, 0), sq(2, 0), sq(1, 1)]))
    assert info[101]["n_polygons"] == 3 and b[101].area == pytest.approx(3.0)  # A B D
    assert info[102]["n_polygons"] == 2 and b[102].bounds == (10.0, 0.0, 12.0, 1.0)
    assert basins.delineate(hybas(), {100: (2.5, 0.5)})[100].area == pytest.approx(4.0)


def test_delineate_without_next_sink_follows_every_link():
    df = hybas().drop(columns="NEXT_SINK")
    _, info = basins.delineate_with_info(df, {100: (2.5, 0.5)})
    assert info[100]["n_polygons"] == 5 and info[100]["n_endorheic_excluded"] == 0


def test_delineate_point_outside_raises():
    with pytest.raises(ValueError, match="inside no HydroBASINS polygon"):
        basins.delineate(hybas(), {100: (50.0, 50.0)})


def test_delineate_reads_wkb_geoparquet(tmp_path):
    df = hybas()
    df["geom"] = shapely.to_wkb(df["geom"].to_numpy())
    path = tmp_path / "h.parquet"
    df.to_parquet(path)
    b = basins.delineate(path, {100: (2.5, 0.5)})
    assert b[100].area == pytest.approx(4.0)


def test_area_km2_matches_spherical_rectangle():
    g = box(-71.0, -38.0, -70.0, -37.0)
    assert basins.area_km2(g) == pytest.approx(km2(1, 1, -38.0), rel=1e-9)
    # a union of two equal-latitude squares is twice one square
    two = shapely.union_all([box(10, 40, 11, 41), box(11, 40, 12, 41)])
    assert basins.area_km2(two) == pytest.approx(km2(2, 1, 40.0), rel=1e-9)


def test_geojson_round_trip_and_metadata(tmp_path):
    b, info = basins.delineate_with_info(hybas(), {100: (2.5, 0.5)})
    b[100] = shapely.union_all([b[100], box(0.123456789, 5, 0.2, 5.1)]).buffer(0)
    path = basins.write_geojson(b, info, tmp_path / "g.geojson", {100: "Gauge"})
    doc = json.loads(path.read_text())
    assert doc["source"].startswith("HydroBASINS v1c level 12 (Lehner & Grill 2013")
    assert "extends past the gauge point" in doc["note"]
    props = doc["features"][0]["properties"]
    assert props["station_id"] == 100 and props["name"] == "Gauge"
    assert (
        props["n_polygons"] == 4 and props["gauge_hybas_id"] == 3 and props["up_area_km2"] == 40.0
    )
    assert props["area_km2"] > 0
    # coordinates rounded to 5 decimals
    coords = shapely.get_coordinates(shape(doc["features"][0]["geometry"]))
    assert np.allclose(coords, np.round(coords, 5))
    back = basins.read_geojson(path)
    assert set(back) == {100} and back[100].area == pytest.approx(b[100].area, rel=1e-4)
    assert basins.read_geojson_meta(path)["stations"][100]["name"] == "Gauge"


def test_write_geojson_simplify_is_recorded_and_bounded(tmp_path):
    b = {1: sq(0, 0)}
    info = {1: {"up_area_km2": 1.0, "n_polygons": 1, "gauge_hybas_id": 9}}
    path = basins.write_geojson(b, info, tmp_path / "g.geojson", simplify=0.001)
    assert json.loads(path.read_text())["simplify_tolerance_deg"] == 0.001
    with pytest.raises(ValueError, match="tolerance"):
        basins.write_geojson(b, info, tmp_path / "x.geojson", simplify=0.01)


def test_cli_flow_basins(tmp_path):
    df = hybas()
    df["geom"] = shapely.to_wkb(df["geom"].to_numpy())
    h = tmp_path / "h.parquet"
    df.to_parquet(h)
    fd = tmp_path / "flow"
    fd.mkdir()
    (fd / "stations.json").write_text(
        json.dumps(
            {"stations": [{"id": 100, "name": "G", "lat": 0.5, "lon": 2.5, "area_km2": 44000.0}]}
        )
    )
    out = tmp_path / "o.geojson"
    r = CliRunner().invoke(
        cli.app, ["flow", "basins", "--hybas", str(h), "--flow-dir", str(fd), "--out", str(out)]
    )
    assert r.exit_code == 0, r.output
    assert "SNIH 44000" in r.output and "4 polygons" in r.output
    assert set(basins.read_geojson(out)) == {100}

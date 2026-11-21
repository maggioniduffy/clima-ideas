import json
import math
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

from clima_nqn.layers import debris_catchments as dl
from clima_nqn.layers.manifest import load_manifest
from clima_nqn.stages.debris import catchments, scs


def _c(i, target, lon, area=1.0, slope=3.0, length=2000.0, geom=None, planar=None, channel=True):
    geom = geom if geom is not None else box(lon, -38.0, lon + 0.01, -37.99)
    lon = geom.bounds[0]  # distinct outlets so catchments are not deduplicated
    rect, elong = catchments.shape_metrics(geom)
    return catchments.Catchment(
        id=i,
        target=target,
        geometry=geom,
        area_km2=area,
        mean_slope_deg=slope,
        relief_m=40.0,
        longest_flow_path_m=length,
        outlet_lon=lon,
        outlet_lat=-38.0,
        rectangularity=rect,
        elongation=elong,
        planar_flow=catchments.is_planar_flow(rect, elong) if planar is None else planar,
        dinf_acc_km2=area,
        prominence=8.0 if channel else 1.0,
        channel=channel,
    )


@pytest.fixture
def parquets(tmp_path):
    a = catchments.write_parquet(
        [_c(0, "RP5", -69.0, 2.0), _c(1, "RP5", -69.1, 0.5)], tmp_path / "a.parquet"
    )
    # same catchment as a's first (duplicate) plus one new, with an id that collides with a's ids
    b = catchments.write_parquet(
        [_c(0, "RP5", -69.0, 2.0), _c(1, "Plottier", -68.9, 1.0)], tmp_path / "b.parquet"
    )
    return a, b


def test_idf_constant_matches_f33_table():
    rains, origin = dl.load_idf(Path("/nonexistent.parquet"))
    assert origin == "constant"
    assert len(rains) == 7 * 6
    assert rains[(10.0, 24.0)] == 78.7 and rains[(100.0, 0.5)] == 22.4 and rains[(2.0, 1.0)] == 10.4


def test_concatenate_dedupes_and_renumbers(parquets):
    rows, meta = dl.read_catchments(parquets)
    assert [r["id"] for r in rows] == [0, 1, 2]
    assert [r["target"] for r in rows] == ["RP5", "RP5", "Plottier"]
    assert rows[2]["source_id"] == 1 and rows[2]["source_file"] == "b.parquet"
    assert [f["n"] for f in meta["files"]] == [2, 1]


def test_peaks_match_design_peaks_and_scenarios_are_ordered():
    rains, _ = dl.load_idf(Path("/nonexistent.parquet"))
    row = {"area_km2": 2.0, "mean_slope_deg": 3.0, "longest_flow_path_m": 2000.0}
    out = dl.peaks_for(row, rains)
    slope_pct = math.tan(math.radians(3.0)) * 100
    ref = {dp.return_period: dp for dp in scs.design_peaks(2.0, 85.0, 2000.0, slope_pct, rains)}
    assert out["peak_m3s"]["hsg-c"] == [round(ref[t].peak_m3s, 3) for t in dl.RETURN_PERIODS]
    assert out["critical_duration_h"]["hsg-c"] == [
        ref[t].critical_duration_h for t in dl.RETURN_PERIODS
    ]
    for i in range(len(dl.RETURN_PERIODS)):  # higher CN -> higher peak; peak grows with T
        assert (
            out["peak_m3s"]["hsg-b"][i]
            <= out["peak_m3s"]["hsg-c"][i]
            <= out["peak_m3s"]["hsg-d"][i]
        )
    c = out["peak_m3s"]["hsg-c"]
    assert c == sorted(c)


def test_build_writes_contract(parquets, tmp_path):
    out = dl.build(parquets, tmp_path / "debris-catchments")
    m = load_manifest(out / "manifest.json")
    assert m.id == "debris-catchments" and m.kind == "polygons"
    assert m.files == ["catchments.geojson", "peaks.json"]  # default file = geometry
    assert m.period == "2000-07-01/2025-06-30" and "IMERG" in m.source and "TR-55" in m.source
    for f in m.files:
        assert (out / f).is_file()
    gj = json.loads((out / "catchments.geojson").read_text(encoding="utf-8"))
    pk = json.loads((out / "peaks.json").read_text(encoding="utf-8"))
    assert len(gj["features"]) == 3 == pk["n_catchments"]
    assert {str(f["properties"]["id"]) for f in gj["features"]} == set(pk["catchments"])
    assert pk["return_periods"] == [2, 5, 10, 25, 50, 100]
    assert [s["cn"] for s in pk["cn"]["scenarios"]] == [77, 85, 88]
    assert pk["cn"]["citation"] == "sin verificar" and "no medidos" in pk["cn"]["label"]
    assert "sin verificar" in pk["rain"]["note"] and "sin corrección de sesgo" in pk["rain"]["note"]
    assert pk["rain"]["period"].startswith("2000/01")
    assert any("No es un sistema de alerta" in c for c in pk["caveats"])
    one = pk["catchments"]["0"]
    assert (
        set(one["peak_m3s"]) == {"hsg-b", "hsg-c", "hsg-d"} and len(one["peak_m3s"]["hsg-c"]) == 6
    )
    assert gj["features"][0]["geometry"]["type"] == "Polygon"


def test_build_rejects_empty_input(tmp_path):
    p = catchments.write_parquet([], tmp_path / "e.parquet")
    with pytest.raises(ValueError):
        dl.build([p], tmp_path / "out")


def test_planar_flag_computed_for_old_parquet_and_counted(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    strip = box(-69.0, -38.0, -68.99, -37.9)  # long thin rectangle -> planar flow
    blob = box(-69.2, -38.0, -69.19, -37.99)  # square -> not flagged
    p = catchments.write_parquet([_c(0, "RP7", 0, geom=strip), _c(1, "RP7", 0, geom=blob)], tmp_path / "n.parquet")
    t = pq.read_table(p)
    drop = ("rectangularity", "elongation", "planar_flow", "dinf_acc_km2", "prominence", "channel")
    old = pa.table({n: t[n] for n in t.column_names if n not in drop and not n.startswith("prominence_r")})
    old = old.replace_schema_metadata(t.schema.metadata)
    pq.write_table(old, tmp_path / "old.parquet")
    rows, _ = dl.read_catchments([tmp_path / "old.parquet"])
    assert [r["planar_flow"] for r in rows] == [True, False]
    out = dl.build([tmp_path / "old.parquet"], tmp_path / "o")
    pk = json.loads((out / "peaks.json").read_text(encoding="utf-8"))
    assert pk["planar_flow"]["n_excluded"] == 1 and pk["n_ranked"] == 1
    assert pk["planar_flow"]["criterion"] == "shape" and pk["channel"]["method"] == "shape"
    assert pk["channel"]["shape_rule"]["min_rectangularity"] == 0.85 and "sin verificar" in pk["planar_flow"]["note"]
    gj = json.loads((out / "catchments.geojson").read_text(encoding="utf-8"))
    assert [f["properties"]["planar_flow"] for f in gj["features"]] == [True, False]


def test_overlap_marks_the_smaller_catchment_of_another_target(tmp_path):
    big = box(-69.0, -38.0, -68.95, -37.95)
    inside = box(-68.99, -37.99, -68.97, -37.97)  # fully inside big, other target -> excluded from ranking
    same_target = box(-68.99, -37.99, -68.96, -37.97)
    apart = box(-68.5, -38.0, -68.45, -37.95)
    p = catchments.write_parquet(
        [_c(0, "RP7", 0, area=9, geom=big), _c(1, "Centenario", 0, area=1, geom=inside), _c(2, "RP7", 0, area=1, geom=apart)],
        tmp_path / "a.parquet",
    )
    q = catchments.write_parquet([_c(0, "RP7", 0, area=1, geom=same_target)], tmp_path / "b.parquet")
    rows, _ = dl.read_catchments([p, q])
    assert [r["overlaps_id"] for r in rows] == [None, 0, None, None]  # same target is not an overlap
    out = dl.build([p, q], tmp_path / "o")
    pk = json.loads((out / "peaks.json").read_text(encoding="utf-8"))
    assert pk["overlap"]["n_excluded"] == 1 and pk["n_ranked"] == 3 and pk["n_catchments"] == 4
    gj = json.loads((out / "catchments.geojson").read_text(encoding="utf-8"))
    assert gj["features"][1]["properties"]["overlaps_id"] == 0 and gj["features"][0]["properties"]["overlaps_id"] is None
    assert "1" in pk["catchments"]  # the excluded one keeps its peaks (still clickable)


def test_ranking_needs_channel_and_non_planar_shape(tmp_path):
    strip = box(-69.0, -38.0, -68.99, -37.9)  # converges (channel) but is a band: shape rule says planar
    blob = box(-69.2, -38.0, -69.19, -37.99)  # compact, but the front shows no convergence
    gully = Polygon([(-69.3, -38.0), (-69.28, -37.99), (-69.29, -37.97), (-69.31, -37.985)])  # compact, converges
    p = catchments.write_parquet(
        [
            _c(0, "RP7", 0, geom=strip, channel=True),
            _c(1, "RP7", 0, geom=blob, channel=False),
            _c(2, "RP7", 0, geom=gully, channel=True),
        ],
        tmp_path / "c.parquet",
    )
    rows, _ = dl.read_catchments([p])
    assert [r["shape_planar"] for r in rows] == [True, False, False]
    assert [r["planar_flow"] for r in rows] == [True, True, False]
    out = dl.build([p], tmp_path / "o")
    pk = json.loads((out / "peaks.json").read_text(encoding="utf-8"))
    assert pk["channel"]["method"] == "dinf" and pk["channel"]["n_channel"] == 2 and pk["n_ranked"] == 1
    assert pk["channel"]["min_prominence"] == catchments.CHANNEL_MIN_PROMINENCE and "sin verificar" in pk["channel"]["note"]
    assert pk["planar_flow"]["criterion"] == "channel+shape" and pk["planar_flow"]["n_excluded"] == 2
    gj = json.loads((out / "catchments.geojson").read_text(encoding="utf-8"))
    a, b, c = (f["properties"] for f in gj["features"])
    assert a["planar_flow"] is True and a["shape_planar"] is True and a["prominence"] == 8.0 and a["dinf_acc_km2"] == 1.0
    assert b["planar_flow"] is True and b["prominence"] == 1.0
    assert c["planar_flow"] is False

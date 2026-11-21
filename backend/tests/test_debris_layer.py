import json
import math
from pathlib import Path

import pytest
from shapely.geometry import box

from clima_nqn.layers import debris_catchments as dl
from clima_nqn.layers.manifest import load_manifest
from clima_nqn.stages.debris import catchments, scs


def _c(i, target, lon, area=1.0, slope=3.0, length=2000.0):
    return catchments.Catchment(
        id=i,
        target=target,
        geometry=box(lon, -38.0, lon + 0.01, -37.99),
        area_km2=area,
        mean_slope_deg=slope,
        relief_m=40.0,
        longest_flow_path_m=length,
        outlet_lon=lon,
        outlet_lat=-38.0,
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

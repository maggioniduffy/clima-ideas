import itertools
import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from clima_nqn.api.app import create_app
from clima_nqn.layers import convection_idf as cl
from clima_nqn.layers.manifest import load_manifest
from clima_nqn.stages.convection import idf

LATS = np.array([-39.15, -39.05, -38.95, -38.85, -38.75], dtype="float32")
LONS = np.array([-68.35, -68.25, -68.15, -68.05, -67.95], dtype="float32")
STORM = (pd.Timestamp("2001-04-06 00:00"), pd.Timestamp("2001-04-08 00:00"))
COMPARE = (pd.Timestamp("2001-04-06 12:00"), pd.Timestamp("2001-04-07 12:00"))


@pytest.fixture(scope="module")
def zarr_path(tmp_path_factory):
    """Six complete hydrological years (2000/01-2005/06) of small random rain plus a known storm in 2001."""
    path = tmp_path_factory.mktemp("imerg") / "neuquen.zarr"
    times = pd.date_range("2000-07-01", "2006-07-01", freq="30min", inclusive="left")
    rng = np.random.default_rng(7)
    data = rng.exponential(0.05, size=(len(times), len(LATS), len(LONS))).astype("float32")
    # storm: 1 mm/h (0.5 mm per step) at the Neuquén cell for the whole comparison window, plus a dry spell
    at = (times >= COMPARE[0]) & (times < COMPARE[1])
    data[at, 2, 2] = 1.0
    data[(times >= STORM[0]) & (times < COMPARE[0]), 2, 2] = 0.0
    ds = xr.Dataset(
        {"precipitation": (("time", "lat", "lon"), data)},
        coords={"time": times, "lat": LATS, "lon": LONS},
        attrs={"doi": "https://doi.org/10.5067/GPM/IMERG/3B-HH/07", "license": "CC BY 4.0"},
    )
    ds.to_zarr(path, consolidated=False)
    return path


@pytest.fixture(scope="module")
def layer(zarr_path, tmp_path_factory):
    out = tmp_path_factory.mktemp("processed") / cl.LAYER_ID
    cl.build(zarr_path, out, n_boot=40, storm=STORM, compare=COMPARE)
    return out


def test_manifest_contract(layer):
    m = load_manifest(layer / "manifest.json")
    assert m.id == "convection-idf" and m.kind == "raster-frames"
    assert m.source == "GPM IMERG Final V07 (NASA GES DISC)"
    assert m.period == "2000-07-01/2006-06-30"
    assert m.files[0] == "idf.json"  # default file of the API
    for f in m.files:
        assert (layer / f).is_file()


def test_idf_json_scenarios_and_labels(layer):
    d = json.loads((layer / "idf.json").read_text(encoding="utf-8"))
    assert d["label"] == "IDF solo con IMERG, sin corrección de sesgo"
    assert d["period"] == "2000/01–2005/06 (años julio–junio)"
    assert d["n_years"] == 6 and d["extrapolation_above_t"] == 12
    assert d["cell"] == {"lat": -38.95, "lon": -68.15}
    assert d["return_periods"] == [2, 5, 10, 25, 50, 100]
    assert [s["id"] for s in d["scenarios"]] == ["main", "div-0.92", "div-0.67"]
    main, s92, s67 = d["scenarios"]
    assert len(main["gev"]) == len(main["gumbel"]) == 6 * len(d["durations_h"])
    assert "gumbel" not in s92 and "gumbel" not in s67
    key = lambda s, dur, t: next(r for r in s["gev"] if r["d"] == dur and r["t"] == t)
    base = key(main, 24.0, 10.0)
    assert key(s92, 24.0, 10.0)["depth_mm"] == pytest.approx(base["depth_mm"] / 0.92, rel=5e-3)
    assert key(s67, 24.0, 10.0)["depth_mm"] == pytest.approx(base["depth_mm"] / 0.67, rel=5e-3)
    assert base["intensity_mm_h"] == pytest.approx(base["depth_mm"] / 24, rel=1e-2)
    assert base["depth_lo"] <= base["depth_mm"] <= base["depth_hi"]
    # T > 2 * n_years is flagged as extrapolation (n = 6: T 25, 50, 100; T 10 is not)
    assert key(main, 1.0, 10.0)["extrapolated"] is False
    assert key(main, 1.0, 25.0)["extrapolated"] is True


def test_idf_matches_stage_table(zarr_path, layer):
    """The layer's main curve is the stage's `idf_table` of the nearest cell, with no correction."""
    ds = xr.open_zarr(zarr_path, consolidated=False)
    series = ds.precipitation.isel(lat=2, lon=2).load().to_series() * idf.STEP_H
    table = idf.idf_table(idf.annual_maxima(series), n_boot=40)
    row = table[
        (table.method == "gev_lmom") & (table.return_period_yr == 5) & (table.duration_h == 6)
    ].iloc[0]
    d = json.loads((layer / "idf.json").read_text(encoding="utf-8"))
    got = next(r for r in d["scenarios"][0]["gev"] if r["d"] == 6.0 and r["t"] == 5.0)
    assert got["depth_mm"] == pytest.approx(row.depth_mm, abs=0.01)
    assert got["depth_lo"] == pytest.approx(row.ci_low, abs=0.01)


def test_frames_follow_the_ar_contract(layer):
    index = json.loads((layer / "frames/index.json").read_text(encoding="utf-8"))
    g = index["grid"]
    assert (g["ny"], g["nx"]) == (5, 5)
    assert (g["lat_min"], g["lat_max"], g["lon_min"], g["lon_max"]) == (
        -39.15,
        -38.75,
        -68.35,
        -67.95,
    )
    assert index["units"] == "mm/h" and index["step_hours"] == 0.5
    entry = index["events"][cl.FRAME_SET]
    assert entry["start"] == "2001-04-06T00:00:00Z" and entry["n_frames"] == 96
    raw = np.fromfile(layer / "frames" / f"{cl.FRAME_SET}.bin", dtype="<f4")
    assert raw.size == 96 * 5 * 5
    frames = raw.reshape(96, 5, 5)
    # row 0 = south: the Neuquén cell (lat -38.95) is row 2, column 2 (lon -68.15)
    assert frames[0, 2, 2] == 0.0 and frames[24, 2, 2] == 1.0 and frames[71, 2, 2] == 1.0
    assert frames[72, 2, 2] != 1.0
    assert entry["vmax"] == pytest.approx(float(np.nanmax(frames)), abs=1e-3)


def test_replay_cumulative_and_station_reference(layer):
    r = json.loads((layer / "replay.json").read_text(encoding="utf-8"))
    assert r["cell"] == {"lat": -38.95, "lon": -68.15, "row": 2, "col": 2}
    c = r["compare"]
    assert c["start"] == "2001-04-06T12:00:00Z" and c["end"] == "2001-04-07T12:00:00Z"
    assert c["imerg_mm"] == 24.0  # 48 steps of 1 mm/h * 0.5 h
    st = c["station"]
    assert st["value_mm"] == 118.0 and "NOAA ISD" in st["source"] and "877150" in st["id"]
    cum = r["cumulative"]["mm"]
    assert cum[0] == 0 and cum[24] == 12.0 and len(cum) == 1 + 72  # to the replay end (exclusive)
    assert all(b >= a for a, b in itertools.pairwise(cum))  # monotone


def test_station_reference_can_be_overridden(zarr_path, tmp_path):
    out = tmp_path / "l"
    cl.build(zarr_path, out, n_boot=10, storm=STORM, compare=COMPARE, station={"value_mm": 50.0})
    r = json.loads((out / "replay.json").read_text(encoding="utf-8"))
    assert r["compare"]["station"]["value_mm"] == 50.0


def test_incomplete_frames_raise(zarr_path, tmp_path):
    late = (pd.Timestamp("2007-01-01"), pd.Timestamp("2007-01-02"))
    with pytest.raises(ValueError, match="incomplete"):
        cl.build(zarr_path, tmp_path / "l", n_boot=10, storm=late, compare=late)


def test_compare_window_must_be_inside_replay(zarr_path, tmp_path):
    with pytest.raises(ValueError, match="inside"):
        cl.build(
            zarr_path,
            tmp_path / "l",
            n_boot=10,
            storm=STORM,
            compare=(pd.Timestamp("2001-04-01"), pd.Timestamp("2001-04-07")),
        )


def test_api_serves_the_layer(layer):
    client = TestClient(create_app(layer.parent))
    assert client.get("/layers").json()[0]["id"] == "convection-idf"
    assert client.get("/layers/convection-idf/data").json()["n_years"] == 6
    r = client.get(f"/layers/convection-idf/frames/{cl.FRAME_SET}")
    assert r.status_code == 200 and len(r.content) == 96 * 25 * 4
    assert (
        client.get("/layers/convection-idf/data", params={"file": "replay.json"}).status_code == 200
    )

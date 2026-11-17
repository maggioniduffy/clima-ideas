import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from typer.testing import CliRunner

from clima_nqn import cli
from clima_nqn.io import dem, forcing
from clima_nqn.stages.flood import hydro_models as hm
from clima_nqn.stages.flood import lstm
from clima_nqn.stages.flood import streamflow_eval as ev
from test_hydro_models import forcing as synth_forcing
from test_streamflow_eval import PARAMS, station_basin

UNIFORM = np.arange(101, dtype=float)


# --- layer elevations ---------------------------------------------------------------------------


def test_layer_elevations_uniform_curve():
    assert hm.layer_elevations(UNIFORM, 5).tolist() == [10, 30, 50, 70, 90]
    assert hm.layer_elevations(UNIFORM, 1).tolist() == [50]


def test_layer_elevations_n3_uses_34_33_33_split():
    # nn = 34 -> H[int(0 + 17)] = 17; nn = 33 -> H[int(34 + 16.5)] = 50; H[int(67 + 16.5)] = 83
    assert hm.layer_elevations(UNIFORM, 3).tolist() == [17, 50, 83]


def test_layer_elevations_validates():
    with pytest.raises(ValueError):
        hm.layer_elevations(np.arange(10.0), 3)
    with pytest.raises(ValueError):
        hm.layer_elevations(UNIFORM, 0)


# --- extrapolation ------------------------------------------------------------------------------


def test_extrapolate_mean_equals_input_and_gradients():
    rng = np.random.default_rng(1)
    p = np.where(rng.random(200) < 0.5, rng.gamma(1.0, 5.0, 200), 0.0)
    t = rng.normal(5, 3, 200)
    z = [500.0, 1500.0, 2500.0]
    pl, tl = hm.extrapolate_layers(p, t, z, 1500.0, grad_p=0.0005, grad_t=0.006)
    np.testing.assert_allclose(pl.mean(axis=0), p, atol=1e-12)
    assert np.all(pl[2][p > 0] > pl[0][p > 0])
    assert np.all(pl[:, p == 0] == 0.0) and not np.isnan(pl).any()
    np.testing.assert_allclose(tl[0], t + 1000 * 0.006)
    np.testing.assert_allclose(tl[2], t - 1000 * 0.006)
    assert np.all(tl[2] < tl[0])


def test_extrapolate_caps_precip_gradient_at_threshold():
    p = np.array([10.0])
    t = np.array([0.0])
    # layers above the 4000 m threshold get the same factor
    pl, _ = hm.extrapolate_layers(p, t, [3000.0, 4500.0, 6000.0], 2000.0, grad_p=0.001)
    assert pl[1, 0] == pytest.approx(pl[2, 0])
    f = np.exp(0.001 * np.array([1000.0, 2000.0, 2000.0]))
    np.testing.assert_allclose(pl[:, 0], 10.0 * f / f.mean())
    # forcing already above the threshold: unchanged
    pl2, _ = hm.extrapolate_layers(p, t, [3000.0, 5000.0], 4500.0, grad_p=0.001)
    f2 = np.exp(0.001 * np.array([3000.0 - 4000.0, 0.0]))
    np.testing.assert_allclose(pl2[:, 0], 10.0 * f2 / f2.mean())


def test_extrapolate_single_layer_is_identity():
    p, t, _ = synth_forcing(50)
    pl, tl = hm.extrapolate_layers(p, t, [1234.0], 2000.0)
    np.testing.assert_array_equal(pl[0], p)
    np.testing.assert_array_equal(tl[0], t)


# --- equivalence with the single layer model ----------------------------------------------------


def test_single_layer_reproduces_current_simulate_and_cemaneige():
    p, t, e = synth_forcing(1200)
    spec = hm.LayerSpec((2000.0,), 2000.0)
    a = hm.simulate(PARAMS, p, t, e)
    b = hm.simulate(PARAMS, p, t, e, layers=spec)
    for x, y in zip(a, b, strict=True):
        np.testing.assert_array_equal(x, y)
    s = hm.cemaneige(p, t, PARAMS.ctg, PARAMS.kf)
    liquid, solid, melt, pack = hm.cemaneige_layers(p[None], t[None], PARAMS.ctg, PARAMS.kf)
    np.testing.assert_array_equal(liquid, s.liquid)
    np.testing.assert_array_equal(solid[0], s.solid)
    np.testing.assert_array_equal(melt[0], s.melt)
    np.testing.assert_array_equal(pack[0], s.snowpack)


def test_snow_batch_per_column_matches_shared_series():
    p, t, _ = synth_forcing(800)
    solid = p * hm._solid_fraction(t)
    ctg, kf = np.array([0.0, 0.3, 0.8]), np.array([1.0, 3.0, 6.0])
    m1, k1 = hm._snow_batch(solid, t, ctg, kf, 50.0)
    m2, k2 = hm._snow_batch(
        np.repeat(solid[:, None], 3, 1), np.repeat(t[:, None], 3, 1), ctg, kf, 50.0
    )
    np.testing.assert_array_equal(m1, m2)
    np.testing.assert_array_equal(k1, k2)


def cold_series(n=365, z=(500.0, 1500.0, 2500.0, 3500.0), z_in=2000.0):
    t = np.arange(n)
    temp = 1.5 + 0.5 * np.sin(2 * np.pi * t / 30)  # hovers around +1..+2 degC at z_in
    precip = np.where(t % 3 == 0, 6.0, 0.0)
    return precip, temp, hm.LayerSpec(z, z_in)


def test_highest_layer_accumulates_snow_first():
    p, t, spec = cold_series()
    res = hm.simulate_layers(PARAMS, p, t, np.full(p.size, 0.5), spec)
    first = [int(np.argmax(res.snowpack[i] > 0)) if (res.snowpack[i] > 0).any() else 10**6
             for i in range(4)]  # fmt: skip
    assert first[3] <= first[2] <= first[1] <= first[0]
    mid = 100
    assert res.snowpack[3, mid] > res.snowpack[0, mid]
    assert res.snowpack[0, mid] < 1e-6 < res.snowpack[3, mid]
    np.testing.assert_allclose(res.sim.snowpack, res.snowpack.mean(axis=0), atol=1e-12)


def test_batched_layers_match_per_parameter_loop():
    p, t, e = synth_forcing(900)
    spec = hm.LayerSpec((1000.0, 2000.0, 3000.0), 2000.0)
    sets = np.array([[300.0, -1.0, 80.0, 1.5, 0.1, 3.0], [800.0, 0.5, 200.0, 3.0, 0.6, 5.0]])
    batch = hm._simulate_batch(sets, p, t, e, 0.3, 0.5, spec)
    for j in range(2):
        one = hm.simulate(hm.Params(*sets[j]), p, t, e, layers=spec)
        np.testing.assert_allclose(batch.q[j], one.q, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(batch.snowpack[j], one.snowpack, rtol=1e-12, atol=1e-12)


def test_calibrate_with_layers_runs():
    p, t, e = synth_forcing(900)
    spec = hm.LayerSpec((1000.0, 2000.0, 3000.0), 2000.0)
    q = hm.simulate(PARAMS, p, t, e, layers=spec).q
    cal = hm.calibrate(p, t, e, q, warmup=100, maxiter=3, popsize=4, layers=spec)
    assert np.isfinite(cal.kge)


# --- hypsometry ---------------------------------------------------------------------------------


def test_weighted_quantiles_hand_cases():
    v = np.array([3.0, 1.0, 2.0, 4.0])
    q = forcing.weighted_quantiles(v, np.ones(4), np.array([0.0, 0.5, 1.0]))
    assert q.tolist() == [1.0, 2.5, 4.0]
    # all the weight on the highest value pulls the median to it
    q = forcing.weighted_quantiles(v, np.array([0.0001, 0.0001, 0.0001, 1.0]), np.array([0.5]))
    assert q[0] == pytest.approx(4.0, abs=0.01)


def write_tile(dem_dir, lat, lon, fn):
    n = 120
    data = fn(np.linspace(lat + 1, lat, n)[:, None], np.linspace(lon, lon + 1, n)[None, :])
    dem_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        dem_dir / f"{dem.tile_name(lat, lon)}.tif", "w", driver="GTiff", height=n, width=n,
        count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(lon, lat + 1, 1 / n, 1 / n),
    ) as ds:  # fmt: skip
        ds.write(np.broadcast_to(data, (n, n)).astype("float32"), 1)


BOX = (-37.9, -37.1, -71.0, -70.2)


def test_dem_hypsometry_and_build_static_adds_it(tmp_path):
    dem_dir = tmp_path / "dem"
    write_tile(dem_dir, -38, -71, lambda la, lo: 1000 + 2000 * (lo + 71))
    h = forcing.dem_hypsometry(dem_dir, BOX, step=1 / 120)
    assert h.shape == (101,) and np.all(np.diff(h) >= 0)
    assert h[0] == pytest.approx(1000, abs=30) and h[100] == pytest.approx(2600, abs=30)
    assert h[50] == pytest.approx(1800, abs=40)
    # an old entry without hypso_m keeps its fields (also unknown ones) and gets the curve
    out = tmp_path / "forcing.parquet"
    spath = forcing.static_path(out)
    first = forcing.build_static(out, dem_dir, [1], {1: BOX}, step=1 / 120)
    doc = json.loads(first.read_text())
    entry = doc["basins"]["1"]
    entry.pop("hypso_m")
    entry["era5_orog_m"] = 1621.7
    entry["elev_mean_m"] = 1234.5  # stored value must not be recomputed
    spath.write_text(json.dumps(doc))
    forcing.build_static(out, dem_dir, [1], {1: BOX}, step=1 / 120)
    new = json.loads(spath.read_text())["basins"]["1"]
    assert len(new["hypso_m"]) == 101 and new["era5_orog_m"] == 1621.7
    assert new["elev_mean_m"] == 1234.5


def test_dem_hypsometry_missing_tile_gives_nan_and_warns(tmp_path):
    with pytest.warns(UserWarning, match="missing DEM tile"):
        h = forcing.dem_hypsometry(tmp_path / "none", BOX)
    assert h.shape == (101,) and np.isnan(h).all()
    with pytest.warns(UserWarning):
        path = forcing.build_static(tmp_path / "f.parquet", tmp_path / "none", [1], {1: BOX})
    assert json.loads(path.read_text())["basins"]["1"]["hypso_m"] is None


# --- streamflow_eval ----------------------------------------------------------------------------

FAST = {"seeds": (0,), "maxiter": 2, "popsize": 4}


def test_gr4j_baseline_layers_records_and_validates():
    b = station_basin(start="2002-01-01", end="2012-12-31")
    hypso = np.linspace(1000, 3000, 101)
    g = ev.gr4j_baseline(b, "default", n_layers=3, hypso=hypso, z_inputs=2000.0, **FAST)
    assert g["n_layers"] == 3 and len(g["z_layers"]) == 3 and g["z_inputs"] == 2000.0
    assert g["grad_p"] == hm.GRAD_P and g["grad_t"] == hm.GRAD_T
    g1 = ev.gr4j_baseline(b, "default", **FAST)
    assert g1["n_layers"] == 1 and g1["grad_p"] is None
    with pytest.raises(ValueError, match="need hypso"):
        ev.gr4j_baseline(b, "default", n_layers=3, **FAST)


def test_z_input_for_sources():
    assert ev.z_input_for({"era5_orog_m": 1600.0, "elev_mean_m": 1800.0}) == (1600.0, "era5_orog")
    assert ev.z_input_for({"elev_mean_m": 1800.0}) == (1800.0, "dem_mean")
    assert ev.z_input_for({"era5_orog_m": 1600.0, "elev_mean_m": 1800.0}, "dem_mean") == (
        1800.0,
        "dem_mean",
    )


def test_gr4j_bands_smoke_and_cli(tmp_path, monkeypatch):
    b = station_basin("12004", "2002-01-01", "2017-12-31")
    static = {"12004": {"elev_mean_m": 1800.0, "hypso_m": np.linspace(1000, 3000, 101).tolist()}}
    res = ev.gr4j_bands([b], static, "default", (1, 3), maxiter=2, popsize=4, seeds=(0,))
    cell = res["stations"]["12004"]
    assert set(cell["layers"]) == {"1", "3"} and cell["n"] > 0
    for sc in cell["layers"].values():
        assert {"nse", "kge", "nse_log", "excl_2023"} <= set(sc)
    assert res["z_inputs_source"] == {"12004": "dem_mean"}
    assert "12004" in ev.bands_table(res)

    fpath = tmp_path / "forcing.parquet"
    fpath.write_text("x")
    fpath.with_suffix(".static.json").write_text(json.dumps({"basins": static}))
    monkeypatch.setattr(lstm, "neuquen_basins", lambda *a, **k: ([b], {}))
    out = tmp_path / "o.json"
    r = CliRunner().invoke(
        cli.app,
        ["flow", "gr4j-bands", "--forcing", str(fpath), "--layers", "1", "--layers", "2",
         "--seeds", "0", "--maxiter", "2", "--popsize", "4", "--out", str(out)],
    )  # fmt: skip
    assert r.exit_code == 0, r.output
    assert json.loads(out.read_text())["layer_counts"] == [1, 2]
    assert "12004" in r.output

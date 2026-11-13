import json
import sys

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from clima_nqn import cli
from clima_nqn.stages.flood import lstm


def synth_basin(
    bid="b1", start="2000-01-01", end="2012-12-31", seed=0, group="neuquen", extra=None
):
    dates = pd.date_range(start, end, freq="D")
    n = len(dates)
    rng = np.random.default_rng(seed)
    doy = dates.day_of_year.to_numpy()
    precip = rng.gamma(0.6, 6.0, n) * (rng.random(n) < 0.4)
    tmean = 8 + 8 * np.cos(2 * np.pi * doy / 365.25) + rng.normal(0, 1, n)
    pet = np.clip(1 + 0.1 * tmean, 0, None)
    q = 0.5 * precip + 0.3 * np.r_[0.0, precip[:-1]]
    x = np.stack([precip, tmean, tmean - 5, tmean + 5, pet], axis=1)
    if extra:
        extra(x, q, dates)
    return lstm.Basin(
        id=bid, dates=dates, x=x, q=q, static=np.array([np.log(1000.0), 1500.0, -38.0]), group=group
    )


# --- splits ------------------------------------------------------------------------------------


def test_hydrological_year_starts_in_april():
    d = pd.DatetimeIndex(["2006-03-31", "2006-04-01", "2007-01-15"])
    assert list(lstm.hydro_year(d)) == [2005, 2006, 2006]


def test_default_split_labels():
    d = pd.DatetimeIndex(
        ["1980-03-31", "1980-04-01", "2007-03-31", "2007-04-01", "2014-03-31", "2014-04-01",
         "2026-04-01"]
    )  # fmt: skip
    lab = lstm.split_labels(d, "default")
    names = [lstm.PART_NAMES[i] for i in lab]
    assert names == ["none", "train", "train", "val", "val", "test", "none"]


def test_alt_split_labels():
    d = pd.DatetimeIndex(["1980-04-01", "1992-03-31", "1992-04-01", "1999-03-31", "1999-04-01"])
    names = [lstm.PART_NAMES[i] for i in lstm.split_labels(d, "alt")]
    assert names == ["test", "test", "val", "val", "train"]


def test_unknown_split_rejected():
    with pytest.raises(ValueError, match="split"):
        lstm.split_labels(pd.DatetimeIndex(["2000-01-01"]), "nope")


# --- normalization -----------------------------------------------------------------------------


def test_normalization_uses_train_rows_only():
    def outlier(x, q, dates):  # a test-period (2014-2025) outlier must not move the statistics
        x[dates >= "2020-01-01", 0] = 1e4
        q[dates >= "2020-01-01"] = 1e4

    clean = lstm.compute_norm([synth_basin(start="1980-01-01", end="2025-12-31")], "default")
    dirty = lstm.compute_norm(
        [synth_basin(start="1980-01-01", end="2025-12-31", extra=outlier)], "default"
    )
    np.testing.assert_allclose(clean.dyn_mean, dirty.dyn_mean)
    np.testing.assert_allclose(clean.dyn_std, dirty.dyn_std)
    assert clean.q_mean == dirty.q_mean and clean.q_std == dirty.q_std
    assert clean.dyn_mean[0] < 10  # precip mean from train years, not the outlier


def test_norm_round_trip_json():
    norm = lstm.compute_norm([synth_basin(start="1980-01-01", end="2012-12-31")], "default")
    again = lstm.Norm.from_dict(json.loads(json.dumps(norm.to_dict())))
    np.testing.assert_allclose(norm.dyn_mean, again.dyn_mean)
    assert norm.q_std == again.q_std


# --- samples -----------------------------------------------------------------------------------


def make_ds(split="default", start="1980-01-01", end="2025-12-31", **kw):
    b = [synth_basin(start=start, end=end, **kw)]
    return lstm.Dataset.from_basins(b, split, lstm.compute_norm(b, split)), b[0]


@pytest.mark.parametrize("split", ["default", "alt"])
@pytest.mark.parametrize("mode", ["sim", "forecast"])
def test_target_dates_never_overlap_between_parts(split, mode):
    ds, _ = make_ds(split)
    seen = {}
    for part in ("train", "val", "test"):
        ends = ds.sample_ends(part, mode, hist=30, n_out=7)
        assert len(ends) > 0
        dates = set()
        for e in ends:
            dates.update(ds.dates[e - 6 : e + 1])
        seen[part] = dates
        labels = {
            lstm.PART_NAMES[i]
            for i in ds.labels[np.concatenate([np.arange(e - 6, e + 1) for e in ends])]
        }
        assert labels == {part}
    assert not (seen["train"] & seen["val"])
    assert not (seen["train"] & seen["test"])
    assert not (seen["val"] & seen["test"])


def test_train_and_val_inputs_never_reach_test_dates():
    ds, _ = make_ds("alt")
    for part in ("train", "val"):
        ends = ds.sample_ends(part, "sim", hist=60, n_out=5)
        assert len(ends) > 0
        for e in ends:
            assert not (ds.labels[e - 59 : e + 1] == lstm.PART_NAMES.index("test")).any()


def test_sample_ends_skip_windows_with_missing_forcing():
    def hole(x, q, dates):
        x[400, 0] = np.nan

    ds, _ = make_ds("default", extra=hole)
    ends = ds.sample_ends("train", "sim", hist=30, n_out=1)
    assert not any(400 - 0 <= e <= 400 + 29 for e in ends)


def test_forecast_sample_flow_channel_mask_and_targets():
    def gap(x, q, dates):
        q[1000] = np.nan  # a gap inside the history

    ds, b = make_ds("default", extra=gap)
    hist, lead = 30, 7
    t = 1100
    e = t + lead
    x, y, w = ds.batch(np.array([e]), "forecast", hist=hist, n_out=lead)
    assert x.shape == (1, hist + lead, lstm.n_inputs("forecast"))
    flow, mask = x[0, :, -2], x[0, :, -1]
    qn = (b.q - ds.norm.q_mean) / ds.norm.q_std
    np.testing.assert_allclose(flow[:hist], qn[t - hist + 1 : t + 1], rtol=1e-5)
    assert (flow[hist:] == 0).all() and (mask[hist:] == 0).all()
    assert mask[:hist].all()
    np.testing.assert_allclose(y[0], qn[t + 1 : t + 1 + lead], rtol=1e-5)
    # a gap in the history becomes 0 with mask 0
    x2, _, _ = ds.batch(np.array([1000 + lead]), "forecast", hist=hist, n_out=lead)
    assert x2[0, hist - 1, -2] == 0 and x2[0, hist - 1, -1] == 0
    assert w.shape == (1,)


def test_sim_batch_has_no_flow_channels_and_last_steps_are_targets():
    ds, b = make_ds("default")
    e = 2000
    x, y, _ = ds.batch(np.array([e]), "sim", hist=20, n_out=4)
    assert x.shape == (1, 20, lstm.n_inputs("sim")) == (1, 20, 8)
    qn = (b.q - ds.norm.q_mean) / ds.norm.q_std
    np.testing.assert_allclose(y[0], qn[e - 3 : e + 1], rtol=1e-5)


# --- data builders -----------------------------------------------------------------------------


def write_neuquen_files(tmp_path, tmean_nan=False):
    dates = pd.date_range("2000-01-01", periods=400, freq="D")
    f = pd.DataFrame(
        {
            "station_id": np.int32(12004),
            "date": dates,
            "precip_mm": 2.0,
            "deg0l_m": 2500.0,
            "tmean_c": np.nan if tmean_nan else 8.0,
            "tmin_c": np.nan if tmean_nan else 3.0,
            "tmax_c": np.nan if tmean_nan else 13.0,
            "pet_mm": np.nan if tmean_nan else 1.5,
        }
    )
    fp = tmp_path / "forcing.parquet"
    f.to_parquet(fp)
    fp.with_suffix(".static.json").write_text(
        json.dumps(
            {
                "basins": {
                    "12004": {"area_km2": 1200.0, "elev_mean_m": 1800.0, "centroid_lat": -37.4}
                }
            }
        )
    )
    flow_dir = tmp_path / "flow"
    flow_dir.mkdir()
    q = pd.DataFrame({"date": dates[:300], "q_m3s": 100.0, "qualifier": "", "validated": True})
    q.loc[5, "q_m3s"] = np.nan
    q.to_parquet(flow_dir / "12004.parquet")
    (flow_dir / "stations.json").write_text(
        json.dumps({"stations": [{"id": 12004, "area_km2": 1000.0, "lat": -38.5}]})
    )
    return fp, flow_dir


def test_neuquen_basins_convert_flow_to_mm_per_day(tmp_path):
    fp, flow_dir = write_neuquen_files(tmp_path)
    basins, info = lstm.neuquen_basins(fp, flow_dir, stations=[12004])
    b = basins[0]
    assert b.id == "12004" and b.group == "neuquen"
    assert b.q[0] == pytest.approx(100.0 * 86.4 / 1000.0)
    assert np.isnan(b.q[5]) and np.isnan(b.q[350])  # missing day, and days after the flow record
    np.testing.assert_allclose(b.static, [np.log(1000.0), 1800.0, -38.5])
    assert b.x.shape == (400, 5)
    assert info["12004"]["area_km2"] == 1000.0


def test_neuquen_basins_fail_clearly_without_temperature(tmp_path):
    fp, flow_dir = write_neuquen_files(tmp_path, tmean_nan=True)
    with pytest.raises(ValueError, match="temperature"):
        lstm.neuquen_basins(fp, flow_dir, stations=[12004])


def test_camels_basins_use_attributes():
    dates = pd.date_range("1990-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "gauge_id": "g1",
            "date": dates,
            "precip_mm": 1.0,
            "tmin_c": 0.0,
            "tmax_c": 10.0,
            "tmean_c": 5.0,
            "pet_mm": 1.0,
            "q_mm": [1.0, 2.0, np.nan, 3.0, 4.0],
        }
    )
    attrs = pd.DataFrame(
        {"lat": [-35.0], "area_km2": [500.0], "elev_mean_m": [1200.0]},
        index=pd.Index(["g1"], name="gauge_id"),
    )
    (b,) = lstm.camels_basins(df, attrs, ["g1"])
    assert b.group == "camels" and b.id == "g1"
    np.testing.assert_allclose(b.static, [np.log(500.0), 1200.0, -35.0])
    # column order is the model's dynamic order: precip, tmean, tmin, tmax, pet
    np.testing.assert_allclose(b.x[0], [1.0, 5.0, 0.0, 10.0, 1.0])


# --- uncertainty -------------------------------------------------------------------------------


def test_residual_quantiles_and_band_hand_case():
    eps = lstm.EPS_MM
    pred = np.full(100, 2.0)
    ratio = np.exp(np.linspace(-1, 1, 100))
    obs = ratio * (pred + eps) - eps
    frame = pd.DataFrame({"lead": 0, "obs": obs, "pred": pred})
    q = lstm.fit_quantiles(frame)
    res = np.log((obs + eps) / (pred + eps))
    assert q["0"]["q05"] == pytest.approx(np.quantile(res, 0.05))
    assert q["0"]["q95"] == pytest.approx(np.quantile(res, 0.95))
    lo, hi = lstm.band(np.array([2.0]), q["0"])
    assert lo[0] == pytest.approx((2.0 + eps) * np.exp(q["0"]["q05"]) - eps)
    assert hi[0] == pytest.approx((2.0 + eps) * np.exp(q["0"]["q95"]) - eps)
    assert lstm.band(np.array([0.0]), {"q05": -5.0, "q95": 1.0})[0][0] == 0.0  # never negative


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_help_lists_options():
    r = CliRunner().invoke(cli.app, ["flow", "lstm-train", "--help"])
    assert r.exit_code == 0
    for opt in ("--mode", "--split", "--pretrain", "--no-pretrain", "--seeds", "--epochs",
                "--run-name", "--forcing", "--flow-dir", "--camels-dir", "--out-dir"):  # fmt: skip
        assert opt in r.output
    r = CliRunner().invoke(cli.app, ["flow", "streamflow-eval", "--help"])
    assert r.exit_code == 0 and "--run-name" in r.output


def test_cli_without_torch_tells_how_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)  # `import torch` raises ImportError
    r = CliRunner().invoke(cli.app, ["flow", "lstm-train", "--run-name", "x"])
    assert r.exit_code != 0
    assert "uv sync --group ml" in r.output
    r = CliRunner().invoke(cli.app, ["flow", "streamflow-eval", "--run-name", "x"])
    assert r.exit_code != 0 and "uv sync --group ml" in r.output


# --- torch -------------------------------------------------------------------------------------


def tiny_cfg(**kw):
    base = {"mode": "sim", "split": "default", "hidden": 8, "dropout": 0.0, "seq_len": 12, "loss_steps": 4,
                "batch_size": 64, "samples_per_epoch": 512, "epochs": 60, "patience": 100, "lr": 0.01,
                "seeds": (0,), "pretrain": False, "lead": 7}  # fmt: skip
    base.update(kw)
    return lstm.TrainConfig(**base)


def tiny_dataset(mode="sim"):
    b = [synth_basin(start="2000-01-01", end="2012-12-31")]
    return lstm.Dataset.from_basins(b, "default", lstm.compute_norm(b, "default"))


def test_tiny_model_overfits_synthetic_series():
    pytest.importorskip("torch")
    ds = tiny_dataset()
    cfg = tiny_cfg()
    _, hist = lstm.fit_model(ds, cfg, seed=0, epochs=cfg.epochs, lr=cfg.lr)
    assert hist["train_loss"][-1] < 0.1 * hist["train_loss"][0]


def test_same_seed_same_weights_and_predictions():
    torch = pytest.importorskip("torch")
    ds = tiny_dataset()
    cfg = tiny_cfg(epochs=3)
    m1, _ = lstm.fit_model(ds, cfg, seed=3, epochs=3, lr=cfg.lr)
    m2, _ = lstm.fit_model(ds, cfg, seed=3, epochs=3, lr=cfg.lr)
    for a, b in zip(m1.state_dict().values(), m2.state_dict().values(), strict=True):
        assert torch.equal(a, b)
    m3, _ = lstm.fit_model(ds, cfg, seed=4, epochs=3, lr=cfg.lr)
    assert not all(
        torch.equal(a, b) for a, b in zip(m1.state_dict().values(), m3.state_dict().values())
    )


def test_run_save_load_roundtrip_and_ensemble_shape(tmp_path):
    pytest.importorskip("torch")
    b = [synth_basin(start="2000-01-01", end="2012-12-31")]
    cfg = tiny_cfg(epochs=2, seeds=(0, 1, 2))
    run = lstm.train_run(b, None, cfg, info={"note": "synthetic"})
    out = lstm.save_run(run, tmp_path / "run")
    for name in ("config.json", "norm.json", "quantiles.json", "model_seed0.pt", "model_seed2.pt"):
        assert (out / name).is_file()
    cfgj = json.loads((out / "config.json").read_text())
    assert cfgj["mode"] == "sim" and cfgj["seeds"] == [0, 1, 2] and cfgj["pretrain"] is False
    assert cfgj["splits"]["default"]["test"] == [2014, 2025]
    loaded = lstm.load_run(out)
    ds = lstm.Dataset.from_basins(b, "default", loaded.norm)
    ends = ds.sample_ends("val", "sim", hist=cfg.seq_len, n_out=1)[:20]
    p1 = lstm.predict(run, ds, ends, n_out=1)
    p2 = lstm.predict(loaded, ds, ends, n_out=1)
    assert p1.shape == (3, 20, 1)
    np.testing.assert_array_equal(p1, p2)
    assert (p1 >= 0).all()
    assert lstm.ensemble_median(p1).shape == (20, 1)
    assert loaded.quantiles.keys() == run.quantiles.keys() == {"0"}


def test_forecast_mode_trains_and_predicts_seven_leads():
    pytest.importorskip("torch")
    b = [synth_basin(start="2000-01-01", end="2012-12-31")]
    cfg = tiny_cfg(mode="forecast", epochs=2)
    run = lstm.train_run(b, None, cfg)
    ds = lstm.Dataset.from_basins(b, "default", run.norm)
    frame = lstm.predict_frame(run, ds, "val", max_samples=30)
    assert set(frame["lead"]) == set(range(1, 8))
    assert {"basin_id", "issue_date", "date", "lead", "obs", "pred"} <= set(frame.columns)
    assert sorted(run.quantiles) == [str(k) for k in range(1, 8)]
    assert (frame["date"] > frame["issue_date"]).all()


@pytest.mark.slow
def test_pretrain_then_finetune_runs():
    pytest.importorskip("torch")
    neu = [synth_basin("n1", start="2000-01-01", end="2012-12-31")]
    cam = [synth_basin("c1", seed=1, group="camels"), synth_basin("c2", seed=2, group="camels")]
    cfg = tiny_cfg(epochs=2, pretrain=True, pretrain_epochs=2)
    run = lstm.train_run(neu, cam, cfg)
    assert run.info["pretrain"]["n_basins"] == 2


def test_neuquen_basins_trim_trailing_days_without_precipitation(tmp_path):
    fp, flow_dir = write_neuquen_files(tmp_path)
    f = pd.read_parquet(fp)
    f.loc[f.index[-1], "precip_mm"] = np.nan
    f.to_parquet(fp)
    (b,), _ = lstm.neuquen_basins(fp, flow_dir, stations=[12004])
    assert len(b.dates) == 399 and not np.isnan(b.x[:, 0]).any()

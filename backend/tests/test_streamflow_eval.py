import json

import numpy as np
import pandas as pd
import pytest

from clima_nqn.stages.flood import hydro_models as hm
from clima_nqn.stages.flood import lstm
from clima_nqn.stages.flood import streamflow_eval as ev

PARAMS = hm.Params(350.0, -1.0, 90.0, 1.7, 0.1, 3.0)


def station_basin(sid="12004", start="2002-01-01", end="2017-12-31", seed=0):
    """Basin whose flow is GR4J+CemaNeige with known parameters (mm/d)."""
    dates = pd.date_range(start, end, freq="D")
    n = len(dates)
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    season = np.cos(2 * np.pi * t / 365.25)
    tmean = 6 - 10 * season + rng.normal(0, 2, n)
    precip = np.where(rng.random(n) < 0.35, rng.gamma(0.8, 9.0, n), 0.0) * (1.2 + 0.5 * season)
    pet = np.clip(1.6 - 1.4 * season, 0, None)
    q = hm.simulate(PARAMS, precip, tmean, pet).q
    x = np.stack([precip, tmean, tmean - 4, tmean + 4, pet], axis=1)
    return lstm.Basin(sid, dates, x, q.copy(), np.array([np.log(1000.0), 1500.0, -38.0]), "neuquen")


FAST = {"seeds": (0, 1), "maxiter": 3, "popsize": 4}


def test_band_coverage_hand_case():
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0, np.nan])
    lo = np.array([0.0, 0.0, 4.0, 0.0, 0.0, 0.0])
    hi = np.array([2.0, 2.0, 5.0, 5.0, 4.0, 9.0])
    assert ev.band_coverage(obs, lo, hi) == pytest.approx(0.6)  # 3 of 5 observed days inside
    assert np.isnan(ev.band_coverage(np.array([np.nan]), lo[:1], hi[:1]))


def test_gr4j_baseline_calibrates_on_train_years_only():
    b = station_basin()
    out = ev.gr4j_baseline(b, "default", **FAST)
    assert out["q"].shape == b.q.shape
    assert out["seed"] in FAST["seeds"]
    assert -5 < out["kge_cal"] <= 1
    assert out["calibration_period"].startswith(
        "2002-01-01"
    )  # Jan-Mar 2002 is hydrological year 2001 (train)
    assert out["calibration_period"].endswith("2007-03-31")


def test_gr4j_baseline_errors_on_missing_temperature():
    b = station_basin()
    b.x[:, 1] = np.nan
    with pytest.raises(ValueError, match="temperature"):
        ev.gr4j_baseline(b, "default", **FAST)


def test_gr4j_keeps_best_calibration_seed(monkeypatch):
    kges = {0: 0.2, 1: 0.9, 2: 0.5}

    def fake_calibrate(precip, temp, pet, qobs, warmup=365, seed=0, maxiter=50, popsize=8, **kw):
        return hm.Calibration(PARAMS, kges[seed])

    monkeypatch.setattr(ev.hm, "calibrate", fake_calibrate)
    out = ev.gr4j_baseline(station_basin(), "default", seeds=(0, 1, 2))
    assert out["seed"] == 1 and out["kge_cal"] == 0.9


def test_baseline_metrics_structure_sim_and_forecast():
    b = station_basin()
    for mode in ("sim", "forecast"):
        m = ev.evaluate([b], mode=mode, split="default", hist=30, lead=7, **FAST)
        st = m["stations"]["12004"]
        leads = ["0"] if mode == "sim" else [str(k) for k in range(1, 8)]
        assert list(st["leads"]) == leads
        for k in leads:
            cell = st["leads"][k]
            assert cell["n"] > 1000
            assert set(cell["models"]) == ({"gr4j"} if mode == "sim" else {"gr4j", "persistence"})
            for scores in cell["models"].values():
                assert np.isfinite(scores["nse"]) and np.isfinite(scores["kge"])
            assert cell["coverage90"] is None  # no LSTM: no band
        assert m["mode"] == mode and m["split"] == "default"
        assert m["test_years"] == [2014, 2025]
        assert "12004" in m["gr4j"] and m["gr4j"]["12004"]["seed"] in FAST["seeds"]
        assert any("UTC" in n for n in m["notes"])
        assert any("no pronóstico operativo" in n for n in m["notes"])
        json.dumps(m)  # serializable


def test_persistence_lead_one_matches_hand_computation():
    b = station_basin()
    m = ev.evaluate([b], mode="forecast", split="default", hist=30, lead=7, **FAST)
    ds = lstm.Dataset.from_basins([b], "default", lstm.compute_norm([b], "default"))
    ends = ds.sample_ends("test", "forecast", 30, 7)
    t = ends - 7  # issue-day indices
    obs, pers = b.q[t + 1], b.q[t]
    assert m["stations"]["12004"]["leads"]["1"]["models"]["persistence"]["nse"] == pytest.approx(
        hm.nse(obs, pers)
    )


def test_score_frame_uses_only_days_all_models_have():
    frame = pd.DataFrame(
        {
            "basin_id": "a",
            "lead": 1,
            "date": pd.date_range("2015-01-01", periods=4),
            "obs": [1.0, 2.0, 3.0, 4.0],
            "lstm": [1.0, 2.5, np.nan, 4.5],
            "gr4j": [1.1, 2.1, 3.1, 4.1],
        }
    )
    cells = ev.score_frame(frame, ["lstm", "gr4j"], quantiles=None)
    cell = cells["a"]["1"]
    assert cell["n"] == 3  # the NaN lstm day drops out of every model's score
    keep = [0, 1, 3]
    assert cell["models"]["gr4j"]["nse"] == pytest.approx(
        hm.nse(frame["obs"].to_numpy()[keep], frame["gr4j"].to_numpy()[keep])
    )


def test_score_frame_band_coverage_from_quantiles():
    pred = np.full(10, 2.0)
    obs = np.array([2.0] * 8 + [50.0, 0.0])
    frame = pd.DataFrame(
        {"basin_id": "a", "lead": 0, "date": pd.date_range("2015-01-01", periods=10), "obs": obs,
         "lstm": pred}
    )  # fmt: skip
    q = {"0": {"q05": np.log(0.5), "q95": np.log(2.0), "n": 99}}
    cell = ev.score_frame(frame, ["lstm"], quantiles=q)["a"]["0"]
    lo, hi = lstm.band(pred, q["0"])
    assert cell["coverage90"] == pytest.approx(np.mean((obs >= lo) & (obs <= hi)))
    assert cell["coverage90"] == pytest.approx(0.8)


def test_metrics_table_markdown():
    b = station_basin()
    m = ev.evaluate([b], mode="forecast", split="default", hist=30, lead=7, **FAST)
    table = ev.metrics_table(m)
    lines = table.splitlines()
    assert lines[0].startswith("| ") and "12004" in table and "persistence" in table
    assert len(lines) >= 2 + 7  # header, separator and one row per lead


def test_score_frame_excludes_hydrological_year_2023():
    dates = pd.to_datetime(["2023-03-31", "2023-04-01", "2024-03-31", "2024-04-01", "2024-05-01"])
    frame = pd.DataFrame(
        {
            "basin_id": "a",
            "lead": 0,
            "date": dates,
            "obs": [1.0, 50.0, 60.0, 2.0, 3.0],
            "gr4j": [1.2, 10.0, 10.0, 2.5, 2.8],
        }
    )
    cell = ev.score_frame(frame, ["gr4j"])["a"]["0"]
    assert cell["n"] == 5 and cell["excl_2023"]["n"] == 3  # 2023-04-01..2024-03-31 dropped
    keep = [0, 3, 4]
    assert cell["excl_2023"]["models"]["gr4j"]["nse"] == pytest.approx(
        hm.nse(frame["obs"].to_numpy()[keep], frame["gr4j"].to_numpy()[keep])
    )
    assert cell["models"]["gr4j"]["nse"] < cell["excl_2023"]["models"]["gr4j"]["nse"]


def test_score_frame_log_nse_hand_case():
    obs = np.array([1.0, 2.0, 4.0, 8.0])
    sim = np.array([1.5, 2.0, 3.0, 9.0])
    frame = pd.DataFrame(
        {"basin_id": "a", "lead": 0, "date": pd.date_range("2015-01-01", periods=4), "obs": obs,
         "gr4j": sim}
    )  # fmt: skip
    cell = ev.score_frame(frame, ["gr4j"], None, log_eps={"a": 0.5})["a"]["0"]
    lo, ls = np.log(obs + 0.5), np.log(sim + 0.5)
    expected = 1 - ((lo - ls) ** 2).sum() / ((lo - lo.mean()) ** 2).sum()
    assert cell["models"]["gr4j"]["nse_log"] == pytest.approx(expected)
    assert "nse_log" not in ev.score_frame(frame, ["gr4j"])["a"]["0"]["models"]["gr4j"]


def test_evaluate_reports_log_eps_from_training_mean():
    b = station_basin()
    m = ev.evaluate([b], mode="sim", split="default", hist=30, **FAST)
    train_q = b.q[ev.split_train(b.dates, "default")]
    assert m["log_eps_mm"]["12004"] == pytest.approx(0.01 * np.nanmean(train_q))
    cell = m["stations"]["12004"]["leads"]["0"]
    assert np.isfinite(cell["models"]["gr4j"]["nse_log"])
    assert "sin 2023" in ev.sensitivity_table(m)

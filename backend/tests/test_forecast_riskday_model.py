"""F6.3 risk-day half: frozen logistic fit, numpy inference and registry emission."""

import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from clima_nqn.forecast import riskday_model as rm
from clima_nqn.forecast.registry import (
    InvalidPredictionError,
    PredictionRegistry,
)
from clima_nqn.stages.hindcast import riskday as rd

TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
MEMBERS = ("c00", "p01", "p02", "p03", "p04")


# --- synthetic fit inputs --------------------------------------------------------------------------


def synthetic_ctx(seed=0, n_leads=2, poison_after_fit=False):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2000-01-01", "2019-12-31")
    n = len(dates)
    tp, members = {}, {}
    for r in rd.REGIONS:
        base = rng.gamma(0.4, 3.0, n)
        tp[r] = base
        mem = np.empty((n, n_leads, 5))
        for li in range(n_leads):
            for k in range(5):
                mem[:, li, k] = base * np.exp(rng.normal(0, 0.3 * (li + 1), n))
        mem[5, 0, 2] = np.nan
        members[r] = mem
    tp_df = pd.DataFrame(tp, index=dates)
    if poison_after_fit:
        tp_df.loc["2015-01-01":] = rng.gamma(0.4, 300.0, (int((dates >= "2015-01-01").sum()), 3))
    cp_df = tp_df * 0.1
    events = pd.DataFrame({"event_id": [], "start": [], "end": []})
    return rd.build_context(dates, range(1, n_leads + 1), members, tp_df, cp_df, events)


@pytest.fixture(scope="module")
def ctx():
    return synthetic_ctx()


@pytest.fixture(scope="module")
def fitted(ctx):
    pytest.importorskip("sklearn")
    return rm.fit_frozen(ctx, n_boot=12, seed=0)


def test_numpy_predict_equals_sklearn_logistic(ctx, fitted):
    thr = {r: rd.train_threshold(ctx["tp"][r], rm.QUANTILE) for r in rd.REGIONS}
    dates = ctx["dates"]
    sp = rd.split_masks(dates)
    new = np.flatnonzero(sp["test"])[::37]
    for r in rd.REGIONS:
        risk = (ctx["tp"][r] >= thr[r]).reindex(dates).to_numpy(dtype=int)
        for li, lead in enumerate(ctx["leads"]):
            feat = rd.feature_frame(ctx["members"], r, li, thr, dates)
            fit = (sp["train"] | sp["valid"]) & ~np.isnan(feat["own_mean"].to_numpy())
            ref = rd.fit_logistic(feat[fit], risk[fit], feat.iloc[new])
            got = [
                rm.predict(fitted, r, lead, {r: ctx["members"][r][i, li, :]}, dates[i].month)[0]
                for i in new
            ]
            np.testing.assert_allclose(got, ref, atol=1e-9, rtol=0)
            # climatology is the F5.3 monthly base rate of the same fit rows
            clim = rd.climatology_rates(dates.month.to_numpy()[fit], risk[fit])
            np.testing.assert_allclose(fitted["regions"][r][str(lead)]["clim_rates"], clim)


def test_fit_ignores_everything_after_2014(ctx, fitted):
    poisoned = rm.fit_frozen(synthetic_ctx(poison_after_fit=True), n_boot=12, seed=0)
    assert rm.dumps_model(poisoned) == rm.dumps_model(fitted)
    assert fitted["meta"]["fit_last_date"] <= "2014-12-31"
    assert fitted["meta"]["fit_period"] == "2000-01-01/2014-12-31"
    assert fitted["meta"]["train_period_threshold"] == "2000-01-01/2011-12-31"


def test_fit_is_deterministic_and_has_schema(ctx, fitted):
    again = rm.fit_frozen(ctx, n_boot=12, seed=0)
    assert rm.dumps_model(again) == rm.dumps_model(fitted)
    e = fitted["regions"]["confluencia"]["2"]
    assert len(e["boot_coef"]) == len(e["boot_intercept"]) == 12
    assert len(e["boot_coef"][0]) == len(e["coef"]) == len(e["scaler_mean"]) == 4
    assert len(e["clim_rates"]) == 12 and e["prob_cap"] is None
    assert fitted["meta"]["members"] == ["c00", "p01", "p02", "p03", "p04"]
    assert rm.N_BOOT == 200


def test_json_roundtrip_and_version(tmp_path, fitted):
    path = tmp_path / "m.json"
    sha = rm.write_model(fitted, path)
    model, sha2 = rm.load_model(path)
    assert sha == sha2 and model == json.loads(json.dumps(fitted))
    assert rm.model_version(sha) == f"riskday-log-v1-{sha[:8]}"
    assert rm.write_model(fitted, tmp_path / "m2.json") == sha


# --- inference ------------------------------------------------------------------------------------


def toy_model(shift=0.0):
    rng = np.random.default_rng(1)
    coef = np.array([1.0, 2.0, 0.0, 0.0])
    regions = {}
    for r in rd.REGIONS:
        regions[r] = {
            str(lead): {
                "scaler_mean": [0.5, 0.1, 0.0, 0.0],
                "scaler_scale": [1.0, 1.0, 1.0, 1.0],
                "coef": coef.tolist(),
                "intercept": -2.0,
                "boot_coef": (coef + rng.normal(0, 0.3, (200, 4))).tolist(),
                "boot_intercept": (-2.0 + shift + rng.normal(0, 0.3, 200)).tolist(),
                "threshold_mm": 10.0,
                "clim_rates": [0.1] * 12,
                "clim_n": [300] * 12,
                "prob_cap": None,
            }
            for lead in rm.LEADS
        }
    return {"meta": {"model_name": "logistica"}, "regions": regions}


def test_predict_interval_contains_point_estimate():
    rng = np.random.default_rng(2)
    for shift in (0.0, -6.0, 6.0):  # bootstrap entirely below / above the point estimate
        model = toy_model(shift)
        for _ in range(30):
            mem = rng.gamma(0.5, 8.0, 5)
            p, lo, hi, cp, f = rm.predict(model, "cordillera_sur", 3, {"cordillera_sur": mem}, 7)
            assert 0 <= lo <= p <= hi <= 1
            assert cp == 0.1 and f["n_members"] == 5
    p, lo, hi, *_ = rm.predict(toy_model(-6.0), "confluencia", 1, {"confluencia": mem}, 7)
    assert hi == p  # clamped: bootstrap quantiles were all below p


def test_predict_ignores_nan_members_and_rejects_empty():
    model = toy_model()
    mem = np.array([12.0, 3.0, np.nan, 9.0, np.nan])
    a = rm.predict(model, "confluencia", 2, {"confluencia": mem}, 6)
    b = rm.predict(model, "confluencia", 2, {"confluencia": mem[~np.isnan(mem)]}, 6)
    assert a[:4] == b[:4] and a[4]["n_members"] == 3
    assert a[4]["member_frac"] == pytest.approx(1 / 3)
    for bad in (np.full(5, np.nan), np.array([])):
        with pytest.raises(rm.RiskDayModelError):
            rm.predict(model, "confluencia", 2, {"confluencia": bad}, 6)
    with pytest.raises(rm.RiskDayModelError):
        rm.predict(model, "confluencia", 11, {"confluencia": mem}, 6)


# --- emission -------------------------------------------------------------------------------------


def make_snapshot(path, init=TODAY, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for region in rd.REGIONS:
        for lead in rm.LEADS:
            for m in MEMBERS:
                rows.append(
                    {
                        "init_date": init,
                        "lead": lead,
                        "valid_date": init + timedelta(days=lead - 1),
                        "member": m,
                        "region": region,
                        "tp_mm": float(rng.gamma(0.5, 8.0)),
                        "available_on": datetime(2026, 11, 22, 9, 0),
                    }
                )
    pd.DataFrame(rows).to_parquet(path)
    return path


def registry(tmp_path, now=NOW):
    return PredictionRegistry(tmp_path / "reg.jsonl", clock=lambda: now)


def test_emit_today_two_models_three_regions_ten_leads(tmp_path):
    snap = make_snapshot(tmp_path / "2026-11-22.parquet")
    reg = registry(tmp_path)
    recs = rm.emit(reg, toy_model(), "ab" * 32, snap, TODAY)
    assert len(recs) == 2 * 3 * 10
    assert {r.model_name for r in recs} == {"logistica", "climatologia"}
    assert {r.region for r in recs} == set(rd.REGIONS)
    assert {r.variable for r in recs} == {"p_dia_riesgo"}
    for r in recs:
        assert r.kind == "probability" and r.interval_level == 0.9
        assert r.interval_low <= r.value <= r.interval_high
        assert r.details["estado"] == "Experimental"
        assert r.details["threshold_mm"] == 10.0 and r.details["prob_cap"] is None
        assert r.details["gefs_lead"] == r.lead_days + 1  # init == issue day
        assert r.valid_date == TODAY + timedelta(days=r.lead_days)
        assert r.training_period == "2000-01-01/2014-12-31"
        assert r.details["n_members"] == 5 and r.details["gefs_init_date"] == "2026-11-22"
    log = [r for r in recs if r.model_name == "logistica"]
    assert any(r.interval_high > r.interval_low for r in log)
    assert {r.model_version for r in log} == {"riskday-log-v1-abababab"}
    assert {r.inputs[0].latency_hours for r in recs} == {0.0}
    assert reg.verify() is not None
    with pytest.raises(Exception, match="already issued"):  # idempotent by day: no double emission
        rm.emit(reg, toy_model(), "ab" * 32, snap, TODAY)


def test_emit_inputs_hash_covers_snapshot_and_model(tmp_path):
    snap = make_snapshot(tmp_path / "2026-11-22.parquet")
    a = rm.emit(registry(tmp_path), toy_model(), "ab" * 32, snap, TODAY)[0]
    other = tmp_path / "other"
    other.mkdir()
    b = rm.emit(
        PredictionRegistry(other / "r.jsonl", clock=lambda: NOW),
        toy_model(),
        "cd" * 32,
        snap,
        TODAY,
    )[0]
    assert a.inputs_sha256 != b.inputs_sha256


def test_emit_past_date_is_rejected(tmp_path):
    past = TODAY - timedelta(days=2)
    snap = make_snapshot(tmp_path / "2026-11-20.parquet", init=past)
    reg = registry(tmp_path)
    with pytest.raises(InvalidPredictionError):  # the registry refuses backdated issue times
        rm.emit(reg, toy_model(), "ab" * 32, snap, NOW - timedelta(days=2))
    with pytest.raises(ValueError, match="registry's today"):
        rm.emit(reg, toy_model(), "ab" * 32, snap, past)
    fresh = make_snapshot(
        tmp_path / "2026-11-22.parquet"
    )  # a run from the future of that issue date
    with pytest.raises(ValueError, match="after the issue date"):
        rm.emit(reg, toy_model(), "ab" * 32, fresh, NOW - timedelta(days=2))
    assert reg.read() == []


def test_emit_from_yesterdays_run_skips_elapsed_lead(tmp_path):
    snap = make_snapshot(tmp_path / "2026-11-21.parquet", init=TODAY - timedelta(days=1))
    recs = rm.emit(registry(tmp_path), toy_model(), "ab" * 32, snap, TODAY)
    assert len(recs) == 2 * 3 * 9  # lead 1 is valid yesterday: cannot be issued
    for r in recs:  # registry lead = valid - issue day; GEFS lead kept in details
        assert r.lead_days == r.details["gefs_lead"] - 2 and r.details["gefs_lead"] >= 2
    assert {r.inputs[0].latency_hours for r in recs} == {24.0}


def test_latest_snapshot_picks_newest_not_after_day(tmp_path):
    for d in ("2026-11-19", "2026-11-21", "2026-11-23"):
        (tmp_path / f"{d}.parquet").write_bytes(b"")
    (tmp_path / "notes.parquet").write_bytes(b"")
    assert rm.latest_snapshot(tmp_path, TODAY).name == "2026-11-21.parquet"
    with pytest.raises(FileNotFoundError):
        rm.latest_snapshot(tmp_path, date(2026, 1, 1))

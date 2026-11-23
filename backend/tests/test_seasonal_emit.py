"""F6.2 monthly seasonal emission: refusals, model gating, availability, idempotency, notices (offline)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from clima_nqn.forecast.registry import PredictionRegistry
from clima_nqn.stages.seasonal import data, emit

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "backend/models/seasonal-v1"
F62 = ROOT / "reports/06/F6.2.json"
ISSUE = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 10, 17, tzinfo=UTC)


def _oni() -> pd.DataFrame:
    return pd.DataFrame(
        {"date": pd.to_datetime(["2026-07-01", "2026-08-01"]), "oni": [1.6, 2.0],
         "phase": ["nino", "nino"]}
    )  # fmt: skip


def _fetchers(
    state_ok=True, rain_ok=True, seen: dict | None = None, oni: pd.DataFrame | None = None
) -> emit.Fetchers:
    seen = seen if seen is not None else {}

    def state(t):
        seen["state_t"] = t
        if not state_ok:
            return None
        return {b: {"sd": 0.001, "swvl1": 0.19, "swvl2": 0.19, "swvl3": 0.2} for b in data.BOXES}

    def rain(first, last):
        seen["rain"] = (first, last)
        if not rain_ok:
            raise RuntimeError("sin red")
        days = pd.date_range(first, last)
        return {b: pd.Series(2.0, index=days) for b in (12004, 12010)}

    return emit.Fetchers(
        state=state,
        rain_daily=rain,
        oni=(lambda: _oni()) if oni is None else (lambda: oni),
        era5t_latest=lambda: pd.Timestamp("2026-11-16 23:00"),
    )


def _reg(tmp_path, now=NOW):
    return PredictionRegistry(tmp_path / "reg.jsonl", clock=lambda: now)


def _run(tmp_path, **kw):
    return emit.emit_seasonal(_reg(tmp_path), ISSUE, _fetchers(**kw), MODELS, F62)


def test_refuses_non_first_day(tmp_path):
    reg = _reg(tmp_path, datetime(2026, 11, 2, 10, 0, tzinfo=UTC))
    with pytest.raises(emit.SeasonalEmitError, match="día 1"):
        emit.emit_seasonal(reg, date(2026, 11, 2), _fetchers(), MODELS, F62)
    assert reg.read() == []


def test_refuses_issue_that_is_not_registry_today(tmp_path):
    with pytest.raises(emit.SeasonalEmitError, match="hoy del registro"):
        emit.emit_seasonal(_reg(tmp_path), date(2026, 10, 1), _fetchers(), MODELS, F62)


def test_model_only_where_beats_climatology(tmp_path):
    res = _run(tmp_path)
    beats = {(t, k) for (t, k) in emit._beats(json.loads(F62.read_text()))}
    assert beats == {(t, k) for t in ("flow12004", "flow12010") for k in (1, 2, 3)}
    logit = [r for r in res.records if r.model_name == "logistica"]
    got = {(r.details["objetivo"], r.details["lead_months"]) for r in logit}
    assert got == beats
    for r in res.records:  # no model record for rain, AR or flow leads 4-6
        if (r.details["objetivo"], r.details["lead_months"]) not in beats:
            assert r.model_name != "logistica"
    for r in logit:
        assert abs(sum(r.details["p_terciles"].values()) - 1) < 1e-9
        assert r.details["hindcast"]["ic95"][0] > 0  # evidence recorded


def test_baselines_for_every_target_and_lead(tmp_path):
    res = _run(tmp_path)
    key = {(r.details["objetivo"], r.details["lead_months"], r.model_name) for r in res.records}
    for t in emit.TARGET_INFO:
        for k in range(1, 7):
            assert (t, k, "climatologia") in key and (t, k, "analogos_enso") in key
            assert ((t, k, "persistencia") in key) == (t == "rain")
    assert any(
        "236" in v for v in res.skipped.values()
    )  # flow persistence skipped, with the reason
    assert len(res.records) == 24 + 24 + 6 + 6


def test_lead_encoding_and_details(tmp_path):
    res = _run(tmp_path)
    for r in res.records:
        k = r.details["lead_months"]
        first = (pd.Timestamp(ISSUE) + pd.DateOffset(months=k - 1)).date()
        assert r.valid_date == first and r.lead_days == (first - ISSUE).days
        assert r.details["target_month"] == f"{first:%Y-%m}"
        assert r.details["estado"] == "Experimental" and r.variable == emit.VAR
        lo, hi = (
            r.details["bordes_terciles"]["inferior_hasta"],
            r.details["bordes_terciles"]["superior_desde"],
        )
        assert lo <= hi
        assert r.training_period.count("/") == 1 and r.inputs and len(r.inputs_sha256) == 64
        assert r.details["periodo_entrenamiento"] == r.training_period
        assert set(r.details["p_terciles"]) == {"inferior", "medio", "superior"}


def test_notices_present(tmp_path):
    res = _run(tmp_path)
    for r in res.records:
        txt = " ".join(r.details["avisos"])
        assert "No es una alerta oficial" in txt
        for name in ("SMN", "AIC", "Defensa Civil"):
            assert name in txt
        assert "Experimental" in txt and "no indica qué hacer" in txt
        assert r.details["clim_prob"] == pytest.approx(1 / 3) and "historial" in r.details


def test_no_input_available_after_issue(tmp_path):
    seen: dict = {}
    _run(tmp_path, seen=seen)
    iss = pd.Timestamp(ISSUE)
    assert seen["state_t"] == iss - pd.Timedelta(days=5)  # 00 UTC of issue - 5 d, never later
    assert seen["rain"][1] <= iss - pd.Timedelta(days=6)  # last rain day ends at the sampled hour
    with pytest.raises(AssertionError):  # the guard itself
        data.assert_available(pd.DataFrame({"x": [iss + pd.Timedelta(days=1)]}), [iss])


def test_unavailable_inputs_baselines_only(tmp_path):
    res = _run(tmp_path, state_ok=False)
    assert not [r for r in res.records if r.model_name == "logistica"]
    assert len(res.records) == 24 + 24 + 6
    flow = [
        r
        for r in res.records
        if r.details["objetivo"] == "flow12004" and r.details["lead_months"] == 1
    ]
    assert flow and all(r.details["model_skipped"] == "entradas no disponibles" for r in flow)
    rest = [
        r
        for r in res.records
        if r.details["objetivo"] == "flow12004" and r.details["lead_months"] == 5
    ]
    assert all("model_skipped" not in r.details for r in rest)


def test_rain_failure_skips_only_models_that_need_rain(tmp_path):
    res = _run(tmp_path, rain_ok=False)
    logit = {r.details["objetivo"] for r in res.records if r.model_name == "logistica"}
    assert logit == {"flow12004"}  # set S has no rain; flow12010 (set SR) needs rain30/90
    assert not [r for r in res.records if r.model_name == "persistencia"]


def test_idempotent_rerun(tmp_path):
    reg = _reg(tmp_path)
    a = emit.emit_seasonal(reg, ISSUE, _fetchers(), MODELS, F62)
    head = reg.verify()
    b = emit.emit_seasonal(reg, ISSUE, _fetchers(), MODELS, F62)
    assert len(a.records) > 0 and b.records == [] and reg.verify() == head
    keys = [(r.model_version, r.variable, r.region, r.lead_days) for r in reg.read()]
    assert len(keys) == len(set(keys))


def test_missing_oni_skips_analogs_only(tmp_path):
    res = _run(tmp_path, oni=_oni().iloc[:1])  # no Aug season yet
    assert not [r for r in res.records if r.model_name == "analogos_enso"]
    assert [r for r in res.records if r.model_name == "climatologia"]


def test_logistic_probs_sum_to_one_and_follow_coefficients():
    meta = json.loads((MODELS / "flow12004.json").read_text())
    feats = {c: meta["anomaly_stats"]["11"][c][0] for c in meta["features"] if c != "lead"}
    p = emit.logistic_probs(
        meta, feats, pd.Timestamp("2026-11-01"), 3
    )  # anomalies 0, lead 3 -> intercept
    z = np.asarray(meta["intercept"]) + np.asarray(meta["coef"])[:, -1] * ((3 - 3.5) / 1.7)
    assert p.sum() == pytest.approx(1) and np.allclose(p, np.exp(z) / np.exp(z).sum())

"""F6.6 backend: ``forecast-outlook`` layer from a synthetic registry, scores and status log.

``write_fixture`` regenerates ``web/e2e/fixtures/processed/forecast-outlook``; a test checks the committed
fixture is exactly what the builder writes (rerun: ``FORECAST_OUTLOOK_WRITE_FIXTURE=1 uv run pytest -k fixture``).
"""

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.forecast import riskday_model as rm
from clima_nqn.forecast import status as st
from clima_nqn.forecast.registry import PredictionRegistry
from clima_nqn.layers import forecast_outlook as fo
from clima_nqn.layers import forecast_outlook_extras as extras
from clima_nqn.layers.manifest import load_manifest
from clima_nqn.stages.hindcast import riskday as rd
from clima_nqn.stages.seasonal import data, emit

TODAY = date(2026, 1, 1)
NOW = datetime(2026, 1, 1, 10, 17, tzinfo=UTC)
MEMBERS = ("c00", "p01", "p02", "p03", "p04")
SHA = "ab" * 32
VERSION = rm.model_version(SHA, "log")
FIXTURE = Path(__file__).resolve().parents[2] / "web/e2e/fixtures/processed/forecast-outlook"
F58 = Path(__file__).resolve().parents[2] / "reports/05/F5.8.json"


def toy_model() -> dict:
    rng = np.random.default_rng(1)
    coef = np.array([1.0, 2.0, 0.0, 0.0])
    entry = lambda: {
        "scaler_mean": [0.5, 0.1, 0.0, 0.0],
        "scaler_scale": [1.0] * 4,
        "coef": coef.tolist(),
        "intercept": -2.0,
        "boot_coef": (coef + rng.normal(0, 0.3, (50, 4))).tolist(),
        "boot_intercept": (-2.0 + rng.normal(0, 0.3, 50)).tolist(),
        "threshold_mm": 12.5,
        "clim_rates": [0.05] * 12,
        "clim_n": [300] * 12,
        "prob_cap": None,
    }
    regions = {r: {str(lead): entry() for lead in rm.LEADS} for r in rd.REGIONS}
    return {"meta": {"model_name": "logistica"}, "regions": regions}


def caps() -> dict:
    return {
        "rule": rm.CAP_RULE,
        "caps": {
            r: {str(lead): (1.0 if lead <= 4 else 0.3) for lead in rm.LEADS} for r in rd.REGIONS
        },
    }


def snapshot(path: Path, init: date = TODAY) -> Path:
    """Wet northern cordillera, dry elsewhere: p is high (above the 0.3 cap) from lead 5 on in the north."""
    rng = np.random.default_rng(3)
    rows = []
    for region in rd.REGIONS:
        for lead in rm.LEADS:
            for m in MEMBERS:
                mm = 30.0 + rng.uniform(0, 5) if region == "cordillera_norte" else rng.uniform(0, 3)
                rows.append(
                    {
                        "init_date": init,
                        "lead": lead,
                        "valid_date": init + timedelta(days=lead - 1),
                        "member": m,
                        "region": region,
                        "tp_mm": round(float(mm), 2),
                        "available_on": datetime(2026, 1, 1, 9, 0),
                    }
                )
    pd.DataFrame(rows).to_parquet(path)
    return path


def make_registry(tmp_path: Path, now: datetime = NOW) -> PredictionRegistry:
    reg = PredictionRegistry(tmp_path / "reg.jsonl", clock=lambda: now)
    snap = snapshot(tmp_path / f"{now.date()}.parquet", init=now.date())
    rm.emit(reg, toy_model(), SHA, snap, now.date(), caps=caps())
    return reg


def scores_payload() -> dict:
    row = {
        "model": "logistica",
        "variable": "p_dia_riesgo",
        "station": "cordillera_norte",
        "lead": 1,
        "n": 40,
        "n_events": 12,
        "skill": 0.18,
        "skill_ci_low": -0.05,
        "skill_ci_high": 0.37,
        "pod": 0.6,
        "far": 0.4,
        "status": "ok",
    }
    thin = {**row, "lead": 2, "n": 9, "n_events": 3, "skill": None, "skill_ci_low": None,
            "skill_ci_high": None, "pod": None, "far": None, "status": "insuficiente"}  # fmt: skip
    clim = {**row, "model": "climatologia", "skill": 0.0}
    return {
        "table": [row, thin, clim],
        "events_pooled": {"p_dia_riesgo": {"1": {"overall": 14}, "2": {"overall": 5}}},
    }


def gate() -> dict:
    cell = lambda ok: {
        "bss_log_clim": {"value": 0.7, "lo": 0.57, "hi": 0.8},
        "n_events_pooled": 118,
        "status": "pasa hindcast (espera la temporada prospectiva)" if ok else "Experimental",
    }
    return {"regions": {r: {str(lead): cell(lead <= 7) for lead in rm.LEADS} for r in rd.REGIONS}}


def promote_log(tmp_path: Path, leads=(1,), region="cordillera_norte") -> st.StatusLog:
    log = st.StatusLog(tmp_path / "status.jsonl", clock=lambda: NOW)
    log.append_many(
        [
            {
                "variable": "p_dia_riesgo",
                "region": region,
                "lead": lead,
                "model_version": VERSION,
                "from_state": st.EXPERIMENTAL,
                "to_state": st.OUTLOOK,
                "reason": "prueba",
                "evidence": {},
                "approved_by": "tester",
                "approved_on": "2026-01-01",
            }
            for lead in leads
        ]
    )
    return log


def cells(o: dict):
    return [(r["id"], c) for r in o["regions"] for c in r["leads"]]


# --- tests ------------------------------------------------------------------------------------------


def test_three_regions_ten_leads_and_header(tmp_path):
    reg = make_registry(tmp_path)
    o = fo.build_outlook(reg.read())
    assert [r["id"] for r in o["regions"]] == list(rd.REGIONS)
    assert all([c["lead"] for c in r["leads"]] == list(range(1, 11)) for r in o["regions"])
    assert o["variable"] == "p_dia_riesgo" and o["issue_date"] == "2026-01-01"
    assert o["gefs_init_date"] == "2026-01-01" and o["issued_at"].startswith("2026-01-01T10:17")
    assert o["model"] == {
        "name": "logistica",
        "version": VERSION,
        "training_period": "2000-01-01/2014-12-31",
        "baseline": "climatologia",
    }
    assert o["inputs"] and o["inputs"][0]["latency_hours"] == 0.0
    assert o["regions"][0]["threshold_mm"] == 12.5
    first = o["regions"][0]["leads"][0]
    assert first["valid_date"] == "2026-01-01" and first["interval_level"] == 0.9
    assert (
        first["clim_p"] == pytest.approx(0.05) and first["clim_low"] <= 0.05 <= first["clim_high"]
    )
    assert first["p_low"] <= first["p"] <= first["p_high"]
    json.dumps(o, allow_nan=False)


def test_cap_above_cap_and_p_shown(tmp_path):
    o = fo.build_outlook(make_registry(tmp_path).read())
    for _, c in cells(o):
        assert c["p_shown"] == min(c["p"], c["prob_cap"])
        assert c["above_cap"] == (c["p"] > c["prob_cap"])
    north = {c["lead"]: c for c in o["regions"][0]["leads"]}
    assert north[1]["prob_cap"] == 1.0 and not north[1]["above_cap"]
    assert north[9]["prob_cap"] == 0.3 and north[9]["above_cap"] and north[9]["p_shown"] == 0.3
    dry = {c["lead"]: c for c in o["regions"][1]["leads"]}
    assert not any(c["above_cap"] for c in dry.values())
    assert "tope" in o["cap_rule"].lower()


def test_no_caps_means_null_cap_and_p_shown_equals_p(tmp_path):
    reg = PredictionRegistry(tmp_path / "r.jsonl", clock=lambda: NOW)
    rm.emit(reg, toy_model(), SHA, snapshot(tmp_path / "s.parquet"), TODAY)
    for _, c in cells(fo.build_outlook(reg.read())):
        assert c["prob_cap"] is None and not c["above_cap"] and c["p_shown"] == c["p"]


def test_estado_defaults_experimental_and_promoted_case(tmp_path):
    recs = make_registry(tmp_path).read()
    assert {c["estado"] for _, c in cells(fo.build_outlook(recs))} == {"Experimental"}
    log = promote_log(tmp_path)
    o = fo.build_outlook(recs, status_log=log)
    promoted = [(r, c["lead"]) for r, c in cells(o) if c["estado"] == "Perspectiva de riesgo"]
    assert promoted == [("cordillera_norte", 1)]
    # a promotion of another frozen version does not count
    other = st.StatusLog(tmp_path / "o.jsonl", clock=lambda: NOW)
    other.append_many(
        [
            {
                "variable": "p_dia_riesgo",
                "region": "cordillera_norte",
                "lead": 1,
                "model_version": "riskday-log-v1-zzzz",
                "from_state": st.EXPERIMENTAL,
                "to_state": st.OUTLOOK,
                "reason": "x",
            }
        ]
    )
    assert {c["estado"] for _, c in cells(fo.build_outlook(recs, status_log=other))} == {
        "Experimental"
    }


def test_history_insufficient_without_scores_and_filled_with_scores(tmp_path):
    recs = make_registry(tmp_path).read()
    for _, c in cells(fo.build_outlook(recs)):
        assert c["history"] == {
            "n": 0,
            "n_events": 0,
            "n_events_pooled": None,
            "skill": None,
            "ci": None,
            "pod": None,
            "far": None,
            "insufficient": True,
        }
    o = fo.build_outlook(recs, scores=scores_payload())
    h = o["regions"][0]["leads"][0]["history"]
    assert h == {
        "n": 40,
        "n_events": 12,
        "n_events_pooled": 14,
        "skill": 0.18,
        "ci": [-0.05, 0.37],
        "pod": 0.6,
        "far": 0.4,
        "insufficient": False,
    }
    thin = o["regions"][0]["leads"][1]["history"]
    assert thin["insufficient"] and thin["n"] == 9 and thin["skill"] is None and thin["ci"] is None
    assert thin["n_events_pooled"] == 5
    assert o["regions"][1]["leads"][0]["history"]["n"] == 0  # no row for that region


def test_hindcast_from_gate_and_null_when_missing(tmp_path):
    recs = make_registry(tmp_path).read()
    h = fo.build_outlook(recs, gate=gate())["regions"][0]["leads"][0]["hindcast"]
    assert h == {
        "bss_clim": 0.7,
        "ci": [0.57, 0.8],
        "verdict": "pasa hindcast (espera la temporada prospectiva)",
        "n_events_pooled": 118,
    }
    assert fo.build_outlook(recs)["regions"][0]["leads"][0]["hindcast"] is None


def test_notices_and_links(tmp_path):
    o = fo.build_outlook(make_registry(tmp_path).read())
    assert o["notices"]["official"].startswith("No es una alerta oficial. Ante una diferencia")
    assert o["notices"]["audience"] == "Para usuarios técnicos; no indica qué hacer."
    assert set(o["notices"]["states"]) == {"Experimental", "Perspectiva de riesgo"}
    assert [x["label"] for x in o["official_links"]] == [
        "SMN — avisos",
        "AIC",
        "Defensa Civil Neuquén",
    ]
    assert all(x["url"].startswith("https://") for x in o["official_links"])
    assert o["history_note"].startswith("Historial prospectivo")
    assert "color" not in json.dumps(o).lower()


def test_latest_issue_date_wins(tmp_path):
    reg = make_registry(tmp_path)
    nxt = NOW + timedelta(days=1)
    reg2 = PredictionRegistry(reg.path, clock=lambda: nxt)
    rm.emit(reg2, toy_model(), SHA, snapshot(tmp_path / "n.parquet", init=nxt.date()), nxt.date())
    o = fo.build_outlook(reg2.read())
    assert o["issue_date"] == "2026-01-02" and o["gefs_init_date"] == "2026-01-02"


def test_empty_registry_raises(tmp_path):
    with pytest.raises(fo.OutlookError):
        fo.build_outlook([])


@pytest.mark.parametrize(
    ("leads", "expected"),
    [((), "Experimental"), ((1,), "mixto")],
)
def test_manifest_outlook_status_experimental_and_mixed(tmp_path, leads, expected):
    reg = make_registry(tmp_path)
    log = promote_log(tmp_path, leads) if leads else None
    out = fo.build(reg.path, tmp_path / "out", status=log.path if log else None)
    m = load_manifest(out / "manifest.json")
    assert m.outlook_status == expected and m.id == "forecast-outlook" and m.kind == "series"
    assert m.files == ["outlook.json"] and m.period == "2026-01-01/2026-01-10"


def test_manifest_status_promoted_when_every_cell_promoted(tmp_path):
    reg = make_registry(tmp_path)
    log = st.StatusLog(tmp_path / "all.jsonl", clock=lambda: NOW)
    for region in rd.REGIONS:
        promote_log_into(log, region)
    out = fo.build(reg.path, tmp_path / "out", status=log.path)
    assert load_manifest(out / "manifest.json").outlook_status == "Perspectiva de riesgo"


def promote_log_into(log: st.StatusLog, region: str) -> None:
    log.append_many(
        [
            {
                "variable": "p_dia_riesgo",
                "region": region,
                "lead": lead,
                "model_version": VERSION,
                "from_state": st.EXPERIMENTAL,
                "to_state": st.OUTLOOK,
                "reason": "prueba",
            }
            for lead in rm.LEADS
        ]
    )


def test_manifest_without_outlook_status_stays_valid(tmp_path):
    m = {
        "id": "x",
        "title": "T",
        "kind": "series",
        "source": "S",
        "period": "2000-01-01/2001-01-01",
        "license": "L",
        "updated_at": "2026-01-01T00:00:00Z",
        "files": ["a.json"],
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(m))
    assert load_manifest(p).outlook_status is None
    p.write_text(json.dumps({**m, "outlook_status": "rojo"}))
    with pytest.raises(ValueError):
        load_manifest(p)


def test_cli_outlook_layer(tmp_path):
    reg = make_registry(tmp_path)
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(gate()))
    out = tmp_path / "layer"
    r = CliRunner().invoke(
        app,
        ["forecast", "outlook-layer", "--registry", str(reg.path), "--gate", str(gate_path),
         "--out", str(out)],
    )  # fmt: skip
    assert r.exit_code == 0, r.output
    o = json.loads((out / "outlook.json").read_text())
    assert o["regions"][0]["leads"][0]["hindcast"]["bss_clim"] == 0.7
    missing = CliRunner().invoke(
        app,
        ["forecast", "outlook-layer", "--registry", str(reg.path), "--gate", str(tmp_path / "no"),
         "--out", str(out)],
    )  # fmt: skip
    assert missing.exit_code == 1


def test_real_gate_file_feeds_the_layer(tmp_path):
    if not F58.is_file():
        pytest.skip("reports/05/F5.8.json not present")
    out = fo.build(make_registry(tmp_path).path, tmp_path / "o", gate=F58)
    o = json.loads((out / "outlook.json").read_text())
    assert o["regions"][0]["leads"][0]["hindcast"]["n_events_pooled"] > 0


# --- seasonal and high-flow blocks (extras) -------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
F62 = ROOT / "reports/06/F6.2.json"
F69 = ROOT / "reports/06/F6.9.json"
F67 = ROOT / "backend/data/forecast/f67-gr4j/report/F6.7.json"
MODELS = ROOT / "backend/models/seasonal-v1"
needs_reports = pytest.mark.skipif(
    not (F62.is_file() and F69.is_file() and F67.is_file() and MODELS.is_dir()),
    reason="reports/06 and seasonal models not present",
)


def seasonal_fetchers(state_ok: bool = True) -> emit.Fetchers:
    oni = pd.DataFrame({"date": pd.to_datetime(["2025-10-01"]), "oni": [-0.6], "phase": ["nina"]})

    def rain(first, last):
        return {b: pd.Series(2.0, index=pd.date_range(first, last)) for b in (12004, 12010)}

    def state(t):
        if not state_ok:
            return None
        return {b: {"sd": 0.001, "swvl1": 0.19, "swvl2": 0.19, "swvl3": 0.2} for b in data.BOXES}

    return emit.Fetchers(state=state, rain_daily=rain, oni=lambda: oni)


def seasonal_registry(tmp_path: Path, state_ok: bool = True) -> PredictionRegistry:
    reg = make_registry(tmp_path)  # NOW is 2026-01-01, a 1st: the seasonal issue day too
    emit.emit_seasonal(reg, TODAY, seasonal_fetchers(state_ok), MODELS, F62)
    return reg


def build_extras(tmp_path: Path, reg, **kw) -> dict:
    kw.setdefault("today", reg.now().date())
    out = fo.build(reg.path, tmp_path / "layer", extras_blocks=True, **kw)
    return json.loads(
        (out / "outlook.json").read_text(encoding="utf-8"),
        parse_constant=lambda c: pytest.fail(f"non-strict JSON constant {c}"),
    )


def lead_of(o: dict, target: str, k: int) -> dict:
    t = next(t for t in o["seasonal"]["targets"] if t["id"] == target)
    return next(x for x in t["leads"] if x["lead_months"] == k)


@needs_reports
def test_seasonal_grouped_by_target_and_lead(tmp_path):
    o = build_extras(tmp_path, seasonal_registry(tmp_path), f62=F62)
    s = o["seasonal"]
    assert s["available"] and s["estado"] == "Experimental" and s["issue_date"] == "2026-01-01"
    assert s["source"] and s["period"].startswith("2026-01-01/")
    assert [t["id"] for t in s["targets"]] == ["rain", "ar", "flow12004", "flow12010"]
    assert all([x["lead_months"] for x in t["leads"]] == [1, 2, 3, 4, 5, 6] for t in s["targets"])
    cell = lead_of(o, "flow12004", 1)
    assert [m["name"] for m in cell["models"]] == list(extras.MODEL_ORDER)
    by = {m["name"]: m for m in cell["models"]}
    assert by["logistica"]["emitted"] and by["climatologia"]["emitted"]
    assert sum(by["logistica"]["p_terciles"].values()) == pytest.approx(1)
    assert by["climatologia"]["p_terciles"]["medio"] == pytest.approx(1 / 3)
    assert by["logistica"]["model_version"].startswith("seasonal-v1") and by["logistica"]["inputs"]
    assert by["logistica"]["training_period"].count("/") == 1
    assert all("latency_hours" in i for i in by["logistica"]["inputs"])
    e = cell["edges"]
    assert e["unit"] == "m3/s" and e["lower_up_to"] <= e["upper_from"]
    assert cell["target_month"] == "2026-01"
    assert lead_of(o, "rain", 1)["models"][2]["emitted"]  # persistence only for rain
    ar_pers = next(m for m in lead_of(o, "ar", 1)["models"] if m["name"] == "persistencia")
    assert not ar_pers["emitted"] and "ríos atmosféricos" in ar_pers["reason"]
    assert "236" in by["persistencia"]["reason"]
    no_model = next(m for m in lead_of(o, "rain", 1)["models"] if m["name"] == "logistica")
    assert not no_model["emitted"] and "hindcast" in no_model["reason"]


@needs_reports
def test_seasonal_skill_and_notes_from_f62(tmp_path):
    o = build_extras(tmp_path, seasonal_registry(tmp_path), f62=F62)
    sk = lead_of(o, "rain", 1)["skill"]
    assert sk["beats_climatology"] is False and len(sk["ci95"]) == 2 and sk["rpss_vs_clim"] < 0.01
    assert "Hindcast estacional" in sk["source"]
    sk2 = lead_of(o, "flow12004", 1)["skill"]
    assert sk2["beats_climatology"] is True and sk2["ci95"][0] > 0
    notes = {t["id"]: t["note"] for t in o["seasonal"]["targets"]}
    assert notes["rain"] == "Sin skill sobre la climatología en el hindcast: solo referencias."
    assert notes["ar"] == notes["rain"]
    assert "anticipación de 1, 2, 3" in notes["flow12004"]


@needs_reports
def test_seasonal_without_f62_has_no_skill(tmp_path):
    o = build_extras(tmp_path, seasonal_registry(tmp_path), f62=tmp_path / "no.json")
    assert lead_of(o, "rain", 1)["skill"] is None
    assert o["seasonal"]["targets"][0]["note"].startswith("Sin verificar")


@needs_reports
def test_seasonal_skipped_model_carries_reason(tmp_path):
    o = build_extras(tmp_path, seasonal_registry(tmp_path, state_ok=False), f62=F62)
    cell = lead_of(o, "flow12004", 1)
    m = next(m for m in cell["models"] if m["name"] == "logistica")
    assert m == {
        "name": "logistica",
        "label": extras.MODEL_LABELS["logistica"],
        "emitted": False,
        "reason": emit.MODEL_SKIPPED,
    }
    assert any(x["emitted"] for x in cell["models"])  # baselines remain


def test_seasonal_empty_registry_note_computes_next_first(tmp_path):
    reg = make_registry(tmp_path, now=datetime(2026, 11, 23, 10, 17, tzinfo=UTC))
    o = build_extras(tmp_path, reg)
    assert o["seasonal"] == {
        "available": False,
        "note": "La primera emisión estacional sale el 1 de diciembre de 2026 (día 1 de cada mes).",
    }
    (tmp_path / "b").mkdir()
    reg2 = make_registry(tmp_path / "b", now=datetime(2026, 12, 15, 9, 0, tzinfo=UTC))
    assert "1 de enero de 2027" in build_extras(tmp_path / "b", reg2)["seasonal"]["note"]
    assert extras.next_first_of_month(date(2026, 3, 1)) == date(2026, 3, 1)
    assert extras.next_first_of_month(date(2026, 3, 2)) == date(2026, 4, 1)


@needs_reports
def test_highflow_f67_and_f69_extraction(tmp_path):
    o = build_extras(tmp_path, make_registry(tmp_path), f67=F67, f69=F69)
    h = o["highflow"]
    assert (
        h["estado"] == "Experimental" and h["note"] == "Prueba retrospectiva, no es un pronóstico"
    )
    f67 = h["f67"]
    assert f67["available"] and f67["estado"] == "Experimental" and f67["period"] and f67["source"]
    assert f67["independent_years"]["required"] == 20 and 0 < f67["independent_years"]["n"] < 20
    assert f67["independent_years"]["n"] == len(f67["independent_years"]["years"])
    main = f67["variants"]["main"]
    assert "mediana de los máximos anuales" in main["threshold_rule"]
    lead1 = main["models"]["gr4j"]["1"]
    raw = json.loads(F67.read_text())["metrics"]["main"]["gr4j"]["1"]
    assert lead1["n_floods"] == raw["n_floods"] and lead1["rises"] == raw["rises"]
    assert lead1["coverage_ci95"] == raw["coverage_ci"] and lead1["coverage_nominal"] == 0.9
    assert lead1["bss_clim_ci95"] == [raw["bss_clim"]["lo"], raw["bss_clim"]["hi"]]
    assert lead1["verdict"] == "no pasa"
    f69 = h["f69"]
    assert f69["available"] and f69["period"] and f69["source"] and f69["gefs_period"]
    p95 = f69["thresholds"]["p95"]
    pooled = p95["era5"]["vs_climatology"]["pooled"]
    assert pooled["bss"] == pytest.approx(0.0882, abs=1e-3) and pooled["ci95"][0] > 0
    assert set(p95["era5"]["vs_persistence"]["stations"]) == {"12004", "12010", "12012"}
    assert list(p95["gefs_by_lead"]) == [str(k) for k in range(1, 11)]
    assert p95["gefs_by_lead"]["1"]["vs_climatology"]["pooled"]["ci_excludes_0"] is False


def test_highflow_missing_files(tmp_path):
    o = build_extras(tmp_path, make_registry(tmp_path), f67=tmp_path / "a", f69=tmp_path / "b")
    assert o["highflow"]["f67"] == {"available": False}
    assert o["highflow"]["f69"] == {"available": False}
    assert extras.build_highflow(None, {})["f69"] == {"available": False}


def test_extras_off_keeps_outlook_unchanged(tmp_path):
    out = fo.build(make_registry(tmp_path).path, tmp_path / "plain")
    o = json.loads((out / "outlook.json").read_text())
    assert "seasonal" not in o and "highflow" not in o


@needs_reports
def test_cli_outlook_layer_extras_flags(tmp_path):
    reg = seasonal_registry(tmp_path)
    g = tmp_path / "gate.json"
    g.write_text(json.dumps(gate()))
    out = tmp_path / "layer"
    base = [
        "forecast",
        "outlook-layer",
        "--registry",
        str(reg.path),
        "--gate",
        str(g),
        "--out",
        str(out),
    ]
    r = CliRunner().invoke(app, [*base, "--f62", str(F62), "--f67", str(F67), "--f69", str(F69)])
    assert r.exit_code == 0, r.output
    o = json.loads((out / "outlook.json").read_text())
    assert o["seasonal"]["available"]
    assert o["highflow"]["f67"]["available"] and o["highflow"]["f69"]["available"]
    assert load_manifest(out / "manifest.json").files == ["outlook.json"]
    gone = [str(tmp_path / n) for n in ("x", "y", "z")]  # missing optional reports do not fail
    r = CliRunner().invoke(app, [*base, "--f62", gone[0], "--f67", gone[1], "--f69", gone[2]])
    assert r.exit_code == 0, r.output
    assert json.loads((out / "outlook.json").read_text())["highflow"]["f67"] == {"available": False}


# --- fixture for the web e2e ------------------------------------------------------------------------


def write_fixture(tmp_path: Path, dest: Path) -> Path:
    reg = make_registry(tmp_path)
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps(scores_payload()))
    g = tmp_path / "gate.json"
    g.write_text(json.dumps(gate()))
    log = promote_log(tmp_path, leads=(1,))
    out = fo.build(reg.path, dest, scores=scores, status=log.path, gate=g)
    m = out / "manifest.json"
    d = json.loads(m.read_text())
    d.update(
        source="GEFS operativo y ERA5T falsos de prueba; modelo logístico de juguete (datos falsos de prueba)",
        license="CC0",
    )
    m.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


EXTRA_KEYS = ("seasonal", "highflow")


def test_fixture_matches_builder(tmp_path):
    # The e2e fixture also carries small hand-made `seasonal` and `highflow` blocks (EXTRA_KEYS) for the
    # viewer tests; the builder part is compared without them, and a rewrite keeps them.
    extra = {
        k: v
        for k, v in json.loads((FIXTURE / "outlook.json").read_text(encoding="utf-8")).items()
        if k in EXTRA_KEYS
    }
    if os.environ.get("FORECAST_OUTLOOK_WRITE_FIXTURE"):
        (tmp_path / "w").mkdir()
        w = write_fixture(tmp_path / "w", FIXTURE)
        o = json.loads((w / "outlook.json").read_text(encoding="utf-8")) | extra
        (w / "outlook.json").write_text(
            json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    (tmp_path / "c").mkdir()
    out = write_fixture(tmp_path / "c", tmp_path / "fx")
    assert (FIXTURE / "manifest.json").read_text(encoding="utf-8") == (
        out / "manifest.json"
    ).read_text(encoding="utf-8"), (
        "manifest.json is stale: rerun with FORECAST_OUTLOOK_WRITE_FIXTURE=1"
    )
    fixed = json.loads((FIXTURE / "outlook.json").read_text(encoding="utf-8"))
    built = json.loads((out / "outlook.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in fixed.items() if k not in EXTRA_KEYS} == built, (
        "outlook.json is stale: rerun with FORECAST_OUTLOOK_WRITE_FIXTURE=1"
    )
    o = json.loads((FIXTURE / "outlook.json").read_text(encoding="utf-8"))
    assert any(c["above_cap"] for _, c in cells(o))
    assert any(c["history"]["n"] > 0 for _, c in cells(o))
    assert load_manifest(FIXTURE / "manifest.json").outlook_status == "mixto"


@needs_reports
def test_seasonal_out_of_range_passthrough(tmp_path):
    o = build_extras(tmp_path, seasonal_registry(tmp_path), f62=F62)
    m = next(m for m in lead_of(o, "flow12004", 1)["models"] if m["name"] == "logistica")
    assert m["out_of_range"] == []  # fixture values are inside the trained range

    def state(t):
        s = {b: {"sd": 0.001, "swvl1": 0.19, "swvl2": 0.19, "swvl3": 0.2} for b in data.BOXES}
        s[12004]["swvl1"] = 0.45
        return s

    f = seasonal_fetchers()
    f.state = state
    (tmp_path / "x").mkdir()
    reg = make_registry(tmp_path / "x")
    emit.emit_seasonal(reg, TODAY, f, MODELS, F62)
    o2 = build_extras(tmp_path / "x", reg, f62=F62)
    m2 = next(m for m in lead_of(o2, "flow12004", 1)["models"] if m["name"] == "logistica")
    (item,) = m2["out_of_range"]
    assert item["feature"] == "swvl1_12004" and item["value"] == 0.45 and item["unit"] == "m³/m³"
    assert item["min"] < item["max"] < 0.45 and item["label"].startswith("agua de suelo capa 1")
    assert "out_of_range" not in next(
        m for m in lead_of(o2, "flow12004", 1)["models"] if m["name"] == "climatologia"
    )


@needs_reports
def test_seasonal_old_record_is_unknown(tmp_path):
    old = tmp_path / "models"  # models frozen before feature_range: records carry no fuera_de_rango
    old.mkdir()
    for p in MODELS.glob("*.json"):
        d = json.loads(p.read_text())
        d.pop("feature_range", None)
        (old / p.name).write_text(json.dumps(d))
    (tmp_path / "r").mkdir()
    reg = make_registry(tmp_path / "r")
    emit.emit_seasonal(reg, TODAY, seasonal_fetchers(), old, F62)
    o = build_extras(tmp_path / "r", reg, f62=F62)
    m = next(m for m in lead_of(o, "flow12004", 1)["models"] if m["name"] == "logistica")
    assert m["out_of_range"] is None

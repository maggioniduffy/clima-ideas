"""Viewer layer ``forecast-outlook`` (plan/06, F6.6, backend half): the latest frozen risk-day prediction.

Output in ``<out>/`` (default ``data/processed/forecast-outlook``), kind ``series``:

- ``manifest.json``  layer manifest, with the optional ``outlook_status`` ("Experimental" | "Perspectiva de riesgo" |
  "mixto"): "Perspectiva de riesgo" only when EVERY shown region-lead is promoted, "mixto" when some are.
- ``outlook.json``   the newest issue date of model ``logistica`` of variable ``p_dia_riesgo`` in the registry with
  its ``climatologia`` pair: per region and GEFS lead the probability, its 90 % interval, the climatological
  probability, the cap in force, the state from the status log (default "Experimental"), the retrospective
  hindcast (F5.8.json) and the prospective history (scores/latest.json). Nothing is invented: a missing source
  gives ``null`` (history: ``n`` 0 and ``insufficient`` true). No colors or levels in the data.
  With ``extras`` (the CLI) it also carries ``seasonal`` (latest F6.2 emission, "Experimental") and ``highflow``
  (retrospective F6.7/F6.9 evidence); see ``forecast_outlook_extras``. The risk-day fields do not change.

Not an official warning (plan/06 "Avisos obligatorios"): the notices and official links travel in the JSON.

Run: ``clima-nqn forecast outlook-layer``.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from clima_nqn.forecast import status as st
from clima_nqn.forecast.registry import PredictionRecord, PredictionRegistry
from clima_nqn.forecast.riskday_model import CAP_RULE, VAR_RISK
from clima_nqn.layers import forecast_outlook_extras as extras
from clima_nqn.layers.manifest import LayerManifest
from clima_nqn.stages.hindcast.riskday import REGION_LABELS, REGIONS

LAYER_ID = "forecast-outlook"
TITLE = "Perspectiva de día de riesgo (1–10 días)"
SOURCE = (
    "Pronóstico GEFS operativo (NOAA, NODD) con regresión logística propia congelada (ajuste 2000–2014); "
    "verificación con ERA5T (Copernicus)"
)
LICENSE = (
    "GEFS: NODD de NOAA, abierta con atribución. ERA5 y ERA5T (Copernicus): CC BY 4.0. "
    "Modelo y verificación: propios. No es una alerta oficial."
)
VARIABLE_LABEL = "Día de riesgo (lluvia regional ≥ p95 de 2000–2011)"
MODEL = "logistica"
BASELINE = "climatologia"
OUTLOOK_NAME = "outlook.json"
HISTORY_NOTE = (
    "Historial prospectivo: solo predicciones del registro, puntuadas al llegar ERA5T (≈ 7 días)."
)
NOTICES = {
    "official": (
        "No es una alerta oficial. Ante una diferencia, siga los avisos de SMN, AIC y Defensa Civil."
    ),
    "audience": "Para usuarios técnicos; no indica qué hacer.",
    "states": {
        st.EXPERIMENTAL: (
            "Experimental: todavía no pasó la compuerta de evidencia (hindcast, temporada prospectiva "
            "completa y aprobación). Se muestra para que se pueda verificar, no como perspectiva."
        ),
        st.OUTLOOK: (
            "Perspectiva de riesgo: pasó la compuerta de evidencia para esta región y anticipación "
            "(hindcast, temporada prospectiva completa y aprobación). Sigue siendo una probabilidad con "
            "incertidumbre, no una alerta."
        ),
    },
}
OFFICIAL_LINKS = [
    {"label": "SMN — avisos", "url": "https://www.smn.gob.ar/alertas"},
    {"label": "AIC", "url": "https://www.aic.gob.ar"},
    # Same URL as the published hindcast panel (HindcastPanel.tsx); not reachable from the dev sandbox: sin verificar.
    {"label": "Defensa Civil Neuquén", "url": "https://www.neuquen.gov.ar/defensacivil/"},
]
INTERVAL_LEVEL = 0.9


class OutlookError(Exception):
    """The registry has nothing to show."""


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and math.isfinite(x) else None


def _history(scores: dict | None, region: str, lead: int) -> dict:
    empty = {
        "n": 0,
        "n_events": 0,
        "n_events_pooled": None,
        "skill": None,
        "ci": None,
        "pod": None,
        "far": None,
        "insufficient": True,
    }
    if not scores:
        return empty
    row = next(
        (
            r
            for r in scores.get("table", [])
            if r.get("model") == MODEL
            and r.get("variable") == VAR_RISK
            and str(r.get("station")) == region
            and int(r.get("lead", -1)) == lead
        ),
        None,
    )
    if row is None:
        return empty
    lo, hi = _num(row.get("skill_ci_low")), _num(row.get("skill_ci_high"))
    pooled = (scores.get("events_pooled") or {}).get(VAR_RISK, {}).get(str(lead), {}).get("overall")
    return {
        "n": int(row.get("n") or 0),
        "n_events": int(row.get("n_events") or 0),
        "n_events_pooled": None if pooled is None else int(pooled),
        "skill": _num(row.get("skill")),
        "ci": None if lo is None or hi is None else [lo, hi],
        "pod": _num(row.get("pod")),
        "far": _num(row.get("far")),
        "insufficient": row.get("status") != "ok",
    }


def _hindcast(gate: dict | None, region: str, lead: int) -> dict | None:
    r = ((gate or {}).get("regions") or {}).get(region, {}).get(str(lead))
    if not r:
        return None
    b = r["bss_log_clim"]
    return {
        "bss_clim": _num(b["value"]),
        "ci": [_num(b["lo"]), _num(b["hi"])],
        "verdict": r["status"],
        "n_events_pooled": r["n_events_pooled"],
    }


def _lead_of(r: PredictionRecord) -> int:
    return int(r.details.get("gefs_lead", r.lead_days + 1))


def build_outlook(
    records: list[PredictionRecord],
    scores: dict | None = None,
    status_log: st.StatusLog | None = None,
    gate: dict | None = None,
) -> dict:
    """The ``outlook.json`` payload from registry records (see module docs)."""
    risk = [r for r in records if r.variable == VAR_RISK and r.model_name == MODEL]
    if not risk:
        raise OutlookError(f"no {MODEL} {VAR_RISK} predictions in the registry")
    day = max(r.issued_at.date() for r in risk)
    log_recs = {_key(r): r for r in risk if r.issued_at.date() == day}
    clim = {
        _key(r): r
        for r in records
        if r.variable == VAR_RISK and r.model_name == BASELINE and r.issued_at.date() == day
    }
    first = next(iter(log_recs.values()))
    state_rows = status_log.read() if status_log is not None else []

    regions = []
    for region in [x for x in REGIONS if any(k[0] == x for k in log_recs)]:
        leads = []
        for (reg, lead), r in sorted(log_recs.items(), key=lambda kv: kv[0][1]):
            if reg != region:
                continue
            c = clim.get((reg, lead))
            cap = _num(r.details.get("prob_cap"))
            p = r.value
            leads.append(
                {
                    "lead": lead,
                    "valid_date": r.valid_date.isoformat(),
                    "p": p,
                    "p_low": r.interval_low,
                    "p_high": r.interval_high,
                    "interval_level": r.interval_level,
                    "clim_p": c.value if c else _num(r.details.get("clim_prob")),
                    "clim_low": c.interval_low if c else None,
                    "clim_high": c.interval_high if c else None,
                    "prob_cap": cap,
                    "above_cap": cap is not None and p > cap,
                    "p_shown": p if cap is None else min(p, cap),
                    "estado": st.current_state(state_rows, VAR_RISK, reg, lead, r.model_version),
                    "hindcast": _hindcast(gate, reg, lead),
                    "history": _history(scores, reg, lead),
                }
            )
        thr = log_recs[(region, leads[0]["lead"])].details.get("threshold_mm")
        regions.append(
            {
                "id": region,
                "label": REGION_LABELS.get(region, region),
                "threshold_mm": _num(thr),
                "leads": leads,
            }
        )
    seen: dict[str, float] = {}
    for i in first.inputs:
        seen[i.name] = max(seen.get(i.name, 0.0), i.latency_hours)
    return {
        "variable": VAR_RISK,
        "variable_label": VARIABLE_LABEL,
        "issue_date": day.isoformat(),
        "issued_at": max(r.issued_at for r in log_recs.values()).isoformat(timespec="seconds"),
        "gefs_init_date": first.details.get("gefs_init_date"),
        "model": {
            "name": MODEL,
            "version": first.model_version,
            "training_period": first.training_period,
            "baseline": BASELINE,
        },
        "inputs": [{"name": n, "latency_hours": h} for n, h in seen.items()],
        "cap_rule": first.details.get("prob_cap_rule") or CAP_RULE,
        "notices": NOTICES,
        "official_links": OFFICIAL_LINKS,
        "regions": regions,
        "history_note": HISTORY_NOTE,
    }


def _key(r: PredictionRecord) -> tuple[str, int]:
    return (r.region, _lead_of(r))


def outlook_status(outlook: dict) -> str:
    """ "Perspectiva de riesgo" if every shown cell is promoted, "Experimental" if none, else "mixto"."""
    states = [c["estado"] for reg in outlook["regions"] for c in reg["leads"]]
    if states and all(s == st.OUTLOOK for s in states):
        return st.OUTLOOK
    if any(s == st.OUTLOOK for s in states):
        return "mixto"
    return st.EXPERIMENTAL


def _read_json(path: Path | str | None) -> dict | None:
    """A JSON report, or None if the path is unset, missing or not strict JSON."""
    if not path or not Path(path).is_file():
        return None
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def build(
    registry: Path | str,
    out_dir: Path | str,
    scores: Path | str | None = None,
    status: Path | str | None = None,
    gate: Path | str | None = None,
    f62: Path | str | None = None,
    f67: Path | str | None = None,
    f69: Path | str | None = None,
    extras_blocks: bool = False,
    today: date | None = None,
) -> Path:
    reg = PredictionRegistry(Path(registry))
    reg.verify()
    scores_d = None
    if scores and Path(scores).is_file():
        scores_d = json.loads(Path(scores).read_text(encoding="utf-8"))
    log = st.StatusLog(Path(status)) if status else None
    if log is not None:
        log.verify()
    gate_d = json.loads(Path(gate).read_text(encoding="utf-8")) if gate else None
    records = reg.read()
    outlook = build_outlook(records, scores_d, log, gate_d)
    if extras_blocks:
        outlook["seasonal"] = extras.build_seasonal(
            records, _read_json(f62), today or datetime.now(UTC).date()
        )
        outlook["highflow"] = extras.build_highflow(_read_json(f67), _read_json(f69))
    valid = [c["valid_date"] for r in outlook["regions"] for c in r["leads"]]
    manifest = LayerManifest(
        id=LAYER_ID,
        title=TITLE,
        kind="series",
        source=SOURCE,
        period=f"{outlook['issue_date']}/{max(valid)}",
        license=LICENSE,
        updated_at=datetime.fromisoformat(outlook["issued_at"]).astimezone(UTC),
        files=[OUTLOOK_NAME],
        outlook_status=outlook_status(outlook),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / OUTLOOK_NAME).write_text(
        json.dumps(outlook, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return out_dir

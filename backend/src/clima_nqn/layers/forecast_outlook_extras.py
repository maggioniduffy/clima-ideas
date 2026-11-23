"""Extra blocks of the ``forecast-outlook`` layer (plan/06 F6.2 seasonal and F6.7/F6.9 high flow).

Both go inside ``outlook.json`` as new top-level keys (``seasonal``, ``highflow``); the risk-day fields do not change.

- ``seasonal``: the newest seasonal emission of the registry (variable ``seas_p_tercil_alto``), grouped by target and
  lead month, always "Experimental", with the F6.2 hindcast skill per target and lead. Without a record:
  ``{"available": false, "note": ...}`` with the next 1st of the month computed from the build date.
- ``highflow``: retrospective evidence only (F6.7 leave-one-flood-out, F6.9 conditional climatology), read from the
  report files. A missing file gives ``{"available": false}``. It is a retrospective test, not a forecast.

Nothing is invented: absent values are ``null``. No levels, colors or advice in the data.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from clima_nqn.forecast.registry import PredictionRecord
from clima_nqn.stages.seasonal import emit

ESTADO = "Experimental"
RETRO_NOTE = "Prueba retrospectiva, no es un pronóstico"
REQUIRED_INDEPENDENT = 20
NOMINAL_COVERAGE = 0.90
MONTHS_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
# Phase/task ids ("F6.2") that older registry records or reports may carry in their text; the viewer shows
# plain Spanish instead. Ordered: specific phrases first, then a generic cleanup of parenthesised ids.
_PLAIN = (
    (re.compile(r"espera prospectiva F6\.8"), "espera la temporada prospectiva"),
    (re.compile(r"catálogo de ríos atmosféricos \(F1\.3\)"), "catálogo de ríos atmosféricos (ERA5)"),
    (re.compile(r"catálogo F1\.3"), "catálogo de ríos atmosféricos (ERA5)"),
    (re.compile(r"\(F6\.1\)"), "(medido el 2026-11-22)"),
    (re.compile(r"[Hh]indcast (?:de )?F6\.2"), "hindcast estacional"),
    (re.compile(r"\(F\d\.\d+, "), "("),
    (re.compile(r" ?\(F\d\.\d+\)"), ""),
)


def plain_text(text: str) -> str:
    """Replace internal phase ids in a text by plain Spanish (see ``_PLAIN``)."""
    for rx, repl in _PLAIN:
        text = rx.sub(repl, text)
    return text


def plain_tree(obj: Any) -> Any:
    """``plain_text`` over every string value of a JSON-like structure (keys untouched)."""
    if isinstance(obj, str):
        return plain_text(obj)
    if isinstance(obj, list):
        return [plain_tree(v) for v in obj]
    if isinstance(obj, dict):
        return {k: plain_tree(v) for k, v in obj.items()}
    return obj


MODEL_LABELS = {
    "climatologia": "Climatología (1/3 por tercil)",
    "analogos_enso": "Análogos ENSO",
    "persistencia": "Persistencia",
    "logistica": "Modelo logístico",
}
MODEL_ORDER = tuple(MODEL_LABELS)
NO_MODEL_REASON = "no supera a la climatología en el hindcast estacional: no se emite"
SEASONAL_SOURCE = (
    "Emisión mensual propia (registro de pronósticos): referencias climatológicas, análogos ENSO (NOAA CPC ONI) y "
    "persistencia con ERA5 (Copernicus C3S, ARCO-ERA5); modelo logístico congelado solo donde supera a la "
    "climatología. Hindcast estacional."
)
F67_SOURCE = (
    "Prueba retrospectiva dejando afuera cada crecida grande: GR4J propio con entradas GEFSv12 "
    "(NOAA, NODD) y caudal SNIH (Red Hidrológica Nacional)."
)
F67_VARIANTS = {
    "main": (
        "Umbral: mediana de los máximos anuales de los años de entrenamiento (proxy del nivel de 2 años), "
        "por estación y partición"
    ),
    "thr_p95": "Sensibilidad. Umbral: p95 provisional del caudal diario de entrenamiento",
    "t_perfect": (
        "Sensibilidad optimista (temperatura perfecta). Umbral: mediana de los máximos anuales de los años "
        "de entrenamiento"
    ),
}
F69_THRESHOLDS = {
    "p95": "Umbral: p95 del caudal diario de toda la serie",
    "annmax_median": "Umbral: mediana de los máximos anuales",
}


def _num(x: Any) -> float | None:
    return (
        float(x)
        if isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)
        else None
    )


def _pair(v: Any) -> list[float | None] | None:
    if not isinstance(v, list | tuple) or len(v) != 2:
        return None
    return [_num(v[0]), _num(v[1])]


def next_first_of_month(today: date) -> date:
    """The first day of the month on or after ``today`` (the day the seasonal emission runs)."""
    if today.day == 1:
        return today
    return date(today.year + (today.month == 12), today.month % 12 + 1, 1)


def _date_es(d: date) -> str:
    return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"


# --- seasonal ------------------------------------------------------------------------------------


def _skill(f62: dict | None, target: str, lead: int) -> dict | None:
    if not f62:
        return None
    v = next(
        (
            x
            for x in f62.get("verdicts", [])
            if x.get("model") == "logit" and x.get("target") == target and x.get("lead") == lead
        ),
        None,
    )
    if v is None:
        return None
    return {
        "metric": "RPSS frente a la climatología",
        "rpss_vs_clim": _num(v.get("rpss_vs_clim")),
        "ci95": _pair(v.get("ci_vs_clim")),
        "beats_climatology": bool(v.get("beats_climatology")),
        "source": "Hindcast estacional, validación temporal",
    }


def _target_note(f62: dict | None, target: str) -> str:
    if not f62:
        return "Sin verificar: falta el hindcast estacional; solo referencias."
    leads = sorted(
        x["lead"]
        for x in f62.get("verdicts", [])
        if x.get("model") == "logit"
        and x.get("target") == target
        and isinstance(x.get("lead"), int)
        and x.get("beats_climatology")
    )
    if not leads:
        return "Sin skill sobre la climatología en el hindcast: solo referencias."
    txt = ", ".join(str(k) for k in leads)
    return (
        f"El modelo supera a la climatología en el hindcast solo con anticipación de {txt} mes(es); "
        "en el resto, solo referencias."
    )


def _missing_reason(name: str, target: str) -> str:
    if name == "analogos_enso":
        return emit.ENSO_SKIP_REASON
    if name == "persistencia":
        key = target if target in emit.PERSIST_SKIP_REASONS else "flow"
        return emit.PERSIST_SKIP_REASONS[key]
    return NO_MODEL_REASON


def _model_entry(name: str, target: str, rec: PredictionRecord | None, skipped: str | None) -> dict:
    if rec is None:
        return {
            "name": name,
            "label": MODEL_LABELS[name],
            "emitted": False,
            "reason": skipped or _missing_reason(name, target),
        }
    lo, hi = rec.interval_low, rec.interval_high
    return {
        "name": name,
        "label": MODEL_LABELS[name],
        "emitted": True,
        "p_terciles": rec.details["p_terciles"],
        "p_superior_interval": None if lo is None or hi is None else [lo, hi],
        "interval_level": rec.interval_level,
        "model_version": rec.model_version,
        "training_period": rec.training_period,
        "inputs": [{"name": i.name, "latency_hours": i.latency_hours} for i in rec.inputs],
    }


def build_seasonal(
    records: list[PredictionRecord], f62: dict | None = None, today: date | None = None
) -> dict:
    """The ``seasonal`` block (see module docs)."""
    seas = [r for r in records if r.variable == emit.VAR]
    if not seas:
        nxt = next_first_of_month(today or date.today())
        return {
            "available": False,
            "note": f"La primera emisión estacional sale el {_date_es(nxt)} (día 1 de cada mes).",
        }
    day = max(r.issued_at.date() for r in seas)
    cur = [r for r in seas if r.issued_at.date() == day]
    by_region = {info["region"]: t for t, info in emit.TARGET_INFO.items()}
    cells: dict[tuple[str, int], dict[str, PredictionRecord]] = {}
    for r in cur:
        t = by_region.get(r.region)
        if t is not None:
            cells.setdefault((t, int(r.details["lead_months"])), {})[r.model_name] = r
    targets = []
    for target, info in emit.TARGET_INFO.items():
        leads = []
        for (t, k), models in sorted(cells.items(), key=lambda kv: kv[0][1]):
            if t != target:
                continue
            any_rec = next(iter(models.values()))
            skipped = next(
                (
                    r.details["model_skipped"]
                    for r in models.values()
                    if r.details.get("model_skipped")
                ),
                None,
            )
            edges = any_rec.details.get("bordes_terciles") or {}
            leads.append(
                {
                    "lead_months": k,
                    "target_month": any_rec.details.get("target_month"),
                    "edges": {
                        "lower_up_to": _num(edges.get("inferior_hasta")),
                        "upper_from": _num(edges.get("superior_desde")),
                        "unit": edges.get("unidad", info["unit"]),
                    },
                    "models": [
                        _model_entry(
                            n, target, models.get(n), skipped if n == "logistica" else None
                        )
                        for n in MODEL_ORDER
                    ],
                    "skill": _skill(f62, target, k),
                }
            )
        if leads:
            targets.append(
                {
                    "id": target,
                    "label": info["label"],
                    "unit": info["unit"],
                    "region": info["region"],
                    "note": _target_note(f62, target),
                    "leads": leads,
                }
            )
    first = cur[0]
    return {
        "available": True,
        "estado": ESTADO,
        "variable": emit.VAR,
        "variable_label": "Probabilidad por tercil (inferior, medio, superior) del mes objetivo",
        "issue_date": day.isoformat(),
        "issued_at": max(r.issued_at for r in cur).isoformat(timespec="seconds"),
        "source": SEASONAL_SOURCE,
        "period": f"{day.isoformat()}/{max(r.valid_date for r in cur).isoformat()}",
        "model_version": emit.VERSION,
        "notices": first.details.get("avisos") or list(emit.AVISOS),
        "targets": targets,
    }


# --- high flow -----------------------------------------------------------------------------------


def _f67_lead(e: dict) -> dict:
    bss = e.get("bss_clim") or {}
    out = {
        "n_floods": e.get("n_floods"),
        "rises": e.get("rises"),
        "rises_frac": _num(e.get("rises_frac")),
        "rises_ci95": _pair(e.get("rises_ci")),
        "coverage": _num(e.get("coverage")),
        "coverage_ci95": _pair(e.get("coverage_ci")),
        "coverage_nominal": NOMINAL_COVERAGE,
        "bss_clim": _num(bss.get("bss")),
        "bss_clim_ci95": [_num(bss.get("lo")), _num(bss.get("hi"))],
        "verdict": "pasa" if e.get("passes") else "no pasa",
    }
    if "bss_vs_gr4j" in e:
        b = e["bss_vs_gr4j"] or {}
        out["bss_vs_gr4j"] = _num(b.get("bss"))
        out["bss_vs_gr4j_ci95"] = [_num(b.get("lo")), _num(b.get("hi"))]
    return out


def build_f67(f67: dict | None) -> dict:
    if not f67 or "metrics" not in f67:
        return {"available": False}
    years = sorted({f["hydro_year"] for f in f67.get("floods", []) if f.get("included")})
    ctx = f67.get("context") or {}
    variants = {}
    for v, rule in F67_VARIANTS.items():
        models = f67["metrics"].get(v) or {}
        entry = {
            "threshold_rule": rule,
            "models": {
                m: {
                    str(k): _f67_lead(e)
                    for k, e in sorted(leads.items(), key=lambda kv: int(kv[0]))
                }
                for m, leads in models.items()
                if m != "shown" and isinstance(leads, dict)
            },
        }
        if entry["models"]:
            variants[v] = entry
    return {
        "available": True,
        "estado": ESTADO,
        "note": RETRO_NOTE,
        "source": F67_SOURCE,
        "period": (ctx.get("forcing_period") or "").replace(" to ", "/") or None,
        "independent_years": {"n": len(years), "required": REQUIRED_INDEPENDENT, "years": years},
        "n_floods": sum(1 for f in f67.get("floods", []) if f.get("included")),
        "variants": variants,
        "report_note": f67.get("note"),
    }


def _bss(e: dict | None) -> dict | None:
    if not e:
        return None
    return {
        "n": e.get("n"),
        "n_exceed": e.get("n_exceed"),
        "bss": _num(e.get("bss")),
        "ci95": [_num(e.get("ci_lo")), _num(e.get("ci_hi"))],
        "ci_excludes_0": e.get("ci_excludes_0"),
        "status": e.get("status"),
    }


def _vs(block: dict) -> dict:
    """{"clim": {...}, "pers": {...}} -> per reference, pooled and per station."""
    out = {}
    for ref, key in (("vs_climatology", "clim"), ("vs_persistence", "pers")):
        by = block.get(key) or {}
        out[ref] = {
            "pooled": _bss(by.get("pooled")),
            "stations": {s: _bss(e) for s, e in by.items() if s != "pooled"},
        }
    return out


def build_f69(f69: dict | None) -> dict:
    if not f69 or "results" not in f69:
        return {"available": False}
    src = f69.get("sources") or {}
    stations = (src.get("flow") or {}).get("stations") or {}
    gefs = f69.get("gefs") or {}
    thresholds = {}
    for thr, rule in F69_THRESHOLDS.items():
        main = (f69["results"].get(thr) or {}).get("main")
        if not main:
            continue
        thresholds[thr] = {
            "threshold_rule": rule,
            "threshold_m3s": {
                s: _num(v) for s, v in (f69.get("thresholds_all_data", {}).get(thr) or {}).items()
            },
            "era5": _vs(main),
            "gefs_by_lead": {
                str(k): {"n_events": v.get("n_events"), **_vs(v.get("gefs") or {})}
                for k, v in sorted((gefs.get("leads") or {}).items(), key=lambda kv: int(kv[0]))
            },
        }
    return {
        "available": True,
        "estado": ESTADO,
        "note": RETRO_NOTE,
        "source": (
            "Climatología condicional de caudal alto: "
            f"eventos {(src.get('events') or {}).get('source')}; caudal {(src.get('flow') or {}).get('source')}; "
            f"IVT pronosticado: {gefs.get('source')}"
        ),
        "period": (src.get("events") or {}).get("period"),
        "gefs_period": gefs.get("period"),
        "n_events": f69.get("n_events"),
        "stations": {
            s: {"name": v.get("name"), "period": v.get("period")} for s, v in stations.items()
        },
        "thresholds": thresholds,
    }


def build_highflow(f67: dict | None, f69: dict | None) -> dict:
    """The ``highflow`` block: ``{"f67": ..., "f69": ...}``, each ``{"available": false}`` if its file is missing."""
    return {"estado": ESTADO, "note": RETRO_NOTE, "f67": build_f67(f67), "f69": build_f69(f69)}

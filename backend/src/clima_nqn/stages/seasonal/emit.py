"""Monthly seasonal emission to the forecast registry (F6.2 second part), always "Experimental".

Issue on the 1st of month M, 00 UTC; lead k = 1..6 targets month M+k-1 (as in F6.2). Per target (cordillera
rain box 12004, AR count, mean flow 12004 and 12010) and lead the registry gets, each as one record whose
``value`` is P(upper tercile) and whose ``details`` hold the 3 tercile probabilities:

- ``climatologia``: 1/3 each, with the empirical tercile edges in physical units;
- ``analogos_enso``: training frequencies of the same issue month, lead and ONI phase (ONI of month M-3);
- ``persistencia``: tercile of the last full month at issue. Only rain (box 12004, ERA5T month M-2).
  AR persistence needs the F1.3 catalog (retrospective, not operational) and flow persistence needs SNIH
  flow of month M-1, which has a ~236-day lag (F6.1): both skipped, the reason goes in ``details``;
- ``logistica``: the frozen multinomial logistic (``models/seasonal-v1/<target>.json``) ONLY for the
  target/lead with ``beats_climatology`` true in ``reports/06/F6.2.json``.

Registry encoding (backward compatible, no registry change): variable ``seas_p_tercil_alto``, region = target
name, ``lead_days`` = days from the issue date to the first day of the target month (lead 1 -> 0; the
registry's ``valid_date`` = issue date + lead_days = first day of the target month), and
``details.lead_months`` = k. The daily scorer finds no ``threshold_*`` in ``details`` and leaves these rows
"pending"; scoring seasonal records is a later step.

State inputs (snow depth and soil water, ERA5 0.25 deg via ARCO) are sampled at 00 UTC of issue - 5 d, the
latency assumed in F6.2. If that hour is not in the store the model is skipped (baselines only) and the
records say ``model_skipped: "entradas no disponibles"``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from clima_nqn.forecast.registry import (
    InputSource,
    PredictionDraft,
    PredictionRecord,
    PredictionRegistry,
    hash_inputs,
)
from clima_nqn.forecast.riskday_model import wilson
from clima_nqn.stages.seasonal import data, fetch, model

MODELS_DIR = Path("models/seasonal-v1")
F62_JSON = Path("../reports/06/F6.2.json")
VAR = "seas_p_tercil_alto"
ESTADO = "Experimental"
VERSION = "seasonal-v1"
MODEL_SKIPPED = "entradas no disponibles"
RAIN_WINDOW_DAYS = 90
PERSIST_RAIN_REGION = "lluvia-cordillera-12004"

# target -> registry region, label, unit, input boxes
TARGET_INFO: dict[str, dict[str, str]] = {
    "rain": {"region": PERSIST_RAIN_REGION, "label": "lluvia mensual en la cordillera (caja 12004)",
             "unit": "mm/mes"},
    "ar": {"region": "rios-atmosfericos-mes", "label": "cantidad de ríos atmosféricos por mes",
           "unit": "eventos/mes"},
    "flow12004": {"region": "caudal-medio-12004", "label": "caudal medio mensual, estación 12004",
                  "unit": "m3/s"},
    "flow12010": {"region": "caudal-medio-12010", "label": "caudal medio mensual, estación 12010",
                  "unit": "m3/s"},
}  # fmt: skip

AVISOS = (
    (
        "No es una alerta oficial. Ante una diferencia, siga los avisos de SMN "
        "(https://www.smn.gob.ar/alertas), AIC (https://www.aic.gob.ar) y Defensa Civil "
        "(https://www.neuquen.gov.ar/defensacivil/)."
    ),
    (
        "Estado: Experimental. Perspectiva estacional por terciles (inferior, medio, superior) para "
        "usuarios técnicos; no indica qué hacer."
    ),
    (
        "Probabilidad junto a la climatológica (1/3 por tercil); la incertidumbre es la distribución de "
        "los tres terciles. Historial de aciertos: solo el hindcast de F6.2; n prospectivo = 0 (sin verificar)."
    ),
    (
        "Entradas: ERA5 (Copernicus C3S) vía ARCO-ERA5, 0,25°, cajas de la cuenca alta aproximadas (sin "
        "verificar); ONI de NOAA CPC; historia de caudal SNIH y catálogo de ríos atmosféricos (F1.3) hasta "
        "el período de entrenamiento."
    ),
)


class SeasonalEmitError(Exception):
    """The emission is refused (non-1st issue date, missing reference, ...)."""


# --- reference (frozen, committed) --------------------------------------------------------------


def build_reference(inp: data.Inputs, out: Path = MODELS_DIR / "reference.json") -> dict:
    """Freeze what the baselines need at issue time without the 1980-2025 inputs: per target, the sorted
    training values per target calendar month (tercile edges) and the ENSO-analog and empirical class
    counts. Computed with the F6.2 definitions on all years (same samples as the final models)."""
    ref: dict[str, Any] = {
        "version": VERSION,
        "tercile_rule": "mid-rank: p=(n_below+0.5 n_equal)/n per calendar month; low p<1/3, high p>2/3",
        "input_hashes": inp.hashes,
        "targets": {},
    }
    for target in data.MAIN_TARGETS:
        S = data.build_samples(inp, target)
        idx = np.arange(len(S))
        y, _ = model.fold_labels(S, idx, idx)
        tm = pd.DatetimeIndex(np.unique(S.meta["target_month"].values))
        vals = S.series.reindex(tm).dropna()
        cls, _ = model.class_labels(S.series, tm, vals.index, vals.values)
        clim_emp = {
            str(m): np.bincount(cls[(vals.index.month == m) & (cls >= 0)], minlength=3).tolist()
            for m in range(1, 13)
        }
        im = S.meta["issue"].dt.month.values
        enso: dict[str, list[int]] = {}
        for i in np.flatnonzero((y >= 0) & (S.meta["phase"].values != "")):
            key = f"{im[i]}|{S.meta['lead'].values[i]}|{S.meta['phase'].values[i]}"
            enso.setdefault(key, [0, 0, 0])[y[i]] += 1
        ref["targets"][target] = {
            "training_target_months": [str(tm.min().date()), str(tm.max().date())],
            "tercile_reference": {
                str(m): sorted(vals[vals.index.month == m].tolist()) for m in range(1, 13)
            },
            "clim_emp_counts": clim_emp,
            "enso_counts": enso,
        }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ref, indent=1, sort_keys=True, default=float) + "\n")
    return ref


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- inputs at issue (injectable) ---------------------------------------------------------------


@dataclass
class Fetchers:
    """Everything that touches the network. ``state`` returns {box: {sd, swvl1..3}} for the sampled hour or
    None if that hour is not in the store; ``rain_daily`` returns {box: daily mm Series} (NaN = missing)."""

    state: Callable[[pd.Timestamp], dict[int, dict[str, float]] | None]
    rain_daily: Callable[[pd.Timestamp, pd.Timestamp], dict[int, pd.Series]]
    oni: Callable[[], pd.DataFrame]
    era5t_latest: Callable[[], pd.Timestamp | None] = lambda: None  # for the record only


def _arco_area(boxes) -> tuple[float, float, float, float]:
    return (
        max(b[1] for b in boxes.values()) + 0.5, min(b[2] for b in boxes.values()) - 0.5,
        min(b[0] for b in boxes.values()) - 0.5, max(b[3] for b in boxes.values()) + 0.5,
    )  # fmt: skip


def arco_fetchers(oni: Callable[[], pd.DataFrame], opener=None) -> Fetchers:
    """Fetchers on the ARCO-ERA5 store (anonymous). Sampling mirrors ``fetch.py`` and ``forcing.py``."""
    from concurrent.futures import ThreadPoolExecutor

    from clima_nqn.io import era5, forcing, snow

    opener = opener or era5.open_arco
    boxes = snow.UPSTREAM_BOXES
    area = _arco_area(boxes)
    store: list = []

    def raw():
        if not store:
            store.append(era5._retry(opener, 3, 10, "open"))
        return store[0]

    def state(t: pd.Timestamp):
        vals: dict[int, dict[str, float]] = {b: {} for b in boxes}
        for name, short in fetch.ARCO_VARS.items():
            try:
                lazy = raw()[[name]].sel(time=[t])
                ds = era5.crop_to_area(lazy, area, {name: short}).load()
            except Exception:  # noqa: BLE001  (hour beyond the store, network): treated as unavailable
                return None
            for b, box in boxes.items():
                v = float(forcing.box_mean(ds[short], box)[0])
                if not np.isfinite(v):
                    return None
                vals[b][short] = v
        return vals

    def rain_daily(first: pd.Timestamp, last: pd.Timestamp):
        """Daily box precipitation (mm) for days first..last (UTC; day D = hours D 01:00..D+1 00:00)."""
        times = pd.date_range(first + pd.Timedelta(hours=1), last + pd.Timedelta(days=1), freq="h")
        ds = era5.crop_to_area(raw()[["total_precipitation"]], area, {"total_precipitation": "tp"})

        def one(t):
            return era5._retry(lambda: ds["tp"].sel(time=t).load(), 3, 10, f"tp {t}")

        with ThreadPoolExecutor(max_workers=16) as pool:
            fields = list(pool.map(one, times))
        da = __import__("xarray").concat(fields, dim="time").assign_coords(time=times)
        days = pd.date_range(first, last, freq="D")
        out = {}
        for b in (12004, 12010):
            hourly = forcing.box_mean(da, boxes[b]) * 1000.0
            out[b] = forcing._daily(hourly, times, "sum", shift_hours=1).reindex(days)
        return out

    def latest() -> pd.Timestamp | None:
        v = raw().attrs.get("valid_time_stop_era5t")
        return pd.Timestamp(v) + pd.Timedelta(hours=23) if v else None

    return Fetchers(state=state, rain_daily=rain_daily, oni=oni, era5t_latest=latest)


# --- frozen logistic ----------------------------------------------------------------------------


def logistic_probs(
    meta: dict, feats: dict[str, float], issue: pd.Timestamp, lead: int
) -> np.ndarray:
    """Probabilities (low, mid, high) of the frozen multinomial logistic, same transform as ``model.Prep``."""
    stats = meta["anomaly_stats"][str(issue.month)]
    x = []
    for c in meta["features"]:
        if c == "lead":
            x.append((lead - 3.5) / 1.7)
        else:
            mu, sd = stats[c]
            x.append((feats[c] - mu) / sd)
    z = np.asarray(meta["coef"]) @ np.asarray(x) + np.asarray(meta["intercept"])
    e = np.exp(z - z.max())
    return e / e.sum()


# --- helpers ------------------------------------------------------------------------------------


def target_month(issue: pd.Timestamp, k: int) -> pd.Timestamp:
    return (issue.to_period("M") + k - 1).to_timestamp()


def edges(ref_t: dict, month: pd.Timestamp) -> tuple[float, float]:
    v = np.asarray(ref_t["tercile_reference"][str(month.month)], float)
    q = np.quantile(v, [1 / 3, 2 / 3])
    return float(q[0]), float(q[1])


def _period(ref_t: dict) -> str:
    a, b = (pd.Timestamp(x) for x in ref_t["training_target_months"])
    return f"{a.date()}/{(b + pd.offsets.MonthEnd(0)).date()}"


def _beats(f62: dict) -> dict[tuple[str, int], dict]:
    out = {}
    for v in f62["verdicts"]:
        if v["model"] == "logit" and isinstance(v["lead"], int) and v["beats_climatology"]:
            out[(v["target"], v["lead"])] = v
    return out


def _count_prob(counts: list[int]) -> tuple[np.ndarray, int]:
    c = np.asarray(counts, float)
    return (c + model.LAPLACE) / (c.sum() + 3 * model.LAPLACE), int(c.sum())


def _interval(p_high: float, counts: list[int] | None) -> tuple[float, float]:
    if counts is None or sum(counts) == 0:
        return p_high, p_high
    n = int(sum(counts))
    lo, hi = wilson(counts[2], n)
    return min(lo, p_high), max(hi, p_high)


def _add(
    drafts: list[PredictionDraft],
    common: dict,
    base: dict,
    name: str,
    p3,
    counts: list[int] | None,
    inputs: list[InputSource],
    in_hash: str,
    extra: dict,
    version: str,
    interval: tuple[float, float] | None = None,
) -> None:
    p3 = np.asarray(p3, float)
    lo, hi = interval or _interval(float(p3[2]), counts)
    terciles = {"inferior": float(p3[0]), "medio": float(p3[1]), "superior": float(p3[2])}
    drafts.append(
        PredictionDraft(
            **common,
            value=float(p3[2]),
            interval_low=lo,
            interval_high=hi,
            model_name=name,
            model_version=version,
            inputs=inputs,
            inputs_sha256=in_hash,
            details={**base, **extra, "p_terciles": terciles},
        )
    )


@dataclass
class EmitResult:
    records: list[PredictionRecord] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # what was not emitted and why
    arco_latest: str | None = None


# --- emission -----------------------------------------------------------------------------------


def emit_seasonal(
    reg: PredictionRegistry,
    issue: date,
    fetchers: Fetchers,
    models_dir: Path = MODELS_DIR,
    f62_path: Path = F62_JSON,
) -> EmitResult:
    """Emit the monthly Experimental seasonal records for ``issue`` (the 1st of a month, the registry's today)."""
    if issue.day != 1:
        raise SeasonalEmitError(f"la emisión estacional es el día 1 de cada mes (recibido {issue})")
    now = reg.now()
    if now.date() != issue:
        raise SeasonalEmitError(
            f"la fecha de emisión {issue} no es el hoy del registro ({now.date()})"
        )
    models_dir = Path(models_dir)
    ref_path = models_dir / "reference.json"
    if not ref_path.is_file():
        raise SeasonalEmitError(f"falta la referencia congelada {ref_path} (seasonal reference)")
    ref = json.loads(ref_path.read_text())
    ref_sha = _sha(ref_path)
    f62 = json.loads(Path(f62_path).read_text())
    beats = _beats(f62)
    iss = pd.Timestamp(issue)
    res = EmitResult()
    latest = fetchers.era5t_latest()
    res.arco_latest = str(latest) if latest is not None else None
    now_ts = pd.Timestamp(now).tz_localize(None)

    # ONI of the season centred on M-3 (nominal publication M-1, before the issue)
    oni_df = fetchers.oni()
    oni_center = (iss.to_period("M") - data.ONI_LAG_MONTHS).to_timestamp()
    row = oni_df[oni_df["date"] == oni_center]
    oni_v = float(row["oni"].iloc[0]) if len(row) else None
    phase = (
        str(row["phase"].iloc[0]) if len(row) and "phase" in row.columns else
        (None if oni_v is None else "nino" if oni_v >= 0.5 else "nina" if oni_v <= -0.5 else "neutral")
    )  # fmt: skip
    if oni_v is None:
        res.skipped["analogos_enso"] = f"sin ONI del mes {oni_center:%Y-%m} a la fecha de emisión"

    # state hour and rain windows (only if something needs them)
    sample = fetch.sample_time(iss)
    state = fetchers.state(sample) if beats else None
    if state is not None:  # the sampled hour (available_on) must not be after the issue date
        data.assert_available(pd.DataFrame({"state": [sample]}), [iss])
    rain: dict[int, pd.Series] | None = None
    last_day = iss - pd.Timedelta(days=fetch.LATENCY_DAYS + 1)
    try:
        rain = fetchers.rain_daily(last_day - pd.Timedelta(days=RAIN_WINDOW_DAYS + 4), last_day)
    except Exception as e:  # noqa: BLE001
        res.skipped["lluvia ERA5T"] = f"{type(e).__name__}: {e}"
    if rain is not None:  # the last rain day (I-6) ends at the sampled hour: same availability
        data.assert_available(pd.DataFrame({"rain": [sample]}), [iss])

    drafts: list[PredictionDraft] = []
    for target, tinfo in TARGET_INFO.items():
        ref_t = ref["targets"][target]
        spec = data.TARGETS[target]
        period = _period(ref_t)
        last_train = pd.Timestamp(ref_t["training_target_months"][1]) + pd.offsets.MonthEnd(0)
        # persistence (rain only)
        persist_class, persist_note, persist_val = None, None, 0.0
        if target == "rain":
            pm = (iss.to_period("M") - data.persistence_months(spec["kind"])).to_timestamp()
            d = None if rain is None else rain[12004].reindex(
                pd.date_range(pm, pm + pd.offsets.MonthEnd(0))
            )  # fmt: skip
            if d is None or d.isna().any():
                persist_note = "lluvia ERA5T del mes M-2 incompleta o no disponible"
            else:
                ref_v = np.asarray(ref_t["tercile_reference"][str(pm.month)], float)
                persist_class = int(model.tercile_classes(ref_v, np.array([d.sum()]))[0][0])
                persist_val = float(d.sum())
        elif target == "ar":
            persist_note = "persistencia de ríos atmosféricos: el catálogo F1.3 es retrospectivo, sin entrada operativa"
        else:
            persist_note = (
                "persistencia de caudal: el caudal SNIH del mes M-1 llega con ~236 días de rezago (F6.1), "
                "no está disponible a la emisión"
            )
        if persist_class is None:
            res.skipped[f"persistencia/{target}"] = persist_note

        for k in data.LEADS:
            tm = target_month(iss, k)
            lo_e, hi_e = edges(ref_t, tm)
            lead_days = (tm - iss).days
            common = {
                "issue_date": now,
                "variable": VAR,
                "region": tinfo["region"],
                "lead_days": lead_days,
                "valid_date": tm.date(),
                "kind": "probability",
                "interval_level": 0.9,
                "training_period": period,
            }
            emp = ref_t["clim_emp_counts"][str(tm.month)]
            base = {
                "estado": ESTADO,
                "objetivo": target,
                "objetivo_descripcion": tinfo["label"],
                "unidad": tinfo["unit"],
                "lead_months": k,
                "target_month": f"{tm:%Y-%m}",
                "issue_month": f"{iss:%Y-%m}",
                "clim_prob": 1 / 3,
                "clim_emp_counts": emp,
                "tercil_regla": ref["tercile_rule"],
                "bordes_terciles": {"inferior_hasta": lo_e, "superior_desde": hi_e, "unidad": tinfo["unit"]},
                "periodo_entrenamiento": period,
                "avisos": list(AVISOS),
                "historial": {"n_prospectivo": 0, "nota": "sin verificar; solo hindcast F6.2"},
                "reference_sha256": ref_sha,
            }  # fmt: skip
            model_wanted = (target, k) in beats
            skip_models: dict[str, str] = {}
            feats: dict[str, float] | None = None
            if model_wanted:
                meta = json.loads((models_dir / f"{target}.json").read_text())
                need_rain = "rain30" in meta["features"]
                if state is not None:
                    feats = {f"{v}_{b}": state[b][v] for b in data.BOXES for v in data.STATE_VARS}
                if feats is not None and need_rain:
                    d = None if rain is None else rain[spec["box"]]
                    r30 = np.nan if d is None else data._window_sum(d, iss, 30)
                    r90 = np.nan if d is None else data._window_sum(d, iss, RAIN_WINDOW_DAYS)
                    feats = (
                        {**feats, "rain30": r30, "rain90": r90} if np.isfinite(r30 + r90) else None
                    )
                if feats is None:
                    skip_models["model_skipped"] = MODEL_SKIPPED
                    res.skipped[f"logistica/{target}/{k}"] = MODEL_SKIPPED
            hist_src = InputSource(
                name=f"Historia mensual de la variable objetivo, referencia congelada {ref_path.name} "
                f"({period})",
                latency_hours=max(0.0, (now_ts - last_train).total_seconds() / 3600),
            )

            add = partial(_add, drafts, common, {**base, **skip_models})

            # climatology 1/3
            add("climatologia", [1 / 3] * 3, None, [hist_src],
                hash_inputs({"ref": ref_sha, "t": target, "k": k}), {}, f"{VERSION}-clim-{ref_sha[:8]}")  # fmt: skip
            # ENSO analogs
            if oni_v is not None and phase:
                counts = ref_t["enso_counts"].get(f"{iss.month}|{k}|{phase}", [0, 0, 0])
                p3, n = _count_prob(counts)
                oni_src = InputSource(
                    name="NOAA CPC ONI (serie operativa; temporada centrada en M-3)",
                    latency_hours=max(0.0, (now_ts - oni_center).total_seconds() / 3600),
                )
                add("analogos_enso", p3, counts, [hist_src, oni_src],
                    hash_inputs({"ref": ref_sha, "oni": oni_v, "phase": phase, "t": target, "k": k}),
                    {"fase_enso": phase, "oni": oni_v, "n_analogos": n, "conteos_terciles": counts},
                    f"{VERSION}-enso-{ref_sha[:8]}")  # fmt: skip
            # persistence
            if persist_class is not None:
                p3 = np.eye(3)[persist_class]
                src = InputSource(
                    name="ERA5T (ARCO-ERA5) lluvia diaria, caja 12004, mes M-2",
                    latency_hours=float((now_ts - (iss - pd.Timedelta(days=fetch.LATENCY_DAYS))).total_seconds() / 3600),
                )  # fmt: skip
                add("persistencia", p3, None, [hist_src, src],
                    hash_inputs({"ref": ref_sha, "class": persist_class, "val": persist_val, "k": k}),
                    {"clase_persistida": ["inferior", "medio", "superior"][persist_class],
                     "valor_mes_M-2": persist_val},
                    f"{VERSION}-persist-{ref_sha[:8]}")  # fmt: skip
            # frozen logistic, only where F6.2 says it beats climatology
            if feats is not None:
                mp = models_dir / f"{target}.json"
                p3 = logistic_probs(meta, feats, iss, k)
                v = beats[(target, k)]
                srcs = [hist_src, InputSource(
                    name=f"{fetch.SOURCE}: nieve y humedad del suelo, 00 UTC de emisión - {fetch.LATENCY_DAYS} d",
                    latency_hours=float((now_ts - sample).total_seconds() / 3600))]  # fmt: skip
                if need_rain:
                    srcs.append(InputSource(
                        name="ERA5T (ARCO-ERA5) lluvia diaria de la caja, 30 y 90 días hasta emisión - 6 d",
                        latency_hours=float((now_ts - (iss - pd.Timedelta(days=fetch.LATENCY_DAYS))).total_seconds() / 3600),
                    ))  # fmt: skip
                add("logistica", p3, None, srcs,
                    hash_inputs({"model": _sha(mp), "input_hash": meta["input_hash"], "feats": feats,
                                 "sample": str(sample), "k": k}),
                    {"modelo": meta["kind"], "conjunto": meta["feature_set"],
                     "entradas_entrenamiento_hash": meta["input_hash"],
                     "periodo_entrenamiento_modelo": f"{meta['training_issues'][0]}/{meta['training_issues'][1]}",
                     "hora_muestra_estado": str(sample),
                     "arco_ultima_hora_era5t": res.arco_latest,
                     "intervalo": "sin intervalo propio (modelo determinista); ver hindcast",
                     "hindcast": {"rpss_vs_clim": v["rpss_vs_clim"], "ic95": v["ci_vs_clim"],
                                  "rpss_vs_clim_emp": v["rpss_vs_clim_emp"], "ic95_emp": v["ci_vs_clim_emp"]}},
                    f"{VERSION}-logistica-{meta['input_hash'][:8]}", interval=None)  # fmt: skip

    # idempotent: never re-append what the registry already has for this issue day
    have = {
        (r.model_version, r.variable, r.region, r.lead_days, r.issued_at.date()) for r in reg.read()
    }
    fresh = [
        d for d in drafts if (d.model_version, d.variable, d.region, d.lead_days, issue) not in have
    ]
    res.records = reg.append_many(fresh)
    return res

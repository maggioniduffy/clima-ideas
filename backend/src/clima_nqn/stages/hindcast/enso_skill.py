"""F5.7: skill of the hindcast by ENSO phase, and ENSO as classifier input (F5.3).

Rules fixed before running (see ``RULE_LINES``):

- phase for stratifying skill = phase of the ONI season centered on the VALID date's month (descriptive);
- ONI known at init (classifier input) = season centered on month(init) - 2, init = valid date - (lead - 1);
- Part A (F5.2 cases, one model): ``verify.verify_model`` on each phase subset of cases + El Niño minus La Niña
  difference of the event CRPSS, bootstrapping episodes of each group independently;
- Part B (F5.3 classifier): Brier with / without ENSO inputs, BSS(con vs sin) with event-block CI.

numpy/pandas/xarray; Part B needs the ``ml`` dependency group (via ``riskday``).
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.io import enso as enso_io
from clima_nqn.stages.hindcast import observe as observe_mod
from clima_nqn.stages.hindcast import riskday as rd
from clima_nqn.stages.hindcast import store
from clima_nqn.stages.hindcast import verify as v

PHASES = ("nino", "neutral", "nina")
PHASE_LABELS = {"nino": "El Niño", "neutral": "Neutral", "nina": "La Niña"}
MIN_EVENT_CASES = 20
MIN_CONTIGUOUS_LEADS = 3
THRESHOLD = 5.0

# re-exported mappings (implemented next to the classifier hook in ``riskday``)
oni_available = rd.oni_available
phase_by_valid_date = rd.phase_by_valid_date


# --- Part A: skill by phase of the F5.2 cases ----------------------------------------------------


def case_phases(ds: xr.Dataset, enso: pd.DataFrame) -> np.ndarray:
    """Phase per case from the ONI season centered on the valid date's month."""
    return phase_by_valid_date(pd.to_datetime(ds["valid_date"].values), enso)


def _boot_values(fn, ids: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """``fn(index array)`` over ``n`` resamples of whole episodes (same scheme as ``verify.bootstrap_ci``)."""
    groups = [np.flatnonzero(ids == u) for u in np.unique(ids)]
    vals = np.empty(n)
    for b in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        vals[b] = fn(np.concatenate([groups[i] for i in pick]))
    return vals


def _event_scores(ds: xr.Dataset, obs_box: pd.Series) -> dict:
    """Per-case arrays needed for the event CRPSS: members (case, lead, member), obs, dates, kind."""
    prec = ds["precip_mm"].where(ds["status"] == 0)
    members = v.box_mean(prec).transpose("case", "lead", "member").values
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ens_mean = np.nanmean(members, axis=2)
    vdates = pd.to_datetime(ds["valid_date"].values)
    return {
        "members": members,
        "ens_mean": ens_mean,
        "obs": obs_box.reindex(vdates).to_numpy(dtype="float64"),
        "vdates": vdates,
        "kind": v.str_values(ds["kind"]),
        "leads": [int(x) for x in ds["lead"].values],
    }


def _group_crpss(sc: dict, sel: np.ndarray, li: int):
    """(point, per-index function, episode ids, n) of the event CRPSS of the cases ``sel`` at lead index li."""
    idx = np.flatnonzero(sel & ~np.isnan(sc["ens_mean"][:, li]) & ~np.isnan(sc["obs"]))
    if len(idx) == 0:
        return np.nan, None, None, 0
    ob = sc["obs"][idx]
    crps = v.fair_crps(sc["members"][idx, li], ob)
    ref = v.crps_vs_empirical(ob)

    def fn(i, crps=crps, ref=ref):
        r = ref[i].mean()
        return 1.0 - crps[i].mean() / r if r > 0 else np.nan

    ids = v.episodes(sc["vdates"][idx])
    return fn(np.arange(len(idx))), fn, ids, len(idx)


def _diff_ci(
    a: tuple, b: tuple, n_boot: int, seed: int, alpha: float = 0.05
) -> tuple[float, float, float]:
    """(point, lo, hi) of CRPSS(a) - CRPSS(b); groups resampled independently (own random stream each)."""
    (pa, fa, ia, _), (pb, fb, ib, _) = a, b
    if fa is None or fb is None or np.isnan(pa) or np.isnan(pb):
        return np.nan, np.nan, np.nan
    va = _boot_values(fa, ia, n_boot, np.random.default_rng([seed, 0]))
    vb = _boot_values(fb, ib, n_boot, np.random.default_rng([seed, 1]))
    d = (va - vb)[~(np.isnan(va) | np.isnan(vb))]
    if len(d) == 0:
        return pa - pb, np.nan, np.nan
    lo, hi = np.percentile(d, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(pa - pb), float(lo), float(hi)


def longest_run(leads: list[int], flags: list[bool]) -> int:
    """Longest run of consecutive leads (step 1) whose flag is True."""
    best = cur = 0
    prev = None
    for lead, f in sorted(zip(leads, flags)):
        if f:
            cur = cur + 1 if prev is not None and lead == prev + 1 and cur > 0 else 1
            best = max(best, cur)
        else:
            cur = 0
        prev = lead
    return best


def _stat(df: pd.DataFrame, lead: int, kind: str, metric: str, thr=np.nan) -> dict:
    val, lo, hi, n = v._get(df, "m", lead, kind, metric, thr)
    return {"value": val, "lo": lo, "hi": hi, "n": n}


def part_a(
    ds: xr.Dataset,
    obs_box: pd.Series,
    enso: pd.DataFrame,
    n_boot: int = 1000,
    seed: int = 0,
    min_events: int = MIN_EVENT_CASES,
) -> dict:
    """Skill of one F5.1 model by valid-date ENSO phase (``verify_model`` per subset) and El Niño - La Niña
    difference of the event CRPSS. Phase groups with < ``min_events`` event cases are "sin verificar"."""
    phase = case_phases(ds, enso)
    kind = v.str_values(ds["kind"])
    leads = [int(x) for x in ds["lead"].values]
    sc = _event_scores(ds, obs_box)
    rows: list[dict] = []
    group_cache: dict[tuple[str, int], tuple] = {}
    counts = {}
    for ph in PHASES:
        sel = phase == ph
        counts[ph] = {
            "n_event": int((sel & (kind == "event")).sum()),
            "n_control": int((sel & (kind == "control")).sum()),
        }
        sub = ds.isel(case=np.flatnonzero(sel))
        df = (
            v.verify_model(
                sub, obs_box, (THRESHOLD,), THRESHOLD, n_boot=n_boot, seed=seed, model="m"
            )
            if sel.any()
            else pd.DataFrame(columns=v.COLUMNS)
        )
        for li, lead in enumerate(leads):
            n_ev = _count(df, lead, "event")
            n_ct = _count(df, lead, "control")
            rows.append(
                {
                    "lead": lead,
                    "phase": ph,
                    "n_event": n_ev,
                    "n_control": n_ct,
                    "sin_verificar": n_ev < min_events,
                    "crpss_event": _stat(df, lead, "event", "crpss") if len(df) else _empty(),
                    "ets": _stat(df, lead, "all", "ets", THRESHOLD) if len(df) else _empty(),
                    "auc": _stat(df, lead, "all", "auc", THRESHOLD) if len(df) else _empty(),
                }
            )
            if ph in ("nino", "nina"):
                group_cache[(ph, li)] = _group_crpss(sc, (phase == ph) & (kind == "event"), li)
    diff = []
    for li, lead in enumerate(leads):
        a, b = group_cache[("nino", li)], group_cache[("nina", li)]
        val, lo, hi = _diff_ci(a, b, n_boot, seed)
        sv = a[3] < min_events or b[3] < min_events
        excl = (not sv) and not np.isnan(lo) and (lo > 0 or hi < 0)
        diff.append(
            {
                "lead": lead,
                "n_nino": a[3],
                "n_nina": b[3],
                "crpss_nino": a[0],
                "crpss_nina": b[0],
                "diff": val,
                "lo": lo,
                "hi": hi,
                "sin_verificar": sv,
                "excludes_zero": bool(excl),
            }
        )
    run = longest_run([d["lead"] for d in diff], [d["excludes_zero"] for d in diff])
    return {
        "leads": leads,
        "phase_counts": counts,
        "rows": rows,
        "diff": diff,
        "longest_run": run,
        "signal": run >= MIN_CONTIGUOUS_LEADS,
        "min_events": min_events,
    }


def _count(df: pd.DataFrame, lead: int, kind: str) -> int:
    if not len(df):
        return 0
    x = _stat(df, lead, kind, "n")["value"]
    return 0 if np.isnan(x) else int(x)


def _empty() -> dict:
    return {"value": np.nan, "lo": np.nan, "hi": np.nan, "n": 0}


# --- Part B: ENSO as classifier input ------------------------------------------------------------


def enso_passes(entry: dict) -> bool:
    """ "ENSO aporta" only if BSS(con vs sin) lower CI > 0 for BOTH logistic and LightGBM."""
    ok = True
    for m in ("log", "lgbm"):
        lo = entry.get("models", {}).get(m, {}).get("bss_con_vs_sin", {}).get("lo")
        ok = ok and lo is not None and not np.isnan(lo) and lo > 0
    return bool(ok)


def part_b(
    ctx: dict, enso: pd.DataFrame, n_boot: int = 1000, seed: int = 0, quantile: float = 0.95
) -> dict:
    """Per region x lead on the test period: Brier sin/con ENSO (logistic, LightGBM), BSS(con vs sin) with
    event-block CI, logistic Brier by valid-date phase; count of (region, lead) where ENSO adds skill."""
    res = rd._evaluate(ctx, quantile, ("clim", "log", "lgbm"), n_boot, seed, light=True, enso=enso)
    cells = []
    for r in rd.REGIONS:
        for lead_s, row in res["regions"].get(r, {}).items():
            e = row["enso"]
            cells.append(
                {
                    "region": r,
                    "lead": int(lead_s),
                    "n_days": row["n_days"],
                    "n_risk_days": row["n_risk_days"],
                    "n_events": row["n_events"],
                    "models": e["models"],
                    "by_phase": e["by_phase"],
                    "enso_aporta": enso_passes(e),
                }
            )
    cells.sort(key=lambda c: (rd.REGIONS.index(c["region"]), c["lead"]))
    return {
        "quantile": quantile,
        "thresholds": res["thresholds"],
        "n_events_pooled_test": res["n_events_pooled_test"],
        "cells": cells,
        "n_total": len(cells),
        "n_pass": sum(c["enso_aporta"] for c in cells),
        "lgbm_available": rd.lightgbm_available(),
    }


# --- orchestration -------------------------------------------------------------------------------


def load_oni(path: Path | None) -> tuple[pd.DataFrame, str]:
    text = Path(path).read_text() if path else enso_io.fetch_oni()
    df = enso_io.parse_oni(text)
    return df, ("archivo local" if path else enso_io.ONI_URL)


def resolve_store(path: Path, name: str = "gefs-reforecast") -> Path:
    path = Path(path)
    return path / f"{name}.zarr" if path.is_dir() and not path.name.endswith(".zarr") else path


def run(
    f52_forecasts: Path,
    f52_obs: Path,
    out_dir: Path,
    f53_forecasts: Path | None = None,
    f53_obs: Path | None = None,
    events: Path | None = None,
    oni_path: Path | None = None,
    n_boot: int = 1000,
    seed: int = 0,
    skip_part_b: bool = False,
) -> dict:
    enso, oni_src = load_oni(oni_path)
    ds = store.read_store(resolve_store(f52_forecasts))
    obs_ds = observe_mod.read_obs(Path(f52_obs))
    obs_box = v.box_mean(obs_ds["precip_mm"]).to_series()
    kinds = v.str_values(ds["kind"])
    a = part_a(ds, obs_box, enso, n_boot, seed)
    b = None
    if not skip_part_b:
        if not (f53_forecasts and f53_obs and events):
            raise ValueError(
                "Part B needs --f53-forecasts, --f53-obs and --events (or --skip-part-b)"
            )
        ctx = rd.load_inputs(Path(f53_forecasts), Path(f53_obs), Path(events))
        b = part_b(ctx, enso, n_boot, seed)
    meta = {
        "model": str(ds.attrs.get("model", "gefs-reforecast")),
        "fc_source": str(ds.attrs.get("source", "")),
        "fc_period": str(ds.attrs.get("period", "")),
        "obs_source": str(obs_ds.attrs.get("source", "ERA5")),
        "n_event": int((kinds == "event").sum()),
        "n_control": int((kinds == "control").sum()),
        "oni_source": enso_io.SOURCE,
        "oni_origin": oni_src,
        "oni_url": enso_io.ONI_URL,
        "oni_first": str(enso["date"].min().date()),
        "oni_last": str(enso["date"].max().date()),
        "n_boot": n_boot,
        "seed": seed,
        "part_b_run": b is not None,
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = rd._clean({"part_a": a, "part_b": b, "meta": meta})
    (out / "F5.7.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    (out / "F5.7.md").write_text(render_md(a, b, meta), encoding="utf-8")
    return payload


# --- report --------------------------------------------------------------------------------------

RULE_LINES = [
    (
        "- Fase de ENSO = fase del índice ONI (NOAA CPC): El Niño si ONI ≥ +0,5, La Niña si ONI ≤ −0,5, neutral en "
        "el medio (umbrales de `io.enso`)."
    ),
    (
        "- Fase para estratificar el acierto: estación de 3 meses centrada en el mes de la fecha VÁLIDA (descriptiva, "
        "no es un predictor)."
    ),
    (
        "- ONI disponible al inicializar (entrada del clasificador): inicialización = fecha válida − (L − 1) días; "
        "si cae en el mes m se usa la estación centrada en m − 2 (la última terminada antes de m: julio → AMJ; enero → "
        "OND del año anterior)."
    ),
    (
        "- Parte A (casos F5.2, solo GEFS reforecast; IFS y AIFS tienen pocos casos): `verify_model` sobre cada "
        "subconjunto de casos por fase; por anticipación y fase: casos de evento y de control, CRPSS de eventos, ETS "
        "y AUC a 5 mm sobre todos los casos, con IC 95 % por bootstrap de episodios ({n_boot} remuestreos, semilla "
        "{seed})."
    ),
    (
        "- Diferencia El Niño − La Niña del CRPSS de eventos: IC percentil 95 % de la diferencia de las dos "
        "distribuciones bootstrap, remuestreando episodios de cada grupo de forma independiente. «Señal» solo si el "
        "IC de la diferencia excluye 0 en ≥ {min_run} anticipaciones contiguas; si no, «sin señal detectable»."
    ),
    "- Grupos de fase con < {min_ev} casos de evento → «sin verificar».",
    (
        "- Parte B (clasificador F5.3, cuantil 0,95, test 2015–2019): regresión logística «con ENSO» = entradas de la "
        "logística base + `oni_avail` + `nino_avail` + `nina_avail`; LightGBM «con ENSO» = todas sus entradas + esas "
        "tres. Por región × anticipación: Brier sin y con ENSO, BSS(con vs sin) con IC 95 % por bootstrap de bloques "
        "de eventos (como F5.3), y Brier de la logística sin ENSO por fase de la fecha válida."
    ),
    (
        "- «ENSO aporta» en (región, anticipación) solo si el IC inferior del BSS(con vs sin) es > 0 en la logística "
        "Y en LightGBM; si no, «sin aporte detectable»."
    ),
]


def _stat_str(d: dict, digits: int = 2) -> str:
    return v._ci(_n(d.get("value")), _n(d.get("lo")), _n(d.get("hi")), digits)


def _n(x) -> float:
    return float("nan") if x is None else float(x)


def render_md(part_a: dict, part_b: dict | None, meta: dict) -> str:
    """Spanish report. ``part_a`` / ``part_b`` as returned by ``part_a`` / ``part_b`` (``part_b`` may be None)."""
    L = [
        "# F5.7 — Acierto por fase de ENSO (El Niño / La Niña) y ENSO como entrada del clasificador",
        "",
    ]
    L += ["## Veredicto", "", "<!-- veredicto: lo escribe Opus -->", ""]
    if part_a:
        c = part_a["phase_counts"]
        L.append(
            "- Casos de evento / control por fase (fecha válida): "
            + "; ".join(
                f"{PHASE_LABELS[p]} {c[p]['n_event']} / {c[p]['n_control']}" for p in PHASES
            )
            + "."
        )
        if part_a["signal"]:
            leads = [d["lead"] for d in part_a["diff"] if d["excludes_zero"]]
            L.append(
                f"- Parte A (El Niño − La Niña, CRPSS de eventos): **señal** (IC que excluye 0 en {part_a['longest_run']} "
                f"anticipaciones contiguas; anticipaciones con IC que excluye 0: {', '.join(map(str, leads))})."
            )
        else:
            L.append(
                "- Parte A (El Niño − La Niña, CRPSS de eventos): **sin señal detectable** (mayor racha de anticipaciones "
                f"contiguas con IC que excluye 0: {part_a['longest_run']}; hacen falta {MIN_CONTIGUOUS_LEADS})."
            )
    if part_b:
        L.append(
            f"- Parte B (clasificador): ENSO aporta en {part_b['n_pass']} de {part_b['n_total']} combinaciones "
            "(región, anticipación); con 30 comparaciones al 95 % se esperan ~1–2 por azar (0,05 × 30 = 1,5), así "
            "que un conteo de ese orden no distingue un aporte real del ruido."
        )
    else:
        L.append("- Parte B (clasificador): no corrida.")
    L += ["", "## Fuente y alcance", ""]
    L.append(
        f"- Índice: {meta.get('oni_source', 'NOAA CPC ONI')} ({meta.get('oni_url', '')}; origen: "
        f"{meta.get('oni_origin', '')}); estaciones centradas entre {meta.get('oni_first', '?')} y "
        f"{meta.get('oni_last', '?')}."
    )
    L.append(
        f"- Parte A: {meta.get('model', 'gefs-reforecast')} — {meta.get('fc_source', '')}; "
        f"{meta.get('fc_period', '')}; {meta.get('n_event', '?')} casos de evento y {meta.get('n_control', '?')} "
        f"de control (F5.2). Observado: {meta.get('obs_source', 'ERA5')}."
    )
    L.append(
        "- Parte B: GEFS reforecast de todos los días (F5.3), ERA5 diario, regiones y partición temporal de F5.3."
    )
    L += ["", "## Regla fijada antes de correr", ""]
    for line in RULE_LINES:
        L.append(
            line.replace("{n_boot}", str(meta.get("n_boot", 1000)))
            .replace("{seed}", str(meta.get("seed", 0)))
            .replace("{min_run}", str(MIN_CONTIGUOUS_LEADS))
            .replace("{min_ev}", str(MIN_EVENT_CASES))
        )
    L.append("")
    L += ["## Parte A: acierto por fase de ENSO (casos F5.2)", ""]
    rows = []
    for r in part_a["rows"]:
        rows.append(
            [
                str(r["lead"]),
                PHASE_LABELS[r["phase"]],
                str(r["n_event"]),
                str(r["n_control"]),
                _stat_str(r["crpss_event"]),
                _stat_str(r["ets"]),
                _stat_str(r["auc"]),
                "sin verificar" if r["sin_verificar"] else "",
            ]
        )
    rows.sort(key=lambda x: (int(x[0]), PHASE_LABELS_ORDER.index(x[1])))
    L += v._table(
        [
            "Anticipación (días)",
            "Fase",
            "n evento",
            "n control",
            "CRPSS eventos [IC]",
            "ETS 5 mm [IC]",
            "AUC 5 mm [IC]",
            "Estado",
        ],
        rows,
    )
    L += ["### Diferencia El Niño − La Niña (CRPSS de eventos)", ""]
    rows = []
    for d in part_a["diff"]:
        if d["sin_verificar"]:
            estado = "sin verificar"
        else:
            estado = "IC excluye 0" if d["excludes_zero"] else "IC incluye 0"
        rows.append(
            [
                str(d["lead"]),
                f"{d['n_nino']} / {d['n_nina']}",
                v._f(_n(d["crpss_nino"])),
                v._f(_n(d["crpss_nina"])),
                v._ci(_n(d["diff"]), _n(d["lo"]), _n(d["hi"])),
                estado,
            ]
        )
    L += v._table(
        [
            "Anticipación (días)",
            "n eventos Niño / Niña",
            "CRPSS El Niño",
            "CRPSS La Niña",
            "Diferencia [IC]",
            "Estado",
        ],
        rows,
    )
    L += ["## Parte B: ENSO como entrada del clasificador de día de riesgo (F5.3)", ""]
    if not part_b:
        L += ["No corrida (`--skip-part-b`).", ""]
    else:
        L.append(
            f"Eventos independientes en test (agrupados entre regiones): {part_b['n_events_pooled_test']}. "
            f"Brier menor es mejor; BSS(con vs sin) > 0 significa que agregar ENSO mejora."
        )
        L.append("")
        if not part_b["lgbm_available"]:
            L += ["LightGBM no estaba instalado: «ENSO aporta» no puede cumplirse.", ""]
        for r in rd.REGIONS:
            cells = [c for c in part_b["cells"] if c["region"] == r]
            if not cells:
                continue
            first = cells[0]
            flag = (
                " — **sin verificar** (< 20 eventos)." if first["n_events"] < rd.MIN_EVENTS else "."
            )
            L += [f"### {rd.REGION_LABELS[r]}", ""]
            L.append(
                f"{first['n_days']} días y {first['n_events']} eventos en test; umbral de riesgo "
                f"{v._f(_n(part_b['thresholds'].get(r)))} mm/día{flag}"
            )
            L.append("")
            rows = []
            for c in cells:
                m = c["models"]
                g = lambda mm, k, m=m: m.get(mm, {}).get(k)
                rows.append(
                    [
                        str(c["lead"]),
                        v._f(_n(g("log", "brier_sin")), 4),
                        v._f(_n(g("log", "brier_con")), 4),
                        _stat_str(g("log", "bss_con_vs_sin") or {}, 3),
                        v._f(_n(g("lgbm", "brier_sin")), 4),
                        v._f(_n(g("lgbm", "brier_con")), 4),
                        _stat_str(g("lgbm", "bss_con_vs_sin") or {}, 3),
                        "ENSO aporta" if c["enso_aporta"] else "sin aporte detectable",
                    ]
                )
            L += v._table(
                [
                    "L (días)",
                    "Brier log. sin",
                    "Brier log. con",
                    "BSS log. con vs sin [IC]",
                    "Brier LGBM sin",
                    "Brier LGBM con",
                    "BSS LGBM con vs sin [IC]",
                    "Regla",
                ],
                rows,
            )
            L += [
                f"Brier de la logística sin ENSO por fase de la fecha válida (días / días de riesgo; {rd.REGION_LABELS[r]}):",
                "",
            ]
            rows = []
            for c in cells:
                row = [str(c["lead"])]
                for ph in PHASES:
                    d = c["by_phase"].get(ph)
                    row.append(
                        f"{v._f(_n(d['brier_log']), 4)} ({d['n_days']} / {d['n_risk_days']})"
                        if d
                        else "—"
                    )
                rows.append(row)
            L += v._table(["L (días)", *[PHASE_LABELS[p] for p in PHASES]], rows)
        L += [
            "### Conteo",
            "",
            f"- ENSO aporta en {part_b['n_pass']} de {part_b['n_total']} combinaciones (región, anticipación).",
            (
                "- Con 30 comparaciones al 95 % se esperan ~1–2 por azar (0,05 × 30 = 1,5); además las "
                "anticipaciones vecinas están correlacionadas, así que el conteo no es independiente."
            ),
            "",
        ]
    L += [
        "## Advertencias",
        "",
        "- ENSO es contexto, no predictor (plan, Rumbo 1): se informa como una tabla, sin peso extra en el resto del proyecto.",
        (
            "- F1.8, F1.9, F2.7 y F3.6 no encontraron señal sostenida de ENSO (F2.7: solo concurrente); esto es una "
            "verificación más, con la regla fijada de antemano."
        ),
        (
            "- NOAA CPC revisa el ONI de forma retroactiva: el archivo actual no es exactamente lo que se conocía en cada "
            "fecha de inicialización; la disponibilidad en tiempo real del ONI usado como entrada está sin verificar."
        ),
        (
            "- Pocos eventos por fase (el ENSO persiste por años: pocos episodios independientes); los ICs son anchos y "
            "los grupos con < 20 casos de evento quedan «sin verificar»."
        ),
        (
            "- Parte A: la muestra es 50/50 evento/control por construcción (ETS y AUC no son valores operativos). "
            "ERA5 es un reanálisis, no lluvia medida."
        ),
        (
            "- Esto es retrospectivo y no es un sistema de alerta oficial; los avisos oficiales son del SMN, la AIC y "
            "Defensa Civil."
        ),
        "",
    ]
    return "\n".join(L)


PHASE_LABELS_ORDER = [PHASE_LABELS[p] for p in PHASES]

"""F5.8: evidence gate (criteria 1-3 of ``plan/06-forecast.md``) for the F5.3 "risk day" classifier.

Rule fixed before running (see ``RULE_LINES``): same partition and labels as F5.3 (reused from ``riskday``),
persistence baseline = Markov chain fitted on 2000-2014 only, BSS of the logistic against climatology and against
Markov persistence with a 95 % CI by event-block bootstrap (blocks of risk days of ANY region), verdict per
(region, lead) with the contiguity rule.

numpy/pandas/xarray; scikit-learn and LightGBM are imported lazily through ``riskday``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.stages.hindcast import riskday as rd
from clima_nqn.stages.hindcast import verify as v

REGIONS = rd.REGIONS
MIN_EVENTS = rd.MIN_EVENTS
MIN_BIN_DAYS = 20  # forecast days a reliability bin needs to count for the probability cap
FIT_END = rd.VALID[1]  # Markov / logistic fit data end here (2014-12-31)
STATE_PASS = "pasa hindcast (espera la temporada prospectiva)"
STATE_EXP = "Experimental"
SEASON_MONTHS = (5, 6, 7, 8, 9)


# --- independent events ------------------------------------------------------------------------


def pooled_events(dates, risk: dict[str, np.ndarray]) -> dict:
    """Independent events: runs of consecutive risk days of ANY region are one event, so a system touching
    several regions counts once. Returns ``pooled`` and per-region counts (a region counts the pooled
    events in which it has at least one risk day)."""
    d = pd.to_datetime(np.asarray(dates))
    rk = {r: np.asarray(x, dtype=bool) for r, x in risk.items()}
    any_risk = np.any(list(rk.values()), axis=0)
    blocks = rd.event_blocks(d, any_risk)
    out = {"pooled": len(np.unique(blocks[any_risk]))}
    for r, x in rk.items():
        out[r] = len(np.unique(blocks[x]))
    return out


def events_per_season(dates, risk: dict[str, np.ndarray], months=SEASON_MONTHS) -> dict:
    """Independent events per May-September season: a pooled event belongs to the season of its first day.
    ``n_seasons`` = number of distinct calendar years in ``dates``."""
    d = pd.to_datetime(np.asarray(dates))
    rk = {r: np.asarray(x, dtype=bool) for r, x in risk.items()}
    n_seasons = len(np.unique(d.year))

    def count(mask: np.ndarray) -> int:
        blocks = rd.event_blocks(d, mask)
        first = pd.Series(d[mask]).groupby(blocks[mask]).min()
        return int(first.dt.month.isin(months).sum())

    any_risk = np.any(list(rk.values()), axis=0)
    out: dict = {"n_seasons": n_seasons}
    for name, mask in (("pooled", any_risk), *rk.items()):
        n = count(mask)
        out[name] = {"n_events": n, "per_season": n / n_seasons if n_seasons else float("nan")}
    return out


# --- Markov persistence ------------------------------------------------------------------------


def markov_table(risk: pd.Series, lead: int, fit_end: str | pd.Timestamp = FIT_END) -> np.ndarray:
    """P(risk on valid day V | risk observed on the issue day D = V - lead) by month of V: array (12, 2),
    columns = state of D (0 no risk, 1 risk). ``risk`` is a daily float series (1, 0, NaN = missing).
    Only pairs with V <= ``fit_end`` are used, so nothing after the fit period can enter. A cell without
    pairs falls back to the rate of its state over all months (then to the overall rate)."""
    s = risk.sort_index()
    idx = s.index[s.index <= pd.Timestamp(fit_end)]
    target = s.reindex(idx)
    state = s.reindex(idx - pd.Timedelta(days=int(lead)))
    state.index = idx
    ok = target.notna() & state.notna()
    t = target[ok].to_numpy(dtype=float)
    st = state[ok].to_numpy(dtype=int)
    mo = idx[ok.to_numpy()].month.to_numpy()
    overall = float(t.mean()) if len(t) else 0.0
    table = np.full((12, 2), np.nan)
    for k in (0, 1):
        sk = st == k
        rate_k = float(t[sk].mean()) if sk.any() else overall
        for m in range(1, 13):
            sel = sk & (mo == m)
            table[m - 1, k] = float(t[sel].mean()) if sel.any() else rate_k
    return table


def markov_predict(table: np.ndarray, risk: pd.Series, lead: int, valid_dates) -> np.ndarray:
    """Persistence probability for each valid date from the risk state observed on V - lead
    (missing state -> the mean of the two cells of that month)."""
    d = pd.to_datetime(np.asarray(valid_dates))
    state = risk.reindex(d - pd.Timedelta(days=int(lead))).to_numpy(dtype=float)
    month = d.month.to_numpy() - 1
    p = np.where(
        np.isnan(state), table[month].mean(axis=1), table[month, np.nan_to_num(state).astype(int)]
    )
    return p.astype(float)


def binary_persistence(risk: pd.Series, lead: int, valid_dates) -> np.ndarray:
    """Raw persistence (sensitivity): 1 if the issue day D = V - lead was a risk day, else 0."""
    d = pd.to_datetime(np.asarray(valid_dates))
    return np.nan_to_num(risk.reindex(d - pd.Timedelta(days=int(lead))).to_numpy(dtype=float))


# --- reliability, cap, POD / FAR ----------------------------------------------------------------


def probability_cap(rel: list[dict], min_n: int = MIN_BIN_DAYS) -> float | None:
    """Upper edge of the highest reliability bin with at least ``min_n`` forecast days (max displayable
    probability); None if no bin qualifies."""
    bins = len(rel)
    ok = [b["bin"] for b in rel if b["n"] >= min_n]
    return (max(ok) + 1) / bins if ok else None


def pooled_caps(rel_by_lead: dict[int, list[dict]], min_n: int = MIN_BIN_DAYS) -> dict[int, dict]:
    """Probability cap in force per lead (user decision 2026-11-22).

    For each lead L the reliability bins of the test forecasts of leads L-1, L, L+1 (those present) are pooled
    (day counts summed) and the cap is the upper edge of the highest pooled bin with at least ``min_n`` days; the
    result is then made non-increasing in L (``cap_L = min(cap_1 .. cap_L)``). Returns per lead ``cap_lead`` (old
    per-lead cap, kept for comparison), ``cap_pooled`` (before the monotone step) and ``cap`` (in force). A lead
    without any qualifying pooled bin has no cap (None), and so do all longer leads.
    """
    out: dict[int, dict] = {}
    running: float | None = None
    dead = False
    for lead in sorted(rel_by_lead):
        near = [rel_by_lead[k] for k in (lead - 1, lead, lead + 1) if k in rel_by_lead]
        bins = len(near[0])
        pooled = [{"bin": b, "n": sum(rel[b]["n"] for rel in near)} for b in range(bins)]
        cap_pooled = probability_cap(pooled, min_n)
        if cap_pooled is None:
            dead = True
        if not dead:
            running = cap_pooled if running is None else min(running, cap_pooled)
        out[lead] = {
            "cap_lead": probability_cap(rel_by_lead[lead], min_n),
            "cap_pooled": cap_pooled,
            "cap": None if dead else running,
        }
    return out


def pod_far(p: np.ndarray, y: np.ndarray, thr: float) -> dict:
    """Day-level POD = hits / risk days and FAR = false alarms / forecast-yes days at p >= thr."""
    p, y = np.asarray(p), np.asarray(y)
    yes = p >= thr
    hits = int((yes & (y == 1)).sum())
    fa = int((yes & (y == 0)).sum())
    n_ev = int((y == 1).sum())
    return {
        "thr": float(thr),
        "hits": hits,
        "false_alarms": fa,
        "n_yes": hits + fa,
        "n_risk_days": n_ev,
        "pod": hits / n_ev if n_ev else float("nan"),
        "far": fa / (hits + fa) if hits + fa else float("nan"),
    }


# --- verdict ------------------------------------------------------------------------------------


def lead_passes(ci_clim: dict, ci_ref: dict, n_pooled: int) -> bool:
    """Criterion 1 for one (region, lead): both CI lower bounds > 0 and enough pooled independent events."""

    def pos(c: dict) -> bool:
        lo = c.get("lo")
        return lo is not None and not np.isnan(lo) and lo > 0

    return bool(pos(ci_clim) and pos(ci_ref) and n_pooled >= MIN_EVENTS)


def contiguous(raw: dict[int, bool]) -> dict[int, bool]:
    """Criterion 2: lead L passes only if it passes on its own and every shorter lead passes."""
    out: dict[int, bool] = {}
    ok = True
    for lead in sorted(raw):
        ok = ok and bool(raw[lead])
        out[lead] = ok
    return out


def status(passed: bool) -> str:
    return STATE_PASS if passed else STATE_EXP


# --- evaluation ---------------------------------------------------------------------------------


def _ci(t: tuple[float, float, float]) -> dict:
    return {"value": t[0], "lo": t[1], "hi": t[2]}


def _evaluate_q(ctx: dict, q: float, n_boot: int, seed: int, with_lgbm: bool) -> dict:
    tp = ctx["tp"]
    obs_dates = tp.index
    thr = {r: rd.train_threshold(tp[r], q) for r in REGIONS}
    risk_obs = {r: (tp[r] >= thr[r]).to_numpy() & tp[r].notna().to_numpy() for r in REGIONS}
    risk_f = {
        r: pd.Series(risk_obs[r].astype(float), index=obs_dates).where(tp[r].notna())
        for r in REGIONS
    }
    test_obs = rd.period_mask(obs_dates, rd.TEST)
    any_risk = np.any([risk_obs[r] for r in REGIONS], axis=0)
    blocks = pd.Series(
        rd.event_blocks(obs_dates[test_obs], any_risk[test_obs]), index=obs_dates[test_obs]
    )
    ev_test = pooled_events(obs_dates[test_obs], {r: risk_obs[r][test_obs] for r in REGIONS})
    n_pooled = ev_test["pooled"]
    dates = ctx["dates"]
    sp = rd.split_masks(dates)
    month = dates.month.to_numpy()
    lgbm_ok = with_lgbm and rd.lightgbm_available()
    result: dict = {
        "quantile": q,
        "thresholds": thr,
        "n_events_pooled_test": n_pooled,
        "n_events_test": {r: ev_test[r] for r in REGIONS},
        "events_per_season": {
            "test_2015_2019": events_per_season(
                obs_dates[test_obs], {r: risk_obs[r][test_obs] for r in REGIONS}
            ),
            "all_2000_2019": events_per_season(obs_dates, risk_obs),
        },
        "regions": {},
        "pooled_leads": {},
    }
    store: dict[int, list] = {}
    for r in REGIONS:
        valid_obs = tp[r].notna().reindex(dates).fillna(False).to_numpy(dtype=bool)
        y_all = (
            pd.Series(risk_obs[r], index=obs_dates).reindex(dates).fillna(False).to_numpy(dtype=int)
        )
        result["regions"][r] = {}
        raw: dict[int, bool] = {}
        for li, lead in enumerate(ctx["leads"]):
            feat = rd.feature_frame(ctx["members"], r, li, thr, dates)
            ok = valid_obs & ~np.isnan(feat["own_mean"].to_numpy())
            tr, va, te = sp["train"] & ok, sp["valid"] & ok, sp["test"] & ok
            if not te.any() or not (tr | va).any():
                continue
            fit = tr | va
            te_idx = np.flatnonzero(te)
            in_blocks = blocks.reindex(dates[te_idx]).notna().to_numpy()
            te_idx = te_idx[in_blocks]
            te_mask = np.zeros(len(dates), dtype=bool)
            te_mask[te_idx] = True
            ids = blocks.reindex(dates[te_idx]).to_numpy().astype(int)
            y = y_all[te_idx].astype(float)
            rates = rd.climatology_rates(month[fit], y_all[fit])
            probs = {"clim": rd.climatology_predict(rates, month[te_idx])}
            probs["log"] = rd.fit_logistic(feat[fit], y_all[fit], feat.iloc[te_idx])
            table = markov_table(risk_f[r], lead)
            probs["markov"] = markov_predict(table, risk_f[r], lead, dates[te_idx])
            probs["binary"] = binary_persistence(risk_f[r], lead, dates[te_idx])
            se = {m: (p - y) ** 2 for m, p in probs.items()}
            base_fit = float(y_all[fit].mean())
            row: dict = {
                "n_days": len(y),
                "base_rate": float(y.mean()),
                "base_rate_fit": base_fit,
                "n_risk_days": int(y.sum()),
                "n_events": len(np.unique(ids[y == 1])),
                "n_events_pooled": n_pooled,
                "brier": {m: float(s.mean()) for m, s in se.items()},
                "bss_log_clim": _ci(rd.bss_with_ci(se["log"], se["clim"], ids, n_boot, seed)),
                "bss_log_markov": _ci(rd.bss_with_ci(se["log"], se["markov"], ids, n_boot, seed)),
                "bss_log_binary": _ci(rd.bss_with_ci(se["log"], se["binary"], ids, n_boot, seed)),
            }
            raw[lead] = lead_passes(row["bss_log_clim"], row["bss_log_markov"], n_pooled)
            rel = rd.reliability(probs["log"], y)
            row["reliability"] = rel
            row["prob_cap"] = probability_cap(rel)
            row["pod_far"] = {
                "p>=0.5": pod_far(probs["log"], y, 0.5),
                "p>=2base": pod_far(probs["log"], y, 2 * base_fit),
            }
            lgbm: dict = {"available": rd.lightgbm_available(), "shown": False}
            if lgbm_ok:
                p_l, _info = rd.fit_lightgbm(
                    feat[tr], y_all[tr], feat[va], y_all[va], feat.iloc[te_idx], seed
                )
                ci = _ci(rd.bss_with_ci((p_l - y) ** 2, se["log"], ids, n_boot, seed))
                lgbm.update(
                    {
                        "brier": float(((p_l - y) ** 2).mean()),
                        "bss_lgbm_log": ci,
                        "shown": bool(ci["lo"] is not None and ci["lo"] > 0),
                    }
                )
            row["lgbm"] = lgbm
            store.setdefault(lead, []).append((y, probs["log"], base_fit))
            result["regions"][r][str(lead)] = row
        caps = pooled_caps({int(k): v["reliability"] for k, v in result["regions"][r].items()})
        for lead, c in caps.items():
            row = result["regions"][r][str(lead)]
            row["prob_cap_pooled"] = c["cap_pooled"]
            row["prob_cap_vigente"] = c["cap"]
        final = contiguous(raw)
        for lead, okc in final.items():
            row = result["regions"][r][str(lead)]
            row["pass_raw"] = raw[lead]
            row["pass_contiguous"] = okc
            row["status"] = status(okc)
    for lead, items in store.items():
        y = np.concatenate([x[0] for x in items])
        p = np.concatenate([x[1] for x in items])
        yes05 = {"thr": 0.5, **_pod_far_multi(items, lambda base: 0.5)}
        yes2 = {"thr": "2*base", **_pod_far_multi(items, lambda base: 2 * base)}
        result["pooled_leads"][str(lead)] = {
            "n_region_days": len(y),
            "p>=0.5": yes05,
            "p>=2base": yes2,
            "reliability": rd.reliability(p, y),
            "prob_cap": probability_cap(rd.reliability(p, y)),
        }
    return result


def _pod_far_multi(items: list, thr_fn) -> dict:
    hits = fa = n_ev = 0
    for y, p, base in items:
        t = thr_fn(base)
        yes = p >= t
        hits += int((yes & (y == 1)).sum())
        fa += int((yes & (y == 0)).sum())
        n_ev += int((y == 1).sum())
    return {
        "hits": hits,
        "false_alarms": fa,
        "n_risk_days": n_ev,
        "pod": hits / n_ev if n_ev else float("nan"),
        "far": fa / (hits + fa) if hits + fa else float("nan"),
    }


def analyze(
    ctx: dict,
    n_boot: int = 1000,
    seed: int = 0,
    quantiles: tuple[float, ...] = (0.95, 0.90, 0.98),
) -> dict:
    """Main run at ``quantiles[0]`` (with LightGBM comparison) plus sensitivity runs (same verdict, no LightGBM)."""
    main = _evaluate_q(ctx, quantiles[0], n_boot, seed, True)
    main["sensitivity_quantile"] = {
        str(q): _evaluate_q(ctx, q, n_boot, seed, False) for q in quantiles[1:]
    }
    main["lgbm_available"] = rd.lightgbm_available()
    return main


# --- run ----------------------------------------------------------------------------------------


def run(
    fc_path: Path,
    obs_path: Path,
    events_path: Path,
    out_dir: Path,
    n_boot: int = 1000,
    seed: int = 0,
    quantiles: tuple[float, ...] = (0.95, 0.90, 0.98),
) -> dict:
    ctx = rd.load_inputs(Path(fc_path), Path(obs_path), Path(events_path))
    results = rd._clean(analyze(ctx, n_boot, seed, tuple(quantiles)))
    results["meta"] = {
        "fc_source": ctx.get("fc_attrs", {}).get("source", "GEFSv12 reforecast"),
        "fc_period": f"{ctx['dates'].min().date()} … {ctx['dates'].max().date()}",
        "n_boot": n_boot,
        "seed": seed,
        "quantiles": list(quantiles),
        "n_cases": len(ctx["dates"]),
        "obs": Path(obs_path).name,
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "F5.8.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    (out / "F5.8.md").write_text(render_md(results), encoding="utf-8")
    return results


# --- report -------------------------------------------------------------------------------------

RULE_LINES = [
    (
        "- Misma partición, regiones y etiqueta que F5.3: umbral = cuantil {q} de los días de entrenamiento "
        "(2000–2011) de la media regional de ERA5 `tp`; ajuste 2000–2014; test 2015–2019. Sensibilidad: cuantiles {sens}."
    ),
    "- Modelos: climatología mensual, regresión logística (idéntica a F5.3) y persistencia; LightGBM solo para el criterio 3.",
    (
        "- Persistencia Markov: P(riesgo en D+L | riesgo observado el día de emisión D) por región, anticipación L y "
        "mes del día válido, con D = válido − L (último día completo antes de la corrida de 00 UTC), ajustada solo "
        "con días válidos ≤ 2014-12-31. Sensibilidad: persistencia binaria (riesgo en D → 1, si no → 0)."
    ),
    (
        "- BSS de la logística contra la climatología y contra la persistencia Markov; IC 95 % por bootstrap de "
        "bloques de eventos agrupados entre regiones (días de riesgo consecutivos de cualquier región = un bloque; "
        "{n_boot} remuestreos, semilla {seed})."
    ),
    (
        "- Criterio 3: LightGBM solo se muestra si su BSS contra la logística tiene IC > 0; se informa esa comparación "
        "en todas las anticipaciones."
    ),
    (
        "- Confiabilidad en 10 bins; POD y FAR (por día) con p ≥ 0,5 y con p ≥ 2 × tasa base de ajuste; eventos "
        "independientes por región y agrupados."
    ),
    (
        "- Tope de probabilidad: borde superior del bin de confiabilidad más alto con al menos 20 días pronosticados "
        "(es la probabilidad máxima que se puede mostrar)."
    ),
    (
        "- Tope vigente (decisión del usuario, 2026-11-22): para cada anticipación L se agrupan los días pronosticados "
        "de test de L−1, L y L+1 (las que existen entre 1 y 10; en los bordes, dos), se toma el borde superior del "
        "bin más alto con al menos 20 días y se lo hace no creciente en L (tope_L = mínimo de los topes 1..L). Por "
        "encima del tope el visor muestra «> tope». El tope por anticipación de arriba se conserva para comparar."
    ),
    (
        "- Veredicto por región y anticipación: pasa si ambos IC (contra climatología y contra Markov) tienen límite "
        "inferior > 0, hay al menos 20 eventos independientes agrupados en test y pasan todas las anticipaciones más "
        "cortas (criterio 2). Estado: «pasa hindcast (espera prospectiva F6.8)» o «Experimental»."
    ),
    (
        "- Eventos esperables por temporada mayo–septiembre: eventos independientes agrupados (evento de la "
        "temporada de su primer día) divididos por los años del período, en test y en 2000–2019."
    ),
]


def _nan(x) -> float:
    return float("nan") if x is None else float(x)


def _ci3(d: dict | None) -> str:
    if not d:
        return "—"
    return v._ci(_nan(d.get("value")), _nan(d.get("lo")), _nan(d.get("hi")))


def _pct(x, d: int = 0) -> str:
    x = _nan(x)
    return "—" if np.isnan(x) else v._f(100 * x, d) + " %"


def _verdict_rows(res: dict, r: str) -> list[list[str]]:
    rows = []
    for lead in sorted(int(k) for k in res["regions"].get(r, {})):
        m = res["regions"][r][str(lead)]
        rows.append(
            [
                str(lead),
                _ci3(m["bss_log_clim"]),
                _ci3(m["bss_log_markov"]),
                _ci3(m["bss_log_binary"]),
                str(m["n_events"]),
                str(m["n_events_pooled"]),
                "sí" if m["pass_raw"] else "no",
                m["status"],
            ]
        )
    return rows


def _verdict_summary(res: dict) -> dict[str, int]:
    out = {}
    for r in REGIONS:
        leads = [int(k) for k, m in res["regions"].get(r, {}).items() if m["pass_contiguous"]]
        out[r] = max(leads) if leads else 0
    return out


def render_md(results: dict) -> str:
    meta = results.get("meta", {})
    q = _nan(results.get("quantile", 0.95))
    sens = results.get("sensitivity_quantile", {})
    L = [
        "# F5.8 — Compuerta de evidencia para «día de riesgo» (criterios 1–3 de `plan/06-forecast.md`)",
        "",
    ]
    L += ["## Veredicto", ""]
    summ = _verdict_summary(results)
    for r in REGIONS:
        n = summ[r]
        L.append(
            f"- {rd.REGION_LABELS[r]}: "
            + (
                f"pasa hindcast de 1 a {n} días de anticipación (espera prospectiva F6.8); el resto, «Experimental»."
                if n
                else "«Experimental» en todas las anticipaciones."
            )
        )
    for k, s_res in sens.items():
        ss = _verdict_summary(s_res)
        L.append(
            f"- Sensibilidad cuantil {v._f(float(k), 2)}: "
            + "; ".join(f"{rd.REGION_LABELS[r]} hasta {ss[r]} d" for r in REGIONS)
            + "."
        )
    L.append(
        f"- Eventos independientes en test (agrupados entre regiones): {results.get('n_events_pooled_test')} "
        f"(mínimo {MIN_EVENTS})."
    )
    shown = [
        (r, lead)
        for r in REGIONS
        for lead, m in results["regions"].get(r, {}).items()
        if m["lgbm"].get("shown")
    ]
    if not results.get("lgbm_available", True):
        L.append("- LightGBM no estaba instalado: criterio 3 sin evaluar; se muestra la logística.")
    elif shown:
        L.append(
            f"- LightGBM supera a la logística con IC > 0 en {shown}: sin verificar su veredicto propio."
        )
    else:
        L.append(
            "- Criterio 3: LightGBM no supera a la logística con IC > 0 en ninguna región ni anticipación; se muestra la logística."
        )
    L.append(
        "- Esto es retrospectivo (hindcast); la promoción exige además la prospectiva (F6.4, F6.5) y la aprobación (F6.8)."
    )
    L += ["", "## Fuente y alcance", ""]
    L.append(
        f"- Pronóstico: {meta.get('fc_source', 'GEFSv12 reforecast')}; {meta.get('fc_period', '')}; "
        f"{meta.get('n_cases', '?')} días, 1–10 días de anticipación, 5 miembros. Observado: `{meta.get('obs', '')}` (ERA5)."
    )
    L += ["", "## Regla fijada antes de correr", ""]
    sens_txt = ", ".join(v._f(float(k), 2) for k in sens) or "—"
    for line in RULE_LINES:
        L.append(
            line.replace("{q}", v._f(q, 2))
            .replace("{sens}", sens_txt)
            .replace("{n_boot}", str(meta.get("n_boot", 1000)))
            .replace("{seed}", str(meta.get("seed", 0)))
        )
    L.append("")
    L += ["## Eventos independientes esperables por temporada (mayo–septiembre)", ""]
    rows = []
    for name, label in (("test_2015_2019", "test 2015–2019"), ("all_2000_2019", "2000–2019")):
        e = results["events_per_season"][name]
        row = [label, str(e["n_seasons"])]
        for key in ("pooled", *REGIONS):
            row.append(
                f"{e[key]['n_events']} ({v._f(_nan(e[key]['per_season']), 1)} por temporada)"
            )
        rows.append(row)
    L += v._table(
        ["Período", "Temporadas", "Agrupados", *[rd.REGION_LABELS[r] for r in REGIONS]], rows
    )
    L.append(
        "El umbral sale de 2000–2011, así que en 2000–2011 el conteo es de la muestra de entrenamiento; la cifra "
        "de test es la independiente."
    )
    L.append("")
    header = [
        "L (días)",
        "BSS vs clim. [IC]",
        "BSS vs Markov [IC]",
        "BSS vs binaria [IC]",
        "Eventos región",
        "Eventos agrupados",
        "Pasa solo",
        "Estado (con contigüidad)",
    ]
    for r in REGIONS:
        reg = results["regions"].get(r, {})
        if not reg:
            continue
        first = reg[min(reg, key=int)]
        L += [f"## {rd.REGION_LABELS[r]}", ""]
        L.append(
            f"Umbral {v._f(_nan(results['thresholds'].get(r)), 2)} mm/día; tasa base en test "
            f"{_pct(first['base_rate'], 1)}; {first['n_days']} días y {first['n_events']} eventos en test."
        )
        L.append("")
        L += v._table(header, _verdict_rows(results, r))
        L += [
            "LightGBM contra la logística (criterio 3) y tope de probabilidad; POD / FAR de la logística.",
            "",
        ]
        rows = []
        for lead in sorted(int(k) for k in reg):
            m = reg[str(lead)]
            pf5, pf2 = m["pod_far"]["p>=0.5"], m["pod_far"]["p>=2base"]
            lg = m["lgbm"]
            rows.append(
                [
                    str(lead),
                    _ci3(lg.get("bss_lgbm_log")) if "bss_lgbm_log" in lg else "sin dato",
                    "sí" if lg.get("shown") else "no",
                    _pct(m["prob_cap"]) if m["prob_cap"] is not None else "—",
                    _pct(m["prob_cap_vigente"]) if m.get("prob_cap_vigente") is not None else "—",
                    f"{v._f(_nan(pf5['pod']))} / {v._f(_nan(pf5['far']))} (n={pf5['n_yes']})",
                    f"{v._f(_nan(pf2['pod']))} / {v._f(_nan(pf2['far']))} (n={pf2['n_yes']})",
                ]
            )
        L += v._table(
            [
                "L (días)",
                "BSS LGBM vs log. [IC]",
                "LGBM se muestra",
                "Tope de probabilidad (por L, anterior)",
                "Tope vigente (L±1, no creciente)",
                "POD / FAR p ≥ 0,5",
                "POD / FAR p ≥ 2×base",
            ],
            rows,
        )
        L += [
            f"Confiabilidad de la logística, {rd.REGION_LABELS[r]} (probabilidad media pronosticada → frecuencia observada, n):",
            "",
        ]
        rows = []
        for lead in rd.SENS_LEADS:
            if str(lead) not in reg:
                continue
            rel = reg[str(lead)]["reliability"]
            rows.append(
                [str(lead)]
                + [
                    f"{v._f(_nan(b['mean_p']))} → {v._f(_nan(b['obs_freq']))} ({b['n']})"
                    if b["n"]
                    else "—"
                    for b in rel
                ]
            )
        L += v._table(
            ["L", *[f"{i / 10:.1f}–{(i + 1) / 10:.1f}".replace(".", ",") for i in range(10)]], rows
        )
    L += ["## Agrupado entre regiones (logística)", ""]
    rows = []
    for lead in sorted(int(k) for k in results.get("pooled_leads", {})):
        pl = results["pooled_leads"][str(lead)]
        a, b = pl["p>=0.5"], pl["p>=2base"]
        rows.append(
            [
                str(lead),
                f"{v._f(_nan(a['pod']))} / {v._f(_nan(a['far']))}",
                f"{v._f(_nan(b['pod']))} / {v._f(_nan(b['far']))}",
                _pct(pl["prob_cap"]) if pl["prob_cap"] is not None else "—",
            ]
        )
    L += v._table(
        ["L (días)", "POD / FAR p ≥ 0,5", "POD / FAR p ≥ 2×base", "Tope de probabilidad"], rows
    )
    L += ["## Sensibilidad", ""]
    L += ["Mayor anticipación contigua que pasa por región y cuantil de riesgo.", ""]
    rows = [[f"cuantil {v._f(q, 2)} (principal)", *[str(summ[r]) for r in REGIONS]]]
    for k, s_res in sens.items():
        ss = _verdict_summary(s_res)
        rows.append([f"cuantil {v._f(float(k), 2)}", *[str(ss[r]) for r in REGIONS]])
    L += v._table(["Variante", *[rd.REGION_LABELS[r] for r in REGIONS]], rows)
    L += [
        "Persistencia binaria: columna «BSS vs binaria» de cada tabla (no entra en el veredicto).",
        "",
        "## Advertencias",
        "",
        "- ERA5 es un reanálisis, referencia débil para convección (F3.4); los aciertos incluyen el error de la referencia.",
        "- Cinco temporadas de test: los IC son anchos y el veredicto es retrospectivo; falta la prueba prospectiva (F6.8).",
        "- POD y FAR por día; con eventos raros el FAR es alto por construcción y no se fija tope.",
        "- No es una alerta oficial. Ante una diferencia, siga los avisos de SMN, AIC y Defensa Civil.",
        "",
    ]
    return "\n".join(L)

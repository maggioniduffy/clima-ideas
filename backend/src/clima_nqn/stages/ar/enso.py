"""Atmospheric rivers by ENSO phase over the Neuquén cordillera (plan/01, F1.8).

Question: do AR count, AR days, AR IVT and the AR share of seasonal rain differ between El Niño,
neutral and La Niña seasons?

Conventions:
- Season-years: DJF, MAM, JJA, SON. December is assigned to the *following* year's DJF, so "DJF 1981"
  is Dec 1980 + Jan 1981 + Feb 1981. A season-year is kept only when every day of its three months
  is in the daily precipitation record; edge seasons (DJF 1980 lacks Dec 1979) are dropped.
- An event belongs to the season-year of its start; its whole ``tp_sum_mm`` is attributed to that
  season even if the event runs past the season edge (small bias, unquantified).
- ``ar_days`` counts UTC days touched by an event (``extremes.ar_days``, no tolerance).
- ``ar_share`` = sum of ``tp_sum_mm`` of the season's events / total seasonal precipitation of the
  polygon mean (``extremes.daily_precip``). Both are polygon means, so the ratio is comparable.
- ``ivt_mean`` and ``ivt_max`` are the mean and the maximum of the events' ``ivt_max``; undefined
  (NaN, season-year left out of that metric) when the season had no events.
- ENSO phase of a season-year: mean of the three monthly ONI values, classified with the thresholds
  of ``clima_nqn.io.enso`` (>= +0.5 Niño, <= -0.5 Niña, else neutral).
- Two-group test (Niño vs Niña): permutation of the labels, statistic = difference of means,
  two-sided p = (k + 1) / (n_perm + 1), k = permutations with |diff| >= |observed|.
- Three-group test (Niño vs Neutro vs Niña): permutation of the labels, statistic = one-way
  ANOVA F (between- over within-group variance). Chosen over max |pairwise difference| because it
  uses all groups and copes with unequal group sizes.
- Multiplicity: Benjamini-Hochberg adjustment over the 16 season x metric tests (per test family).
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.io import enso as io_enso
from clima_nqn.stages.ar import catalog, extremes

YEAR_MIN, YEAR_MAX = 1980, 2025
ALPHA = 0.05
PHASES = ("nino", "neutral", "nina")
SEASONS = extremes.SEASONS  # name -> months
METRICS = {
    "n_events": ("Eventos (n)", 1.0, 2),
    "ar_days": ("Días con RA", 1.0, 1),
    "ivt_mean": ("IVT máx. medio (kg m⁻¹ s⁻¹)", 1.0, 0),
    "ar_share": ("Fracción de lluvia por RA (%)", 100.0, 1),
}
SOURCE = (
    "ERA5 via ARCO-ERA5 (CC-BY 4.0); detecciones TECA BARD 6.0.0 (catálogo F1.3); "
    f"ONI de {io_enso.SOURCE}"
)
TABLE_COLUMNS = [
    "season", "year", "n_events", "ar_days", "ivt_mean", "ivt_max", "ar_precip_mm",
    "total_precip_mm", "ar_share", "oni_mean", "phase",
]  # fmt: skip


# --- seasons -------------------------------------------------------------------------------


def season_of_month(month: int) -> str:
    for name, months in SEASONS.items():
        if month in months:
            return name
    raise ValueError(f"bad month {month}")


def season_year(dates: pd.DatetimeIndex | pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """(season name, season year) per date. December counts toward the following year's DJF."""
    d = pd.DatetimeIndex(dates)
    month = d.month.to_numpy()
    year = d.year.to_numpy() + (month == 12)
    names = np.array([season_of_month(int(m)) for m in month], dtype=object)
    return names, year


def _season_months(season: str, year: int) -> list[pd.Timestamp]:
    return [
        pd.Timestamp(year - 1 if (season == "DJF" and m == 12) else year, m, 1)
        for m in SEASONS[season]
    ]


def _expected_days(season: str, year: int) -> int:
    return sum(m.days_in_month for m in _season_months(season, year))


def seasonal_oni(enso: pd.DataFrame, season: str, year: int) -> tuple[float, str | None]:
    """Mean monthly ONI of the season's three months and its phase (NaN, None if a month is missing)."""
    by_month = enso.set_index(enso["date"].dt.to_period("M"))["oni"]
    vals = []
    for m in _season_months(season, year):
        key = m.to_period("M")
        if key not in by_month.index:
            return math.nan, None
        vals.append(float(by_month[key]))
    mean = float(np.mean(vals))
    return mean, str(io_enso.classify_phase(pd.Series([mean])).iloc[0])


# --- season-year table -----------------------------------------------------------------------


def season_table(
    events: pd.DataFrame,
    daily: pd.Series,
    enso: pd.DataFrame,
    year_min: int = YEAR_MIN,
    year_max: int = YEAR_MAX,
) -> pd.DataFrame:
    """One row per complete season-year with AR metrics, seasonal rain and ENSO phase."""
    days = pd.DatetimeIndex(daily.index)
    d_season, d_year = season_year(days)
    is_ar = extremes.ar_days(events, days, 0).to_numpy()
    day_frame = pd.DataFrame(
        {"season": d_season, "year": d_year, "precip": daily.to_numpy(float), "is_ar": is_ar}
    )
    ev_groups: dict[tuple[str, int], pd.DataFrame] = {}
    if len(events):
        e_season, e_year = season_year(pd.DatetimeIndex(events["start"]))
        ev = events.assign(season=e_season, year=e_year)
        ev_groups = {(s, int(y)): g for (s, y), g in ev.groupby(["season", "year"])}

    rows = []
    for (season, year), g in day_frame.groupby(["season", "year"]):
        year = int(year)
        if not year_min <= year <= year_max or len(g) != _expected_days(season, year):
            continue  # outside the study years or incomplete at the record edge
        e = ev_groups.get((season, year))
        n_ev = 0 if e is None else len(e)
        total = float(g["precip"].sum())
        ar_precip = 0.0 if e is None else float(e["tp_sum_mm"].sum())
        oni_mean, phase = seasonal_oni(enso, season, year)
        rows.append(
            {
                "season": season,
                "year": year,
                "n_events": n_ev,
                "ar_days": int(g["is_ar"].sum()),
                "ivt_mean": float(e["ivt_max"].mean()) if n_ev else math.nan,
                "ivt_max": float(e["ivt_max"].max()) if n_ev else math.nan,
                "ar_precip_mm": ar_precip,
                "total_precip_mm": total,
                "ar_share": ar_precip / total if total > 0 else math.nan,
                "oni_mean": oni_mean,
                "phase": phase,
            }
        )
    out = pd.DataFrame(rows, columns=TABLE_COLUMNS)
    out["_order"] = out["season"].map({s: i for i, s in enumerate(SEASONS)})
    return out.sort_values(["_order", "year"]).drop(columns="_order").reset_index(drop=True)


# --- statistics ----------------------------------------------------------------------------


def _clean_groups(values, labels) -> tuple[np.ndarray, np.ndarray]:
    v = np.asarray(values, dtype=float)
    lab = np.asarray(labels, dtype=object)
    keep = ~np.isnan(v)
    return v[keep], lab[keep]


def permutation_test(
    values,
    labels,
    group_a: str,
    group_b: str,
    n_perm: int = 10000,
    seed: int = 0,
) -> dict:
    """Two-sided permutation test of mean(a) - mean(b), labels shuffled among a and b units.

    p = (k + 1) / (n_perm + 1) with k = permutations with |diff| >= |observed| (so p > 0).
    NaN values are ignored. Returns ``diff``, ``p``, ``n_a``, ``n_b`` (p NaN if a group is empty).
    """
    v, lab = _clean_groups(values, labels)
    a, b = v[lab == group_a], v[lab == group_b]
    n_a, n_b = len(a), len(b)
    if n_a == 0 or n_b == 0:
        return {"diff": math.nan, "p": math.nan, "n_a": n_a, "n_b": n_b}
    obs = float(a.mean() - b.mean())
    pool = np.concatenate([a, b])
    rng = np.random.default_rng(seed)
    perm = pool[rng.random((n_perm, len(pool))).argsort(axis=1)]
    diffs = perm[:, :n_a].mean(axis=1) - perm[:, n_a:].mean(axis=1)
    tol = 1e-9 * max(1.0, abs(obs))
    k = int((np.abs(diffs) >= abs(obs) - tol).sum())
    return {"diff": obs, "p": (k + 1) / (n_perm + 1), "n_a": n_a, "n_b": n_b}


def _f_stat(values: np.ndarray, codes: np.ndarray, n_groups: int) -> np.ndarray:
    """One-way ANOVA F for each row of ``codes`` (integer labels 0..n_groups-1) over shared values."""
    codes = np.atleast_2d(codes)
    n = values.shape[0]
    grand = values.mean()
    ss_total = float(((values - grand) ** 2).sum())
    ssb = np.zeros(codes.shape[0])
    for g in range(n_groups):
        m = codes == g
        n_g = m.sum(axis=1)
        mean_g = (m * values).sum(axis=1) / np.maximum(n_g, 1)
        ssb += n_g * (mean_g - grand) ** 2
    ssw = ss_total - ssb
    ssw = np.where(ssw < 1e-12 * max(ss_total, 1e-300), 0.0, ssw)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = (ssb / (n_groups - 1)) / (ssw / (n - n_groups))
    return np.where(ssw == 0, np.where(ssb > 0, np.inf, 0.0), f)


def permutation_test_groups(
    values,
    labels,
    groups: Sequence[str] = PHASES,
    n_perm: int = 10000,
    seed: int = 0,
) -> dict:
    """Permutation test across groups with the one-way ANOVA F statistic (upper tail only).

    Returns ``stat`` (observed F), ``p`` = (k + 1) / (n_perm + 1) with k = permutations with
    F >= observed, and ``n`` per group. p is NaN when a group is empty or N <= number of groups.
    """
    v, lab = _clean_groups(values, labels)
    sel = np.isin(lab, list(groups))
    v, lab = v[sel], lab[sel]
    ns = {g: int((lab == g).sum()) for g in groups}
    if min(ns.values()) == 0 or len(v) <= len(groups):
        return {"stat": math.nan, "p": math.nan, "n": ns}
    index = {g: i for i, g in enumerate(groups)}
    codes = np.array([index[x] for x in lab])
    obs = float(_f_stat(v, codes, len(groups))[0])
    rng = np.random.default_rng(seed)
    perm_codes = codes[rng.random((n_perm, len(v))).argsort(axis=1)]
    f = _f_stat(v, perm_codes, len(groups))
    tol = 1e-9 * abs(obs) if math.isfinite(obs) else 0.0
    k = int((f >= obs - tol).sum())
    return {"stat": obs, "p": (k + 1) / (n_perm + 1), "n": ns}


def bh_adjust(pvals: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (NaN kept as NaN and excluded from m)."""
    p = np.asarray(pvals, dtype=float)
    out = np.full(p.shape, math.nan)
    ok = ~np.isnan(p)
    m = int(ok.sum())
    if m == 0:
        return out.tolist()
    vals = p[ok]
    order = np.argsort(vals)
    ranked = vals[order] * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    res = np.empty(m)
    res[order] = np.minimum(adj, 1.0)
    out[ok] = res
    return out.tolist()


def _mean_sd(x: np.ndarray) -> tuple[float, float]:
    if len(x) == 0:
        return math.nan, math.nan
    return float(x.mean()), float(x.std(ddof=1)) if len(x) > 1 else math.nan


def compute_results(table: pd.DataFrame, n_perm: int = 10000, seed: int = 0) -> dict:
    """Per season and metric: group stats, Niño-Niña test, 3-group test, BH adjustments."""
    rows = []
    for season in SEASONS:
        sub = table[table["season"] == season]
        lab = sub["phase"].to_numpy(object)
        phase_counts = {p: int((lab == p).sum()) for p in PHASES}
        for metric in METRICS:
            v = sub[metric].to_numpy(float)
            groups = {}
            for p in PHASES:
                mean, sd = _mean_sd(v[(lab == p) & ~np.isnan(v)])
                groups[p] = {"n": int(((lab == p) & ~np.isnan(v)).sum()), "mean": mean, "sd": sd}
            pair = permutation_test(v, lab, "nino", "nina", n_perm, seed)
            triple = permutation_test_groups(v, lab, PHASES, n_perm, seed)
            rows.append(
                {
                    "season": season,
                    "metric": metric,
                    "phase_years": phase_counts,
                    "groups": groups,
                    "diff_nino_nina": pair["diff"],
                    "p": pair["p"],
                    "p_3group": triple["p"],
                    "f_3group": triple["stat"],
                }
            )
    for key, out in (("p", "p_bh"), ("p_3group", "p_3group_bh")):
        for r, adj in zip(rows, bh_adjust([r[key] for r in rows]), strict=True):
            r[out] = adj
    for r in rows:
        r["sustained"] = not math.isnan(r["p"]) and r["p"] < ALPHA
        r["sustained_bh"] = not math.isnan(r["p_bh"]) and r["p_bh"] < ALPHA
    return {"rows": rows, "n_perm": n_perm, "seed": seed, "alpha": ALPHA}


# --- report --------------------------------------------------------------------------------


def _num(x, nd: int = 2) -> str:
    return "n/d" if x is None or math.isnan(x) else f"{x:.{nd}f}"


def _clean(obj):
    """JSON-safe copy: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def label_sustained(p: float) -> str:
    return "sí (p<0.05)" if not math.isnan(p) and p < ALPHA else "no"


def write_report(results: dict, path: Path | str, meta: dict) -> Path:
    """Write the Spanish Markdown report to ``path`` and the numbers to the same name with ``.json``.

    ``meta`` keys: ``period``, ``n_events``, ``bard_threshold``, ``polygon`` (lon, lat vertices);
    ``table`` (optional season-year DataFrame) is written to the JSON only.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = results["rows"]
    n_tests = len(rows)
    table = meta.get("table")
    json_meta = {k: v for k, v in meta.items() if k != "table"}
    lines = [
        "# F1.8 — Ríos atmosféricos por fase ENSO (cordillera neuquina)",
        "",
        (
            "Pregunta: ¿difieren el conteo, los días, el IVT y la fracción de lluvia por río atmosférico "
            "(RA) entre estaciones de El Niño, neutras y de La Niña?"
        ),
        "",
        "## Fuente y alcance",
        "",
        f"- Fuente: {SOURCE}.",
        f"- Período: {meta.get('period', 'sin verificar')}.",
        f"- Eventos RA en el catálogo: {meta.get('n_events', 'sin verificar')}.",
        f"- Umbral BARD de `ar_probability`: {meta.get('bard_threshold', 'sin verificar')}.",
        f"- Polígono (lon, lat): {json.dumps(meta.get('polygon'))} — aproximación, sin verificar.",
        "",
        "## Definiciones",
        "",
        (
            "- Estaciones: DJF, MAM, JJA, SON. Diciembre se asigna al DJF del año siguiente "
            "(DJF 1981 = dic 1980 + ene–feb 1981). Se descartan estaciones incompletas en los bordes "
            "del registro (p. ej. DJF 1980, sin dic 1979)."
        ),
        "- Evento de la estación: el que empieza dentro de ella (toda su lluvia se atribuye a esa estación).",
        "- Días con RA: días UTC tocados por algún evento.",
        "- IVT: promedio, por estación, del IVT máximo de sus eventos (solo años con al menos un evento).",
        (
            "- Fracción de lluvia por RA: suma de la lluvia media del polígono de los eventos / lluvia "
            "total de la estación (media del polígono)."
        ),
        (
            f"- Fase ENSO de la estación: media del ONI mensual ({io_enso.SOURCE}) de sus tres meses; "
            f"Niño si ≥ +{io_enso.NINO_THRESHOLD}, Niña si ≤ {io_enso.NINA_THRESHOLD}, si no Neutro."
        ),
        (
            f"- Prueba Niño − Niña: permutación de etiquetas ({results.get('n_perm')} permutaciones, "
            f"semilla {results.get('seed')}), estadístico = diferencia de medias, p bilateral = "
            "(k+1)/(n+1)."
        ),
        "- Prueba de 3 grupos (Niño, Neutro, Niña): permutación con el estadístico F de ANOVA de una vía.",
        (
            f"- «¿Diferencia sostenida?» = «sí (p<0.05)» solo si el p de permutación Niño − Niña es "
            f"< {ALPHA}; si no, «no». «p BH» es el p ajustado por Benjamini-Hochberg sobre las "
            f"{n_tests} pruebas (estación × métrica)."
        ),
        "",
        "## Años por fase y estación",
        "",
        "| Estación | Niño | Neutro | Niña | Total |",
        "|---|---|---|---|---|",
    ]
    for season in SEASONS:
        pc = next(r for r in rows if r["season"] == season)["phase_years"]
        lines.append(
            f"| {season} | {pc['nino']} | {pc['neutral']} | {pc['nina']} | {sum(pc.values())} |"
        )
    lines.append("")
    for season in SEASONS:
        lines += [
            f"## {season}",
            "",
            (
                "| Métrica | Niño (media ± sd, n) | Neutro (media ± sd, n) | Niña (media ± sd, n) | "
                "Niño − Niña | p (perm.) | p BH | p 3 grupos | p 3 grupos BH | ¿diferencia sostenida? |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in (x for x in rows if x["season"] == season):
            title, scale, nd = METRICS[r["metric"]]
            cells = [
                f"{_num(g['mean'] * scale, nd)} ± {_num(g['sd'] * scale, nd)} (n={g['n']})"
                for g in (r["groups"][p] for p in PHASES)
            ]
            lines.append(
                f"| {title} | {' | '.join(cells)} | {_num(r['diff_nino_nina'] * scale, nd)} | "
                f"{_num(r['p'], 4)} | {_num(r['p_bh'], 4)} | {_num(r['p_3group'], 4)} | "
                f"{_num(r['p_3group_bh'], 4)} | {label_sustained(r['p'])} |"
            )
        lines.append("")
    n_raw = sum(r["sustained"] for r in rows)
    n_bh = sum(r["sustained_bh"] for r in rows)
    lines += [
        "## Resumen",
        "",
        (
            f"- De {n_tests} pruebas Niño − Niña, {n_raw} tienen p < {ALPHA} sin ajustar y {n_bh} "
            f"mantienen p BH < {ALPHA}. Con {n_tests} pruebas se esperan ~{n_tests * ALPHA:.1f} "
            "con p < 0.05 por azar si no hubiera ninguna diferencia."
        ),
        "",
        "## Salvedades",
        "",
        (
            "- Pocos años por fase (ver tabla de años): la prueba tiene poca potencia; «no» significa "
            "«no sostenido por estos datos», no «sin efecto»."
        ),
        (
            f"- Comparaciones múltiples: {n_tests} pruebas (4 estaciones × 4 métricas); los p sin "
            "ajustar sobrestiman la evidencia, por eso se reporta el p BH."
        ),
        "- Las métricas comparten eventos, así que las pruebas no son independientes.",
        "- La permutación trata los años como intercambiables: ignora tendencias y persistencia del ENSO.",
        "- El polígono es una aproximación sin verificar.",
        (
            "- ERA5 es un reanálisis, no datos de estaciones; la lluvia en terreno complejo puede estar "
            "subestimada, y la detección depende del umbral BARD."
        ),
        "- La fase usa el ONI de los tres meses de la estación; no mide desfases entre ENSO y la respuesta regional.",
        "- Análisis retrospectivo de asociación: no prueba causalidad ni es un sistema de alerta.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    payload = {"meta": json_meta, "results": results}
    if table is not None:
        payload["season_years"] = table.to_dict(orient="records")
    path.with_suffix(".json").write_text(
        json.dumps(_clean(payload), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


# --- entry point ---------------------------------------------------------------------------


def run(
    events_path: Path | str,
    era5_paths: Sequence[Path],
    enso_path: Path | str,
    out_dir: Path | str,
    n_perm: int = 10000,
    seed: int = 0,
) -> dict:
    """Read the F1.3 catalog, build the season-year table and write ``F1.8.md`` / ``F1.8.json``."""
    events = pd.read_parquet(events_path)
    cat_meta = catalog.read_metadata(events_path)
    polygon = [tuple(v) for v in json.loads(cat_meta["polygon"])] if "polygon" in cat_meta else None
    polygon = polygon or catalog.CORDILLERA_POLYGON
    enso = io_enso.read_enso(enso_path)
    mean, _cells = extremes.daily_precip(era5_paths, polygon)
    table = season_table(events, mean, enso)
    results = compute_results(table, n_perm, seed)
    meta = {
        "period": f"{mean.index[0]:%Y-%m-%d}/{mean.index[-1]:%Y-%m-%d}",
        "season_years_period": f"{YEAR_MIN}-{YEAR_MAX}",
        "n_events": len(events),
        "n_season_years": len(table),
        "bard_threshold": float(cat_meta["threshold"]) if "threshold" in cat_meta else None,
        "polygon": [list(v) for v in polygon],
        "source": SOURCE,
        "table": table,
    }
    write_report(results, Path(out_dir) / "F1.8.md", meta)
    return results

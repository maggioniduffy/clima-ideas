"""Extreme-rain days by ENSO phase over the Neuquén cordillera (plan/01, F1.9).

Question: do the days with polygon-mean rain at or above the F1.4 threshold (p99 of all days) fall
differently in El Niño, neutral and La Niña seasons, or along the seasonal ONI?

The rule is fixed in ``plan/01-atmospheric-rivers.md`` ("Regla de F1.9") before any run:

- Unit: season-year (DJF, MAM, JJA, SON; December goes to the following year's DJF; incomplete edge
  seasons are dropped), 1980-2025, same convention as F1.8 (``enso.season_year``).
- Series: daily ERA5 rain, polygon mean (``extremes.daily_precip``, UTC days).
- Extreme day: daily value >= ``np.quantile(all days, q)`` (linear interpolation), as F1.4.
- Per season-year: number of extreme days and whether there was at least one.
- Phase: mean ONI of the season's three months, thresholds of ``clima_nqn.io.enso``.
- Per season: Niño - Niña difference in mean extreme days (label permutation, 10 000, seed 0, two-sided);
  3-group permutation F; Spearman rho of extreme days vs seasonal ONI with a permutation p
  (ONI shuffled, 10 000, seed 0, two-sided, p = (k + 1) / (n + 1)). Benjamini-Hochberg over the four
  seasons, separately for each of the three p-values.
- Variants: ``main`` (p99, polygon), ``p95`` (p95, polygon), ``rectangle`` (p99 of the rectangle's own
  series). A season is ``robust`` only when the sign of Niño - Niña and the BH verdict agree in all three.
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
from clima_nqn.stages.ar import enso as ar_enso

YEAR_MIN, YEAR_MAX = ar_enso.YEAR_MIN, ar_enso.YEAR_MAX
ALPHA = ar_enso.ALPHA
PHASES = ar_enso.PHASES
SEASONS = ar_enso.SEASONS
SOURCE = (
    "ERA5 via ARCO-ERA5 (CC-BY 4.0), lluvia diaria (días UTC) promediada sobre la región; "
    f"ONI de {io_enso.SOURCE}"
)
VARIANTS = {
    "main": {"label": "p99, polígono", "quantile": 0.99, "region": "polygon"},
    "p95": {"label": "p95, polígono", "quantile": 0.95, "region": "polygon"},
    "rectangle": {"label": "p99, rectángulo", "quantile": 0.99, "region": "rectangle"},
}
SEASON_NOUN = {"DJF": "veranos", "MAM": "otoños", "JJA": "inviernos", "SON": "primaveras"}
F14_P99_MM = 29.2  # F1.4 main threshold (mm/day), checked in the report
PERM_CHUNK = 2000  # permutations per vectorised block
TABLE_COLUMNS = ["season", "year", "oni_mean", "phase", "n_extreme_days", "any_extreme"]


# --- season-year table -----------------------------------------------------------------------


def threshold_of(daily: pd.Series, quantile: float) -> float:
    """Quantile of all daily values (linear interpolation), as ``extremes.compute_results``."""
    return float(np.quantile(daily.to_numpy(dtype=float), quantile))


def season_table(
    daily: pd.Series,
    enso: pd.DataFrame,
    threshold: float,
    year_min: int = YEAR_MIN,
    year_max: int = YEAR_MAX,
) -> pd.DataFrame:
    """One row per complete season-year: extreme-day count (value >= threshold), ONI mean, phase."""
    days = pd.DatetimeIndex(daily.index)
    d_season, d_year = ar_enso.season_year(days)
    frame = pd.DataFrame(
        {
            "season": d_season,
            "year": d_year,
            "extreme": daily.to_numpy(dtype=float) >= threshold,
        }
    )
    rows = []
    for (season, year), g in frame.groupby(["season", "year"]):
        year = int(year)
        if not year_min <= year <= year_max or len(g) != ar_enso._expected_days(season, year):
            continue  # outside the study years or incomplete at the record edge
        n_ext = int(g["extreme"].sum())
        oni_mean, phase = ar_enso.seasonal_oni(enso, season, year)
        rows.append(
            {
                "season": season,
                "year": year,
                "oni_mean": oni_mean,
                "phase": phase,
                "n_extreme_days": n_ext,
                "any_extreme": n_ext > 0,
            }
        )
    out = pd.DataFrame(rows, columns=TABLE_COLUMNS)
    out["_order"] = out["season"].map({s: i for i, s in enumerate(SEASONS)})
    return out.sort_values(["_order", "year"]).drop(columns="_order").reset_index(drop=True)


# --- statistics ----------------------------------------------------------------------------


def spearman(x, y, n_perm: int = 10000, seed: int = 0) -> dict:
    """Spearman rho (Pearson on average ranks) and its two-sided permutation p.

    ``y`` is shuffled ``n_perm`` times; p = (k + 1) / (n_perm + 1), k = permutations with
    |rho| >= |observed|. NaN pairs are dropped; rho and p are NaN when either side is constant
    or fewer than 3 pairs remain.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    keep = ~(np.isnan(x) | np.isnan(y))
    x, y = x[keep], y[keep]
    if len(x) < 3:
        return {"rho": math.nan, "p": math.nan, "n": len(x)}
    rx = pd.Series(x).rank(method="average").to_numpy()
    ry = pd.Series(y).rank(method="average").to_numpy()
    cx, cy = rx - rx.mean(), ry - ry.mean()
    denom = math.sqrt(float((cx**2).sum()) * float((cy**2).sum()))
    if denom == 0:
        return {"rho": math.nan, "p": math.nan, "n": len(x)}
    obs = float((cx * cy).sum() / denom)
    rng = np.random.default_rng(seed)
    tol = 1e-9
    k = 0
    for start in range(0, n_perm, PERM_CHUNK):  # chunked: bounded memory, same RNG stream
        size = min(PERM_CHUNK, n_perm - start)
        perm = cy[rng.random((size, len(cy))).argsort(axis=1)]
        rhos = (perm * cx).sum(axis=1) / denom
        k += int((np.abs(rhos) >= abs(obs) - tol).sum())
    return {"rho": obs, "p": (k + 1) / (n_perm + 1), "n": len(x)}


def compute_results(table: pd.DataFrame, n_perm: int = 10000, seed: int = 0) -> list[dict]:
    """Per season: group counts, Niño-Niña test, 3-group test, Spearman vs ONI, BH over the seasons."""
    rows = []
    for season in SEASONS:
        sub = table[table["season"] == season]
        lab = sub["phase"].to_numpy(object)
        n_ext = sub["n_extreme_days"].to_numpy(float)
        groups = {}
        for p in PHASES:
            m = lab == p
            n = int(m.sum())
            total = int(n_ext[m].sum())
            groups[p] = {
                "n": n,
                "years_with_extreme": int((n_ext[m] > 0).sum()),
                "total_days": total,
                "mean_days": total / n if n else math.nan,
            }
        pair = ar_enso.permutation_test(n_ext, lab, "nino", "nina", n_perm, seed)
        triple = ar_enso.permutation_test_groups(n_ext, lab, PHASES, n_perm, seed)
        rho = spearman(n_ext, sub["oni_mean"].to_numpy(float), n_perm, seed)
        rows.append(
            {
                "season": season,
                "phase_years": {p: groups[p]["n"] for p in PHASES},
                "groups": groups,
                "diff_nino_nina": pair["diff"],
                "p": pair["p"],
                "p_3group": triple["p"],
                "spearman_rho": rho["rho"],
                "p_oni": rho["p"],
            }
        )
    for key, out in (("p", "p_bh"), ("p_3group", "p_3group_bh"), ("p_oni", "p_oni_bh")):
        for r, adj in zip(rows, ar_enso.bh_adjust([r[key] for r in rows]), strict=True):
            r[out] = adj
    for r in rows:
        r["sustained_bh"] = not math.isnan(r["p_bh"]) and r["p_bh"] < ALPHA
    return rows


def build_variant(
    daily: pd.Series, enso: pd.DataFrame, spec: dict, n_perm: int = 10000, seed: int = 0
) -> dict:
    """One variant: threshold, season-year table and per-season results."""
    thr = threshold_of(daily, spec["quantile"])
    table = season_table(daily, enso, thr)
    return {
        "label": spec["label"],
        "quantile": spec["quantile"],
        "region": spec["region"],
        "threshold_mm": thr,
        "n_extreme_days_total": int((daily.to_numpy(dtype=float) >= thr).sum()),
        "rows": compute_results(table, n_perm, seed),
        "season_years": table.to_dict(orient="records"),
    }


def robust_flags(variants: dict, seasons: Sequence[str] = tuple(SEASONS)) -> dict[str, bool]:
    """Per season: sign of Niño - Niña and the BH verdict agree across all variants."""
    out = {}
    for season in seasons:
        rows = [next(r for r in v["rows"] if r["season"] == season) for v in variants.values()]
        diffs = [r["diff_nino_nina"] for r in rows]
        if any(d is None or math.isnan(d) for d in diffs):
            out[season] = False
            continue
        same_sign = len({int(np.sign(d)) for d in diffs}) == 1
        same_bh = len({bool(r["sustained_bh"]) for r in rows}) == 1
        out[season] = same_sign and same_bh
    return out


def build_payload(
    daily_by_region: dict[str, pd.Series],
    enso: pd.DataFrame,
    n_perm: int = 10000,
    seed: int = 0,
    source: str = SOURCE,
) -> dict:
    """All variants plus the robustness flags. ``daily_by_region`` keys: ``polygon``, ``rectangle``."""
    variants = {
        name: build_variant(daily_by_region[spec["region"]], enso, spec, n_perm, seed)
        for name, spec in VARIANTS.items()
    }
    idx = daily_by_region["polygon"].index
    return {
        "meta": {
            "period": f"{idx[0]:%Y-%m-%d}/{idx[-1]:%Y-%m-%d}",
            "season_years_period": f"{YEAR_MIN}-{YEAR_MAX}",
            "source": source,
            "n_perm": n_perm,
            "seed": seed,
            "alpha": ALPHA,
        },
        "variants": variants,
        "robust": robust_flags(variants),
    }


# --- report --------------------------------------------------------------------------------

_clean = ar_enso._clean
_num = ar_enso._num


def count_sentence(row: dict) -> str:
    """ "5 de 7 inviernos Niño y 3 de 7 inviernos Niña tuvieron al menos un día extremo"."""
    noun = SEASON_NOUN[row["season"]]
    parts = []
    for phase, name in (("nino", "Niño"), ("nina", "Niña")):
        g = row["groups"][phase]
        parts.append(f"{g['years_with_extreme']} de {g['n']} {noun} {name}")
    return f"{parts[0]} y {parts[1]} tuvieron al menos un día extremo"


def _k_of_n(g: dict) -> str:
    return f"{g['years_with_extreme']} de {g['n']}"


def _c(x, nd: int = 2) -> str:
    """Decimal-comma number ("n/d" for None/NaN)."""
    return _num(x, nd).replace(".", ",")


def _pc(x) -> str:
    """p-value with decimal comma: 3 decimals below 0.1, else 2."""
    return _c(x, 3 if x is not None and not math.isnan(x) and x < 0.1 else 2)


def _row(variant: dict, season: str) -> dict:
    return next(r for r in variant["rows"] if r["season"] == season)


def _below(x) -> bool:
    return x is not None and not math.isnan(x) and x < ALPHA


def reading(rows: Sequence[dict], robust: bool) -> str:
    """Plain-language reading of one season across the variants' rows."""
    sustained = [bool(r["sustained_bh"]) for r in rows]
    if not any(sustained):
        return "ninguna variante sostiene diferencia"
    if all(sustained) and robust:
        return "diferencia sostenida en las tres"
    return "cambia según la variante"


def summary_bullet(season: str, variants: dict, robust: bool) -> str:
    """One Resumen bullet: main-variant counts and tests, ONI correlation under each variant."""
    rows = [_row(v, season) for v in variants.values()]
    m = rows[0]
    noun = SEASON_NOUN[season]
    g = m["groups"]
    counts = (
        f"{_k_of_n(g['nino'])} {noun} Niño y {_k_of_n(g['nina'])} {noun} Niña "
        "con al menos un día extremo"
    )
    verdict = "sostenido" if m["sustained_bh"] else "no sostenido"
    pair_reading = "igual en las tres variantes" if robust else "cambia según la variante"
    p_bh = [_pc(r["p_oni_bh"]) for r in rows]
    # The ONI correlation is outside the pre-fixed robust rule: it holds only if every variant agrees.
    oni_sig = [
        r["p_oni_bh"] is not None and not math.isnan(r["p_oni_bh"]) and r["p_oni_bh"] < ALPHA
        for r in rows
    ]
    if all(oni_sig):
        oni_reading = "se sostiene en las tres variantes"
    elif any(oni_sig):
        oni_reading = "no robusto"
    else:
        oni_reading = "no sostenido"
    return (
        f"- {season}: {counts}; Niño − Niña p {_pc(m['p'])} sin ajustar, p BH {_pc(m['p_bh'])} "
        f"({verdict}; {pair_reading}). ρ con el ONI {_c(m['spearman_rho'], 2)}, p BH {p_bh[0]} con "
        f"p99 en el polígono, {p_bh[1]} con p95 y {p_bh[2]} con el rectángulo: {oni_reading}."
    )


def write_report(payload: dict, path: Path | str) -> Path:
    """Write the Spanish Markdown report to ``path`` and the payload to the same name with ``.json``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta, variants = payload["meta"], payload["variants"]
    main_rows = variants["main"]["rows"]
    lines = [
        "# F1.9 — Días de lluvia extrema por fase ENSO (cordillera neuquina)",
        "",
        (
            "Pregunta: ¿cuántos días de lluvia extrema (≥ p99, el umbral de F1.4) caen en estaciones "
            "de El Niño, neutras y de La Niña, y cómo se relacionan con el ONI de la estación?"
        ),
        "",
        "## Fuente y alcance",
        "",
        f"- Fuente: {meta['source']}.",
        f"- Período de la serie diaria: {meta['period']}; estaciones-año completas {meta['season_years_period']}.",
        "- Región principal: polígono de cordillera de F1.3/F1.4 (aproximación, sin verificar).",
        "",
        "## Regla fijada antes de correr",
        "",
        "- Estaciones: DJF, MAM, JJA, SON; diciembre va al DJF del año siguiente; se descartan las incompletas en los bordes.",
        "- Día extremo: media diaria de la región ≥ cuantil de todos los días del registro (interpolación lineal).",
        "- Por estación-año: número de días extremos y si hubo al menos uno.",
        (
            f"- Fase: media del ONI ({io_enso.SOURCE}) de los tres meses; Niño ≥ +{io_enso.NINO_THRESHOLD}, "
            f"Niña ≤ {io_enso.NINA_THRESHOLD}, si no Neutro."
        ),
        (
            f"- Niño − Niña en la media de días extremos: permutación de etiquetas ({meta['n_perm']}, "
            f"semilla {meta['seed']}, bilateral). Prueba de 3 grupos: permutación con F de ANOVA. "
            "Contra el ONI: ρ de Spearman con p por permutación (se mezcla el ONI). "
            "BH sobre las 4 estaciones, por separado para cada p."
        ),
        "- Robusto: dirección de Niño − Niña y resultado BH coinciden en las tres variantes.",
        "",
        "## Umbrales",
        "",
        "| Variante | Cuantil | Umbral (mm/día) | Días extremos en el registro |",
        "|---|---|---|---|",
    ]
    for v in variants.values():
        lines.append(
            f"| {v['label']} | {_num(v['quantile'], 2)} | {_num(v['threshold_mm'], 1)} | "
            f"{v['n_extreme_days_total']} |"
        )
    lines += [
        "",
        (
            "Coincide con el umbral de F1.4 (29,2 mm/día)."
            if abs(variants["main"]["threshold_mm"] - F14_P99_MM) < 0.05
            else "No coincide con F1.4 (29,2 mm/día): revisar."
        ),
        "",
        "## Años por fase y estación",
        "",
        "| Estación | Niño | Neutro | Niña | Total |",
        "|---|---|---|---|---|",
    ]
    for r in main_rows:
        pc = r["phase_years"]
        lines.append(
            f"| {r['season']} | {pc['nino']} | {pc['neutral']} | {pc['nina']} | {sum(pc.values())} |"
        )
    lines += ["", "## Resultado principal", ""]
    for r in main_rows:
        lines.append(f"- {r['season']}: {count_sentence(r)}.")
    lines.append("")
    for v in variants.values():
        lines += [
            f"## Tabla — {v['label']}",
            "",
            (
                "| Estación | Niño: años con ≥1 día extremo; días totales | Neutro: años con ≥1 día extremo; "
                "días totales | Niña: años con ≥1 día extremo; días totales | Niño − Niña (días/estación) | "
                "p | p BH | p 3 grupos | ρ ONI | p ONI BH |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in v["rows"]:
            cells = [f"{_k_of_n(r['groups'][p])}; {r['groups'][p]['total_days']} d" for p in PHASES]
            lines.append(
                f"| {r['season']} | {' | '.join(cells)} | {_num(r['diff_nino_nina'], 2)} | "
                f"{_num(r['p'], 4)} | {_num(r['p_bh'], 4)} | {_num(r['p_3group'], 4)} | "
                f"{_num(r['spearman_rho'], 2)} | {_num(r['p_oni_bh'], 4)} |"
            )
        lines.append("")
    lines += [
        "## Sensibilidad",
        "",
        (
            "| Estación | p BH Niño − Niña (p99 pol. / p95 pol. / p99 rect.) | "
            "p ONI BH (p99 pol. / p95 pol. / p99 rect.) | ¿Robusto? (regla fijada) | Lectura |"
        ),
        "|---|---|---|---|---|",
    ]
    for season, ok in payload["robust"].items():
        rows = [_row(v, season) for v in variants.values()]
        pbh = " / ".join(_pc(r["p_bh"]) for r in rows)
        poni = " / ".join(_pc(r["p_oni_bh"]) for r in rows)
        lines.append(
            f"| {season} | {pbh} | {poni} | {'sí' if ok else 'no'} | {reading(rows, ok)} |"
        )
    lines += [
        "",
        (
            "«Robusto» sigue la regla fijada antes de correr (dirección y resultado BH coinciden en las "
            "tres variantes), así que una estación puede ser «no» solo porque el signo de la diferencia "
            "cambia alrededor de 0 mientras ninguna variante encuentra diferencia."
        ),
        "",
        "## Resumen",
        "",
    ]
    flagged = [
        season
        for season in payload["robust"]
        if any(
            _below(r[k])
            for v in variants.values()
            for r in [_row(v, season)]
            for k in ("p", "p_bh", "p_3group", "p_3group_bh", "p_oni", "p_oni_bh")
        )
    ]
    for season in flagged:
        lines.append(summary_bullet(season, variants, payload["robust"][season]))
    if not flagged:
        lines.append(
            "- Ninguna prueba de ninguna variante tiene p < 0,05, ni sin ajustar ni con BH."
        )
    lines += [
        "- ENSO se informa como contexto de los extremos, no como predictor.",
        "",
        "## Salvedades",
        "",
        "- Pocos años por fase: la prueba tiene poca potencia; no detectar no prueba que no exista.",
        "- Comparaciones múltiples: se ajusta con BH sobre 4 estaciones por tipo de prueba, no entre pruebas.",
        "- Los conteos de días extremos dentro de un año no son independientes (un mismo sistema da varios días).",
        "- ERA5 es un reanálisis, no datos de estaciones; la lluvia en terreno complejo puede estar subestimada.",
        "- El polígono es una aproximación sin verificar; el rectángulo cubre más área.",
        "- Análisis retrospectivo de asociación: no prueba causalidad ni es un sistema de alerta.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
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
    """Read the daily series once per region and write ``F1.9.md`` / ``F1.9.json``."""
    cat_meta = catalog.read_metadata(events_path)
    polygon = [tuple(v) for v in json.loads(cat_meta["polygon"])] if "polygon" in cat_meta else None
    polygon = polygon or catalog.CORDILLERA_POLYGON
    enso = io_enso.read_enso(enso_path)
    poly_mean, _ = extremes.daily_precip(era5_paths, polygon)
    rect_mean, _ = extremes.daily_precip(era5_paths, catalog.LEGACY_RECTANGLE)
    payload = build_payload({"polygon": poly_mean, "rectangle": rect_mean}, enso, n_perm, seed)
    write_report(payload, Path(out_dir) / "F1.9.md")
    return payload

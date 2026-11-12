"""Streamflow vs. ENSO and a GEV with an ONI covariate (plan/02, F2.7).

Question: do the annual maxima and the seasonal mean flow differ between El Niño, neutral and
La Niña years, and does a GEV whose location depends on ONI beat the stationary GEV? The result
decides whether the seasonal model F6.2 is worth building.

Decisions fixed before looking at results (odd/tasks/floods.md, S7):
- Hydrological year and complete-year rule exactly as F2.2 (``extremes.annual_maxima``); only complete
  years enter.
- Primary covariate: mean of the six monthly ONI values April-September (AMJJAS) of the hydrological
  year. The monthly ONI is itself a 3-month running mean (NOAA CPC), so adjacent months overlap.
  The year's ENSO phase is that mean classified with the thresholds of ``clima_nqn.io.enso``.
- Alternate covariate (sensitivity only): ONI of the season (DJF, MAM, JJA, SON, as in F1.8) in which
  the annual peak occurred.
- Seasonal mean flow = mean of the valid daily flows between 1 April and 30 September (the same AMJJAS
  window as the covariate) of each complete year.
- Phase test: permutation test, one-way ANOVA F over the three phases (``ar.enso``).
- GEV: stationary vs. ``mu = mu0 + mu1 * ONI`` with scale and shape constant, both by maximum
  likelihood (multi-start), compared with a likelihood-ratio test (chi-square, 1 df) and AIC.
  The standard error of ``mu1`` is Wald (numerical Hessian); the LRT is the inference to read.
- All p-values (phase tests and both LRTs, all stations) are BH-adjusted together.
- Verdict for F6.2: "señal" only if the primary-covariate LRT has BH-adjusted p < 0.05 at one of the
  analysis stations (12004, 12010); otherwise "sin señal". 12012 (short record) is computed but flagged
  as unreliable and does not enter the verdict.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import chi2, genextreme

from clima_nqn.io import enso as io_enso
from clima_nqn.io import flow
from clima_nqn.stages.ar import enso as ar_enso
from clima_nqn.stages.flood import extremes

ALPHA = 0.05
AMJJAS = (4, 5, 6, 7, 8, 9)
ANALYSIS_STATIONS = (12004, 12010)
DEFAULT_STATIONS = extremes.DEFAULT_STATIONS
N_PERM = 10000
SEED = 20260512
OUT_PATH = flow.OUT_DIR / "enso.json"
REPORT_PATH = Path(__file__).resolve().parents[5] / "reports" / "02" / "F2.7.md"
METRICS = {
    "q_max": "Máximo anual (m³/s)",
    "q_mean_amjjas": "Caudal medio abr–sep (m³/s)",
}
UNRELIABLE_NOTE = "registro corto (unos 25 años completos): GEV con covariable poco confiable"
_BIG = 1e10  # penalty for parameters outside the GEV support


# --- covariates and phase table --------------------------------------------------------------


def hydro_covariate(enso: pd.DataFrame, year: int) -> float:
    """Mean monthly ONI of April-September of hydrological year ``year`` (NaN if a month is missing)."""
    by_month = enso.set_index(enso["date"].dt.to_period("M"))["oni"]
    vals = []
    for m in AMJJAS:
        key = pd.Period(year=year, month=m, freq="M")
        if key not in by_month.index:
            return math.nan
        vals.append(float(by_month[key]))
    return float(np.mean(vals))


def station_table(df: pd.DataFrame, enso: pd.DataFrame, start_month: int = 4) -> pd.DataFrame:
    """One row per complete hydrological year: annual maximum, AMJJAS mean flow, ONI and phase.

    Years whose primary covariate is not available are dropped. ``oni_peak`` is NaN when the ONI of
    the peak's season is not available (the primary table is not affected).
    """
    maxima, _ = extremes.annual_maxima(df, start_month)
    valid = df.dropna(subset=["q_m3s"])
    rows = []
    for r in maxima.itertuples():
        y = int(r.hydro_year)
        z = hydro_covariate(enso, y)
        if math.isnan(z):
            continue
        in_window = valid["date"].dt.year.eq(y) & valid["date"].dt.month.between(4, 9)
        season = ar_enso.season_of_month(int(r.date.month))
        _, s_year = ar_enso.season_year(pd.DatetimeIndex([r.date]))
        oni_peak, _ = ar_enso.seasonal_oni(enso, season, int(s_year[0]))
        rows.append(
            {
                "hydro_year": y,
                "peak_date": r.date,
                "q_max": float(r.q_m3s),
                "q_mean_amjjas": float(valid.loc[in_window, "q_m3s"].mean()),
                "oni_amjjas": z,
                "phase": str(io_enso.classify_phase(pd.Series([z])).iloc[0]),
                "peak_season": season,
                "oni_peak": oni_peak,
            }
        )
    return pd.DataFrame(rows)


def phase_tests(table: pd.DataFrame, n_perm: int = N_PERM, seed: int = SEED) -> dict:
    """Per metric: n, mean and sd per phase, Niño-Niña difference and the 3-group permutation test."""
    lab = table["phase"].to_numpy(object)
    out = {}
    for key in METRICS:
        v = table[key].to_numpy(float)
        means, sds, ns = {}, {}, {}
        for p in ar_enso.PHASES:
            x = v[(lab == p) & ~np.isnan(v)]
            ns[p] = len(x)
            means[p], sds[p] = ar_enso._mean_sd(x)
        test = ar_enso.permutation_test_groups(v, lab, ar_enso.PHASES, n_perm, seed)
        out[key] = {
            "n": ns,
            "means": means,
            "sds": sds,
            "diff_nino_nina": means["nino"] - means["nina"],
            "f": test["stat"],
            "p": test["p"],
        }
    return out


# --- GEV with a covariate --------------------------------------------------------------------


def _nll(theta: np.ndarray, y: np.ndarray, z: np.ndarray) -> float:
    mu0, mu1, log_sigma, xi = theta
    if not -2.0 < xi < extremes.MAX_XI or abs(log_sigma) > 50:
        return _BIG
    ll = genextreme.logpdf(y, -xi, loc=mu0 + mu1 * z, scale=math.exp(log_sigma))
    return _BIG if not np.all(np.isfinite(ll)) else float(-ll.sum())


def _hessian(f, x: np.ndarray, h: float = 1e-3) -> np.ndarray:
    n = len(x)
    hess = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            ei, ej = np.eye(n)[i] * h, np.eye(n)[j] * h
            hess[i, j] = hess[j, i] = (
                f(x + ei + ej) - f(x + ei - ej) - f(x - ei + ej) + f(x - ei - ej)
            ) / (4 * h * h)
    return hess


def _loglik(y, z, mu0, mu1, sigma, xi) -> float:
    return float(np.sum(genextreme.logpdf(y, -xi, loc=mu0 + mu1 * z, scale=sigma)))


def compare_gev(y, z) -> dict:
    """Stationary vs. ``mu = mu0 + mu1 * z`` GEV by maximum likelihood, LRT (1 df) and AIC.

    The stationary fit is the F2.2 estimator (``extremes.GEV``). The covariate model is optimised in
    standardised units from several starts (the stationary optimum with ``mu1 = 0``, the OLS slope,
    and three shapes), so it can never end below the stationary likelihood.
    """
    y, z = np.asarray(y, dtype=float), np.asarray(z, dtype=float)
    n = len(y)
    c_s, loc_s, scale_s = extremes.GEV.fit(y)
    ll_s = _loglik(y, z, loc_s, 0.0, scale_s, -c_s)

    ym, ysd = float(y.mean()), float(y.std())
    zm, zsd = float(z.mean()), float(z.std()) or 1.0
    ys, zs = (y - ym) / ysd, (z - zm) / zsd  # standardised: loc = a + b * zs
    slope = float(np.polyfit(zs, ys, 1)[0])
    gumbel_scale = max(float(np.std(ys)) * math.sqrt(6) / math.pi, 1e-3)
    starts = [np.array([(loc_s - ym) / ysd, 0.0, math.log(scale_s / ysd), -c_s])]
    for xi0 in (-0.2, 0.0, 0.2, 0.4):
        for b0 in (0.0, slope):
            starts.append(np.array([-0.5772 * gumbel_scale, b0, math.log(gumbel_scale), xi0]))
    best = None
    for s in starts:
        res = minimize(_nll, s, args=(ys, zs), method="Nelder-Mead",
                       options={"maxiter": 4000, "xatol": 1e-9, "fatol": 1e-11, "adaptive": True})  # fmt: skip
        res = minimize(_nll, res.x, args=(ys, zs), method="Nelder-Mead",
                       options={"maxiter": 4000, "xatol": 1e-10, "fatol": 1e-12, "adaptive": True})  # fmt: skip
        if best is None or res.fun < best.fun:
            best = res
    a, b, log_s, xi = best.x
    sigma = math.exp(log_s) * ysd
    # standardised location a + b * zs  ->  mu0 + mu1 * z
    mu1 = b * ysd / zsd
    mu0 = ym + a * ysd - mu1 * zm
    ll_ns = _loglik(y, z, mu0, mu1, sigma, xi)
    if ll_ns < ll_s:  # numerical safety: nested model, fall back to the stationary optimum
        mu0, mu1, sigma, xi, ll_ns = loc_s, 0.0, scale_s, -c_s, ll_s
    cov = None
    try:
        cov = np.linalg.inv(_hessian(lambda t: _nll(t, ys, zs), best.x))
        se_b = math.sqrt(cov[1, 1]) if cov[1, 1] > 0 else math.nan
    except np.linalg.LinAlgError:
        se_b = math.nan
    se = se_b * ysd / zsd
    stat = max(0.0, 2.0 * (ll_ns - ll_s))
    aic_s, aic_ns = 2 * 3 - 2 * ll_s, 2 * 4 - 2 * ll_ns
    return {
        "n": n,
        "stationary": {
            "mu": float(loc_s),
            "sigma": float(scale_s),
            "xi": float(-c_s),
            "loglik": ll_s,
            "aic": aic_s,
        },
        "nonstationary": {
            "mu0": float(mu0),
            "mu1": float(mu1),
            "mu1_se": se,
            "mu1_ci95_low": float(mu1 - 1.96 * se),
            "mu1_ci95_high": float(mu1 + 1.96 * se),
            "sigma": float(sigma),
            "xi": float(xi),
            "loglik": ll_ns,
            "aic": aic_ns,
        },
        "lrt": {"statistic": stat, "df": 1, "p": float(chi2.sf(stat, 1))},
        "delta_aic": aic_ns - aic_s,
    }


# --- station ---------------------------------------------------------------------------------


def station_result(
    df: pd.DataFrame,
    meta: dict,
    enso: pd.DataFrame,
    reliable: bool = True,
    n_perm: int = N_PERM,
    seed: int = SEED,
) -> dict:
    """Phase tests and both GEV comparisons of one station (p-values not yet BH-adjusted)."""
    table = station_table(df, enso, meta.get("hydro_year_start_month", 4))
    if len(table) < 10:
        raise ValueError(f"station {meta['id']}: only {len(table)} complete years with ONI")
    valid = df.dropna(subset=["q_m3s"])
    n_complete = len(extremes.annual_maxima(df, meta.get("hydro_year_start_month", 4))[0])
    alt = table.dropna(subset=["oni_peak"])
    return {
        "station_id": int(meta["id"]),
        "name": meta.get("name"),
        "river": meta.get("river"),
        "source": df.attrs.get("source", flow.SOURCE),
        "url": df.attrs.get("url", flow.SNIH_URL),
        "fetched": df.attrs.get("fetched"),
        "period": f"{valid['date'].min():%Y-%m-%d}/{valid['date'].max():%Y-%m-%d}",
        "n_years": len(table),
        "n_complete_years": n_complete,
        "years_used": [int(y) for y in table["hydro_year"]],
        "unreliable": not reliable,
        "unreliable_note": None if reliable else UNRELIABLE_NOTE,
        "phase_tests": phase_tests(table, n_perm, seed),
        "primary": compare_gev(table["q_max"], table["oni_amjjas"]),
        "alternate": compare_gev(alt["q_max"], alt["oni_peak"]),
        "alternate_n_years": len(alt),
    }


def apply_bh(results: list[dict]) -> None:
    """BH-adjust, in place, every p-value of the report together (phase tests and both LRTs)."""
    slots = []
    for r in results:
        for m in METRICS:
            slots.append(r["phase_tests"][m])
        slots.append(r["primary"]["lrt"])
        slots.append(r["alternate"]["lrt"])
    for slot, adj in zip(slots, ar_enso.bh_adjust([s["p"] for s in slots]), strict=True):
        slot["p_bh"] = adj


def verdict(results: list[dict], analysis: Sequence[int] = ANALYSIS_STATIONS) -> str:
    """ "señal" only if the primary LRT has BH-adjusted p < 0.05 at an analysis station."""
    for r in results:
        p = r["primary"]["lrt"]["p_bh"]
        if r["station_id"] in analysis and not math.isnan(p) and p < ALPHA:
            return "señal"
    return "sin señal"


# --- report ----------------------------------------------------------------------------------


def _n(x, nd: int = 2) -> str:
    return (
        "n/d"
        if x is None or (isinstance(x, float) and math.isnan(x))
        else f"{x:,.{nd}f}".replace(",", " ")
    )


def _p(x) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/d"
    return "< 0,001" if x < 0.001 else f"{x:.3f}".replace(".", ",")


def build_report(results: list[dict], meta: dict) -> str:
    lines = [
        "# F2.7 — Caudal y ENSO: máximos anuales por fase y GEV con ONI como covariable",
        "",
        (
            "Retrospectivo: compara años según la fase de ENSO; no es un pronóstico ni un sistema de alerta. "
            "Decide si se hace el modelo estacional F6.2."
        ),
        "",
        f"**Veredicto F6.2: {meta['verdict']}**",
        "",
        (
            'Regla (fijada antes de ver los resultados): "señal" solo si el test de razón de verosimilitud de la '
            'covariable primaria tiene p ajustado por BH < 0,05 en 12004 o 12010; si no, "sin señal". 12012 no '
            "entra en el veredicto."
        ),
        "",
        "## Fuente y método",
        "",
        f"- Caudal: {flow.SOURCE} ({flow.SNIH_URL}), caudal medio diario (m³/s); citar al SIPH/SNIH. Fecha de la última consulta por estación en cada sección.",
        (
            f"- ENSO: {io_enso.SOURCE} ({io_enso.ONI_URL}), ONI mensual {meta['oni_period']}. "
            "Fecha de descarga del ONI: sin verificar (el Parquet no la guarda). Fase: ONI ≥ +0,5 Niño, "
            "≤ −0,5 Niña, el resto neutro; no se exige persistencia de cinco meses (fases por año, no por evento)."
        ),
        (
            "- Año hidrológico y regla de año completo como en F2.2 (inicio en abril, etiquetado por el año de inicio; "
            f"al menos {flow.MIN_VALID_DAYS} días válidos). Solo entran años completos con ONI disponible."
        ),
        (
            "- Covariable primaria: media del ONI mensual de abril a septiembre (AMJJAS) del año hidrológico. El ONI "
            "mensual ya es un promedio móvil de tres meses, de modo que meses vecinos se solapan. Covariable alternativa "
            "(solo sensibilidad): ONI de la estación (DJF, MAM, JJA, SON) en que ocurrió el pico anual."
        ),
        (
            "- Caudal estacional: media de los caudales diarios válidos de abril a septiembre (la misma ventana "
            "AMJJAS que la covariable)."
        ),
        (
            f"- Test por fase: permutación (estadístico F de ANOVA de una vía sobre Niño, neutro y Niña; {meta['n_perm']} "
            f"permutaciones, semilla {meta['seed']}). El tamaño de efecto es la diferencia de medias Niño − Niña."
        ),
        (
            "- GEV: estacionaria frente a ubicación μ = μ₀ + μ₁·ONI con escala σ y forma ξ constantes; ambas por máxima "
            "verosimilitud (scipy, varios puntos de partida); la estacionaria usa el mismo estimador que F2.2. Se comparan "
            "con el test de razón de verosimilitud (χ², 1 gl) y con AIC (ΔAIC = AIC con covariable − AIC estacionaria; "
            "negativo favorece la covariable). El error estándar de μ₁ es de Wald (hessiano numérico); con ξ ≥ 0,5 el "
            "estimador no es regular y se lee con cautela."
        ),
        (
            "- Todos los valores p (tests por fase y los dos LRT, todas las estaciones) se ajustan juntos por "
            f"Benjamini-Hochberg ({meta['n_tests']} tests)."
        ),
        "",
        "## Salvedades",
        "",
        "- Los años no son independientes entre sí en el sentido del ONI (persistencia interanual); los valores p son aproximados.",
        "- El LRT usa la distribución χ² asintótica; con unas decenas de años es aproximada.",
        "- Que haya o no señal no prueba causalidad ni predictibilidad; F6.2 usaría ONI como predictor.",
        "- Resultados de una sola covariable fijada de antemano; la alternativa no se usa para decidir.",
        "",
    ]
    for r in results:
        pt, pr, al = r["phase_tests"], r["primary"], r["alternate"]
        lines += [
            f"## {r['station_id']} {r['name']} ({r['river']})",
            "",
        ]
        if r["unreliable"]:
            lines += [
                f"> **Poco confiable:** {r['unreliable_note']}. Se calcula pero no entra en el veredicto.",
                "",
            ]
        lines += [
            f"- Período con datos: {r['period']}; última consulta: {r['fetched']}.",
            f"- Años completos usados: {r['n_years']} ({r['years_used'][0]}–{r['years_used'][-1]}); con ONI de la estación del pico: {r['alternate_n_years']}."
            + (
                f" Años completos sin ONI (el ONI empieza en {meta['oni_period'][:4]}): {r['n_complete_years'] - r['n_years']}, "
                "por eso n difiere de F2.2."
                if r["n_complete_years"] > r["n_years"]
                else ""
            ),
            "",
            "### Por fase de ENSO (covariable primaria)",
            "",
            "| Variable | n Niño / neutro / Niña | Media Niño | Media neutro | Media Niña | Niño − Niña | p | p BH |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for key, label in METRICS.items():
            m = pt[key]
            n = m["n"]
            lines.append(
                f"| {label} | {n['nino']} / {n['neutral']} / {n['nina']} | {_n(m['means']['nino'], 0)} | "
                f"{_n(m['means']['neutral'], 0)} | {_n(m['means']['nina'], 0)} | {_n(m['diff_nino_nina'], 0)} | "
                f"{_p(m['p'])} | {_p(m['p_bh'])} |"
            )
        lines += [
            "",
            "### GEV con ONI como covariable",
            "",
            "| Covariable | n | ξ estacionaria | μ₁ (m³/s por unidad de ONI) | IC 95 % de μ₁ (Wald) | EE | LRT χ² | p | p BH | ΔAIC |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for label, c in (("Primaria: ONI abr–sep", pr), ("Alternativa: ONI del pico", al)):
            ns = c["nonstationary"]
            lines.append(
                f"| {label} | {c['n']} | {_n(c['stationary']['xi'], 3)} | {_n(ns['mu1'], 1)} | "
                f"{_n(ns['mu1_ci95_low'], 1)} – {_n(ns['mu1_ci95_high'], 1)} | {_n(ns['mu1_se'], 1)} | "
                f"{_n(c['lrt']['statistic'], 2)} | {_p(c['lrt']['p'])} | {_p(c['lrt']['p_bh'])} | {_n(c['delta_aic'], 2)} |"
            )
        lines += [""]
        if pr["stationary"]["xi"] >= 0.5:
            lines += [
                "- Aviso: ξ ≥ 0,5 en la GEV estacionaria; el estimador no es regular y los errores estándar son poco fiables.",
                "",
            ]
    return "\n".join(lines)


def write_outputs(results: list[dict], meta: dict, out: Path | str, report: Path | str) -> None:
    out, report = Path(out), Path(report)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"verdict": meta["verdict"], "meta": meta, "stations": results}
    out.write_text(
        json.dumps(ar_enso._clean(payload), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(build_report(results, meta), encoding="utf-8")


# --- entry point -----------------------------------------------------------------------------


def run(
    flow_dir: Path | str = flow.OUT_DIR,
    enso_path: Path | str = io_enso.DEFAULT_PATH,
    out: Path | str = OUT_PATH,
    report: Path | str = REPORT_PATH,
    stations: Sequence[int] | None = None,
    analysis: Sequence[int] = ANALYSIS_STATIONS,
    n_perm: int = N_PERM,
    seed: int = SEED,
) -> dict:
    """Phase tests and GEV-with-ONI comparison per station -> JSON and Markdown report."""
    flow_dir = Path(flow_dir)
    meta_all = {
        s["id"]: s for s in json.loads((flow_dir / "stations.json").read_text())["stations"]
    }
    enso = io_enso.read_enso(enso_path)
    results = []
    for sid in stations or DEFAULT_STATIONS:
        df = flow.read_flow(flow_dir / f"{sid}.parquet")
        results.append(
            station_result(
                df, meta_all[sid], enso, reliable=sid in analysis, n_perm=n_perm, seed=seed
            )
        )
    apply_bh(results)
    meta = {
        "verdict": verdict(results, analysis),
        "analysis_stations": list(analysis),
        "n_perm": n_perm,
        "seed": seed,
        "n_tests": len(results) * (len(METRICS) + 2),
        "oni_source": io_enso.SOURCE,
        "oni_url": io_enso.ONI_URL,
        "oni_period": f"{enso['date'].min():%Y-%m}/{enso['date'].max():%Y-%m}",
        "rule": (
            "señal solo si el LRT de la covariable primaria tiene p BH < 0,05 en 12004 o 12010; "
            "si no, sin señal"
        ),
    }
    write_outputs(results, meta, out, report)
    return {"meta": meta, "stations": results}

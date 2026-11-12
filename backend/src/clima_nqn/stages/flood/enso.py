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
- Addendum covariate (L12, corrected after review): the single JFM ONI value, the three-month value dated
  February (months January-March). The first run averaged the January-, February- and March-dated values,
  which reach April; the gate rule did not change.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
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
JFM_MONTH = 2  # the ONI file dates each 3-month value by its central month: JFM is dated February
MIN_YEARS = 10  # fewest complete years with ONI a station needs for any fit
SHORT_RECORD_YEARS = 30  # fewer complete years than this -> short record (same threshold as F2.3)
ANALYSIS_STATIONS = (12004, 12010)
DEFAULT_STATIONS = extremes.DEFAULT_STATIONS
N_PERM = 10000
ADDENDUM_STATIONS = (12004, 12010)
GATE_STATION = 12010
RESTRICTED_YEARS = (1953, 2009)  # hydrological years of the restricted refit (check c)
XI_WARN = 0.1  # |xi with covariate - xi stationary| above this -> the Wald interval is flagged
READING = "Lectura: señal débil, concurrente, sostenida por una estación"
SEED = 20260512
OUT_PATH = flow.OUT_DIR / "enso.json"
REPORT_PATH = Path(__file__).resolve().parents[5] / "reports" / "02" / "F2.7.md"
METRICS = {
    "q_max": "Máximo anual (m³/s)",
    "q_mean_amjjas": "Caudal medio abr–sep (m³/s)",
}
NOT_IN_VERDICT_NOTE = "no entra en el veredicto (no figura entre las estaciones de análisis)"


def unreliable_note(n_complete: int) -> str:
    return (
        f"registro corto ({n_complete} años completos, menos de {SHORT_RECORD_YEARS}): "
        "GEV con covariable poco confiable"
    )


def rule_text(analysis: Sequence[int]) -> str:
    """The verdict rule naming the analysis stations actually used."""
    where = " o ".join(str(s) for s in analysis)
    return (
        f"señal solo si el LRT de la covariable primaria tiene p BH < 0,05 en {where}; "
        "si no, sin señal"
    )


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


def jfm_covariate(enso: pd.DataFrame, year: int) -> float:
    """The single JFM ONI value of calendar ``year``: the three-month value dated February (its underlying
    months are January-March, all before 1 April, when the hydrological year ``year`` starts). NaN if missing."""
    by_month = enso.set_index(enso["date"].dt.to_period("M"))["oni"]
    key = pd.Period(year=year, month=JFM_MONTH, freq="M")
    return float(by_month[key]) if key in by_month.index else math.nan


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
                "oni_jfm": jfm_covariate(enso, y),
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


def _nll(theta: np.ndarray, y: np.ndarray, design: np.ndarray) -> float:
    """Negative log-likelihood; ``theta = (beta..., log_sigma, xi)`` and ``mu = design @ beta``."""
    log_sigma, xi = theta[-2], theta[-1]
    if not -2.0 < xi < extremes.MAX_XI or abs(log_sigma) > 50:
        return _BIG
    ll = genextreme.logpdf(y, -xi, loc=design @ theta[:-2], scale=math.exp(log_sigma))
    return _BIG if not np.all(np.isfinite(ll)) else float(-ll.sum())


def _nll_fast(theta: np.ndarray, y: np.ndarray, design: np.ndarray) -> float:
    """``_nll`` with the GEV density written out (same value, about 10x faster; used by the permutations)."""
    log_sigma, xi = theta[-2], theta[-1]
    if not -2.0 < xi < extremes.MAX_XI or abs(log_sigma) > 50:
        return _BIG
    sigma = math.exp(log_sigma)
    w = (y - design @ theta[:-2]) / sigma
    if abs(xi) < 1e-8:  # Gumbel limit
        ll = -log_sigma - w - np.exp(-w)
    else:
        t = 1.0 + xi * w
        if np.any(t <= 0):
            return _BIG
        ll = -log_sigma - (1.0 + 1.0 / xi) * np.log(t) - t ** (-1.0 / xi)
    return _BIG if not np.all(np.isfinite(ll)) else float(-ll.sum())


def _minimize(ys: np.ndarray, design: np.ndarray, starts: list, passes: int = 2, nll=_nll):
    """Best Nelder-Mead optimum of ``nll`` over several starts (``passes`` restarts each)."""
    tols = ((1e-9, 1e-11), (1e-10, 1e-12))
    best = None
    for s in starts:
        res = None
        for xatol, fatol in tols[:passes]:
            res = minimize(nll, s if res is None else res.x, args=(ys, design), method="Nelder-Mead",
                           options={"maxiter": 4000, "xatol": xatol, "fatol": fatol, "adaptive": True})  # fmt: skip
        if best is None or res.fun < best.fun:
            best = res
    return best


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
    design = np.column_stack([np.ones(n), zs])
    best = _minimize(ys, design, starts)
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
        cov = np.linalg.inv(_hessian(lambda t: _nll(t, ys, design), best.x))
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


# --- robustness addendum (odd/tasks/floods.md, L12): post-hoc, never changes the verdict --------


def _stationary_start(y: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Standardised ``y`` and the stationary optimum as a start ``(a, b=0, log_sigma, xi)``."""
    ym, ysd = float(y.mean()), float(y.std())
    c_s, loc_s, scale_s = extremes.GEV.fit(y)
    ys = (y - ym) / ysd
    return ys, ysd, np.array([(loc_s - ym) / ysd, 0.0, math.log(scale_s / ysd), -c_s])


def _lrt_stat(ys: np.ndarray, zs: np.ndarray, start0: np.ndarray) -> float:
    """LRT statistic of ``mu = a + b*z`` against the stationary optimum ``start0`` (same likelihood and
    optimiser as ``compare_gev``, two starts: ``b = 0`` and ``b`` = correlation)."""
    design = np.column_stack([np.ones(len(ys)), zs])
    b0 = float(np.corrcoef(ys, zs)[0, 1]) if np.std(zs) > 0 else 0.0
    start1 = start0.copy()
    start1[1] = b0
    best = _minimize(ys, design, [start0, start1], nll=_nll_fast)
    return max(0.0, 2.0 * (_nll_fast(start0, ys, design) - float(best.fun)))


def _perm_chunk(args) -> int:
    """Count of permuted statistics >= ``thr`` for a chunk of permutation indices (process-pool worker)."""
    ys, zs, start0, perms, thr = args
    return sum(_lrt_stat(ys, zs[idx], start0) >= thr for idx in perms)


def permutation_lrt(
    y, z, n_perm: int = N_PERM, seed: int = SEED, workers: int | None = None
) -> dict:
    """Permutation p of the LRT for ``mu = mu0 + mu1*z``: z is shuffled across years and the model refitted.

    p = (count(stat_perm >= stat_obs) + 1) / (n_perm + 1). The observed and permuted statistics use
    the same fit, so they are comparable (it matches ``compare_gev`` to optimiser tolerance).
    """
    y, z = np.asarray(y, dtype=float), np.asarray(z, dtype=float)
    ys, _, start0 = _stationary_start(y)
    zs = (z - z.mean()) / (float(z.std()) or 1.0)
    obs = _lrt_stat(ys, zs, start0)
    rng = np.random.default_rng(seed)
    thr = obs - 1e-9 * max(1.0, abs(obs))
    perms = [
        rng.permutation(len(zs)) for _ in range(n_perm)
    ]  # drawn here, so workers do not change them
    workers = min(os.cpu_count() or 1, 8) if workers is None and n_perm >= 500 else (workers or 1)
    if workers > 1:
        chunks = [(ys, zs, start0, perms[i::workers], thr) for i in range(workers)]
        with ProcessPoolExecutor(workers) as pool:
            k = sum(pool.map(_perm_chunk, chunks))
    else:
        k = _perm_chunk((ys, zs, start0, perms, thr))
    return {
        "stat": obs,
        "p": (k + 1) / (n_perm + 1),
        "n_perm": n_perm,
        "n_ge": int(k),
        "seed": seed,
    }


def _fit_nested(ys: np.ndarray, design: np.ndarray, extra: np.ndarray | None = None):
    """Multi-start fit of a GEV whose location is ``design @ beta`` (scale and shape constant)."""
    k = design.shape[1]
    beta_ols = np.linalg.lstsq(design, ys, rcond=None)[0]
    g = max(float(np.std(ys)) * math.sqrt(6) / math.pi, 1e-3)
    starts = [] if extra is None else [extra]
    for xi0 in (-0.2, 0.0, 0.2, 0.4):
        for beta in (np.zeros(k), beta_ols):
            b = beta.copy()
            b[0] += -0.5772 * g
            starts.append(np.concatenate([b, [math.log(g), xi0]]))
    return _minimize(ys, design, starts)


def trend_control(y, z, year) -> dict:
    """``mu = mu0 + mu1*z + mu2*year`` against ``mu = mu0 + mu2*year``: LRT for ``mu1`` (1 df).

    z and year are centred and scaled for fitting (numerical stability); ``mu1`` is reported per unit of z
    and ``mu2`` per year.
    """
    y, z, year = (np.asarray(v, dtype=float) for v in (y, z, year))
    n = len(y)
    ym, ysd = float(y.mean()), float(y.std())
    zm, zsd = float(z.mean()), float(z.std()) or 1.0
    tm, tsd = float(year.mean()), float(year.std()) or 1.0
    ys, zs, ts = (y - ym) / ysd, (z - zm) / zsd, (year - tm) / tsd
    ones = np.ones(n)
    red = _fit_nested(ys, np.column_stack([ones, ts]))
    full_design = np.column_stack([ones, zs, ts])
    extra = np.array([red.x[0], 0.0, red.x[1], red.x[2], red.x[3]])  # reduced optimum with mu1 = 0
    full = _fit_nested(ys, full_design, extra)
    ll_red, ll_full = -float(red.fun) - n * math.log(ysd), -float(full.fun) - n * math.log(ysd)
    stat = max(0.0, 2.0 * (ll_full - ll_red))
    a, b1, b2, log_s, xi = full.x
    mu1, mu2 = b1 * ysd / zsd, b2 * ysd / tsd
    try:
        cov = np.linalg.inv(_hessian(lambda t: _nll(t, ys, full_design), full.x))
        se1 = math.sqrt(cov[1, 1]) * ysd / zsd if cov[1, 1] > 0 else math.nan
    except np.linalg.LinAlgError:
        se1 = math.nan
    return {
        "n": n,
        "year_scaling": "centered and scaled for fitting; mu2 reported per year",
        "reduced": {"xi": float(red.x[3]), "mu2": float(red.x[1] * ysd / tsd), "loglik": ll_red},
        "nonstationary": {
            "mu1": float(mu1),
            "mu1_se": se1,
            "mu2": float(mu2),
            "sigma": float(math.exp(log_s) * ysd),
            "xi": float(xi),
            "loglik": ll_full,
        },
        "lrt": {"statistic": stat, "df": 1, "p": float(chi2.sf(stat, 1))},
        "mu0_standardised": float(a),
    }


def f62_gate(lag_perm_p: float, lag_mu1: float, primary_mu1: float) -> bool:
    """Gate for F6.2 (fixed after the primary result, before the addendum): the lagged LRT at 12010 has
    permutation p < 0.05 and its mu1 has the same sign as the primary mu1."""
    if any(isinstance(v, float) and math.isnan(v) for v in (lag_perm_p, lag_mu1, primary_mu1)):
        return False
    return (
        lag_perm_p < ALPHA
        and lag_mu1 != 0
        and primary_mu1 != 0
        and (lag_mu1 > 0) == (primary_mu1 > 0)
    )


def _restricted(sub: pd.DataFrame, lo: int, hi: int) -> dict:
    """Check (c), restricted period: the primary model refitted on ``sub``; unavailable with too few years."""
    if len(sub) < MIN_YEARS:
        return {
            "years": [lo, hi],
            "n": len(sub),
            "available": False,
            "note": f"no disponible: {len(sub)} años",
        }
    return {
        "years": [lo, hi],
        "available": True,
        **compare_gev(sub["q_max"], sub["oni_amjjas"]),
    }


def station_addendum(
    df: pd.DataFrame, meta: dict, enso: pd.DataFrame, n_perm: int = N_PERM, seed: int = SEED
) -> dict:
    """The three checks of L12 for one station (raw p-values, outside the BH family)."""
    table = station_table(df, enso, meta.get("hydro_year_start_month", 4))
    y, z = table["q_max"].to_numpy(float), table["oni_amjjas"].to_numpy(float)
    lagged_t = table.dropna(subset=["oni_jfm"])
    yl, zl = lagged_t["q_max"].to_numpy(float), lagged_t["oni_jfm"].to_numpy(float)
    lag = compare_gev(yl, zl)
    lag_perm = permutation_lrt(yl, zl, n_perm, seed)
    corr = float(np.corrcoef(lagged_t["oni_jfm"], lagged_t["oni_amjjas"])[0, 1])
    lo, hi = RESTRICTED_YEARS
    sub = table[table["hydro_year"].between(lo, hi)]
    return {
        "station_id": int(meta["id"]),
        "n_perm": n_perm,
        "seed": seed,
        "permutation_primary": {"n": len(y), **permutation_lrt(y, z, n_perm, seed)},
        "lagged": {
            "n": len(yl),
            "mu1": lag["nonstationary"]["mu1"],
            "mu1_ci95_low": lag["nonstationary"]["mu1_ci95_low"],
            "mu1_ci95_high": lag["nonstationary"]["mu1_ci95_high"],
            "xi_stationary": lag["stationary"]["xi"],
            "xi_nonstationary": lag["nonstationary"]["xi"],
            "lrt_statistic": lag["lrt"]["statistic"],
            "lrt_p": lag["lrt"]["p"],
            "permutation_p": lag_perm["p"],
            "permutation_stat": lag_perm["stat"],
            "corr_with_amjjas": corr,
        },
        "trend": trend_control(y, z, table["hydro_year"].to_numpy(float)),
        "restricted": _restricted(sub, lo, hi),
    }


def addendum_gate(stations: dict, primary_mu1: dict, gate_station: int = GATE_STATION) -> dict:
    """Evaluate the L12 gate mechanically from the addendum of ``gate_station``."""
    st = stations.get(gate_station)
    base = {
        "station_id": gate_station,
        "rule": "LRT rezagado en 12010 con p de permutación < 0,05 y μ₁ del mismo signo que el primario",
        "consequence_if_fails": "si no pasa, F6.2 corre sin ENSO o queda en los baselines",
    }
    if st is None or gate_station not in primary_mu1:
        return {
            **base,
            "passes": False,
            "outcome": "no pasa",
            "note": "estación de la compuerta no calculada",
        }
    lag = st["lagged"]
    ok = f62_gate(lag["permutation_p"], lag["mu1"], primary_mu1[gate_station])
    return {
        **base,
        "lagged_permutation_p": lag["permutation_p"],
        "lagged_mu1": lag["mu1"],
        "primary_mu1": primary_mu1[gate_station],
        "passes": ok,
        "outcome": "pasa" if ok else "no pasa",
    }


def passes_rule(r: dict) -> bool:
    """The verdict rule at one station: primary LRT with BH-adjusted p < ALPHA."""
    p = r["primary"]["lrt"]["p_bh"]
    return not math.isnan(p) and p < ALPHA


def reading_line(results: list[dict], verdict_: str, analysis: Sequence[int] = ANALYSIS_STATIONS):
    """``READING`` only if the verdict is "señal" and exactly one analysis station passes the rule."""
    n_pass = sum(passes_rule(r) for r in results if r["station_id"] in analysis)
    return READING if verdict_ == "señal" and n_pass == 1 else None


def build_addendum(results: list[dict], enso: pd.DataFrame, flow_dir: Path, meta_all: dict,
                   n_perm: int, seed: int) -> dict | None:  # fmt: skip
    """Addendum for the stations of ``ADDENDUM_STATIONS`` present in ``results``; None if there is none."""
    ids = [r["station_id"] for r in results if r["station_id"] in ADDENDUM_STATIONS]
    if not ids:
        return None
    stations = {}
    for sid in ids:
        df = flow.read_flow(flow_dir / f"{sid}.parquet")
        stations[sid] = station_addendum(df, meta_all[sid], enso, n_perm, seed)
    primary_mu1 = {r["station_id"]: r["primary"]["nonstationary"]["mu1"] for r in results}
    return {
        "label": "posterior al resultado, no cambia el veredicto",
        "n_perm": n_perm,
        "seed": seed,
        "stations": stations,
        "gate": addendum_gate(stations, primary_mu1),
        "note": "valores p crudos; no se agregan a la familia BH de los tests originales",
    }


# --- station ---------------------------------------------------------------------------------


def station_result(
    df: pd.DataFrame,
    meta: dict,
    enso: pd.DataFrame,
    in_verdict: bool = True,
    n_perm: int = N_PERM,
    seed: int = SEED,
) -> dict:
    """Phase tests and both GEV comparisons of one station (p-values not yet BH-adjusted).

    ``unreliable`` depends only on the number of complete years (short record); ``in_verdict`` says whether
    the station is among the analysis stations. The two are independent.
    """
    table = station_table(df, enso, meta.get("hydro_year_start_month", 4))
    if len(table) < MIN_YEARS:
        raise ValueError(f"station {meta['id']}: only {len(table)} complete years with ONI")
    valid = df.dropna(subset=["q_m3s"])
    n_complete = len(extremes.annual_maxima(df, meta.get("hydro_year_start_month", 4))[0])
    alt = table.dropna(subset=["oni_peak"])
    short = n_complete < SHORT_RECORD_YEARS
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
        "unreliable": short,
        "unreliable_note": unreliable_note(n_complete) if short else None,
        "in_verdict": in_verdict,
        "verdict_note": None if in_verdict else NOT_IN_VERDICT_NOTE,
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


def _join_y(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} y {items[-1]}"


def build_report(results: list[dict], meta: dict, addendum: dict | None = None) -> str:
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
    ]
    reading = reading_line(results, meta["verdict"], meta["analysis_stations"])
    if reading:
        analysis_res = [r for r in results if r["station_id"] in meta["analysis_stations"]]
        tests = [r["phase_tests"][m] for r in analysis_res for m in METRICS]
        n_ph = sum(1 for t in tests if not math.isnan(t["p_bh"]) and t["p_bh"] < ALPHA)
        lines += [
            f"**{reading}**",
            "",
            "Razones que respalda la evidencia:",
            "",
            "- 12010 (Agrio) está dentro de la cuenca de 12004: las dos estaciones no son evidencia independiente.",
            "- La covariable (ONI abr–sep) se solapa con la estación de crecidas (abril–septiembre): es una asociación concurrente, no un pronóstico.",
            f"- Tests por fase con p BH < 0,05 (12004 y 12010): {n_ph} de {len(tests)}.",
            "",
        ]
    analysis_where = " o ".join(str(s) for s in meta["analysis_stations"])
    excluded = [
        str(r["station_id"]) for r in results if r["station_id"] not in meta["analysis_stations"]
    ]
    excluded_sentence = (
        f" {_join_y(excluded)} {'no entra' if len(excluded) == 1 else 'no entran'} en el veredicto."
        if excluded
        else ""
    )
    lines += [
        (
            'Regla: "señal" solo si el test de razón de verosimilitud de la covariable primaria tiene p ajustado por '
            f'BH < 0,05 en {analysis_where}; si no, "sin señal".{excluded_sentence} La covariable, la '
            "alternativa, la familia BH y las estaciones se fijaron en la especificación antes de la corrida; el umbral "
            '"p BH < 0,05 en 12004 o 12010" se fijó en el encargo de la tarea antes de la corrida, sin registro previo '
            "en la especificación ni en un commit."
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
            tail = (
                "Se calcula pero no entra en el veredicto."
                if not r["in_verdict"]
                else "Entra en el veredicto por figurar entre las estaciones de análisis; se lee con cautela."
            )
            lines += [f"> **Poco confiable:** {r['unreliable_note']}. {tail}", ""]
        elif not r["in_verdict"]:
            lines += [f"> Esta estación {r['verdict_note']}.", ""]
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
            "| Covariable | n | ξ estacionaria | ξ con covariable | μ₁ (m³/s por unidad de ONI) | IC 95 % de μ₁ (Wald) | EE | LRT χ² | p | p BH | ΔAIC |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for label, c in (("Primaria: ONI abr–sep", pr), ("Alternativa: ONI del pico", al)):
            ns = c["nonstationary"]
            lines.append(
                f"| {label} | {c['n']} | {_n(c['stationary']['xi'], 3)} | {_n(ns['xi'], 3)} | {_n(ns['mu1'], 1)} | "
                f"{_n(ns['mu1_ci95_low'], 1)} – {_n(ns['mu1_ci95_high'], 1)} | {_n(ns['mu1_se'], 1)} | "
                f"{_n(c['lrt']['statistic'], 2)} | {_p(c['lrt']['p'])} | {_p(c['lrt']['p_bh'])} | {_n(c['delta_aic'], 2)} |"
            )
        lines += [""]
        if any(abs(c["nonstationary"]["xi"] - c["stationary"]["xi"]) > XI_WARN for c in (pr, al)):
            lines += [
                (
                    f"- Aviso: ξ cambia más de {_n(XI_WARN, 1)} entre el modelo estacionario y el modelo con covariable; "
                    "el intervalo de Wald de μ₁ es aproximado en ese caso (se lee el LRT)."
                ),
                "",
            ]
        if pr["stationary"]["xi"] >= 0.5:
            lines += [
                "- Aviso: ξ ≥ 0,5 en la GEV estacionaria; el estimador no es regular y los errores estándar son poco fiables.",
                "",
            ]
    if addendum:
        lines += _addendum_lines(addendum, meta, results)
    return "\n".join(lines)


def _addendum_lines(ad: dict, meta: dict, results: list[dict]) -> list[str]:
    """Report section of the post-hoc robustness addendum (L12)."""
    st = ad["stations"]
    lines = [
        "## Adenda de robustez (posterior al resultado, no cambia el veredicto)",
        "",
        (
            "Tres comprobaciones declaradas después de conocer el resultado primario y antes de correr la adenda "
            "(odd/tasks/floods.md, L12), solo en 12004 y 12010; no se agregó ninguna después. No modifican el "
            f"veredicto ni los valores p de arriba. Los valores p de la adenda son crudos: no entran en la familia BH "
            f"de los {meta['n_tests']} tests originales y no se ajustan entre sí. Permutaciones: {ad['n_perm']}, semilla {ad['seed']}."
        ),
        "",
        (
            "Salvedad del mecanismo: F1.8 no encontró señal de ENSO en los conteos de ríos atmosféricos de 1980–2025, "
            "así que el mecanismo que vincularía ENSO con los picos de crecida es sin verificar."
        ),
        "",
        "### (a) p de permutación del LRT primario",
        "",
        "Se baraja el ONI abr–sep entre años, se reajusta el modelo y se compara el estadístico LRT (p = (k + 1) / (n + 1), k = permutaciones con estadístico ≥ el observado).",
        "",
        "| Estación | n años | LRT χ² | p χ² | p permutación |",
        "|---|---|---|---|---|",
    ]
    prim = {r["station_id"]: r for r in results}
    for sid, a in st.items():
        pp = a["permutation_primary"]
        lines.append(
            f"| {sid} | {pp['n']} | {_n(pp['stat'], 2)} | {_p(prim[sid]['primary']['lrt']['p'])} | {_p(pp['p'])} |"
        )
    lines += [
        "",
        "### (b) Covariable rezagada: ONI de enero–marzo (JFM) anterior al año hidrológico",
        "",
        (
            "Un único valor: el ONI trimestral de enero–marzo (JFM) del año calendario en que empieza el año hidrológico, "
            "que el archivo del ONI fecha en febrero (sus meses de base son enero a marzo, todos anteriores al 1 de abril). "
            "LRT contra la GEV estacionaria."
        ),
        "",
        (
            "Corrección posterior a la revisión: la primera corrida de la adenda promedió los valores fechados en enero, febrero y marzo, "
            "que abarcan de diciembre a abril y por lo tanto usaban datos de abril; se corrigió a este único valor JFM. "
            "La regla de la compuerta no cambió."
        ),
        "",
        "| Estación | n | μ₁ (m³/s por unidad de ONI) | IC 95 % (Wald, aproximado) | ξ estac. | ξ con cov. | LRT χ² | p χ² | p permutación | r con ONI abr–sep |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sid, a in st.items():
        g = a["lagged"]
        lines.append(
            f"| {sid} | {g['n']} | {_n(g['mu1'], 1)} | {_n(g['mu1_ci95_low'], 1)} – {_n(g['mu1_ci95_high'], 1)} | "
            f"{_n(g['xi_stationary'], 3)} | {_n(g['xi_nonstationary'], 3)} | {_n(g['lrt_statistic'], 2)} | "
            f"{_p(g['lrt_p'])} | {_p(g['permutation_p'])} | {_n(g['corr_with_amjjas'], 2)} |"
        )
    lines += [
        "",
        "El intervalo de Wald es aproximado cuando ξ cambia mucho entre los dos modelos; se lee el LRT.",
        "",
        "### (c) Control de tendencia y período 1953–2009",
        "",
        (
            "Tendencia: μ = μ₀ + μ₁·ONI + μ₂·año frente a μ = μ₀ + μ₂·año (LRT para μ₁, covariable primaria); el año se "
            "centra y escala para el ajuste (estabilidad numérica) y μ₂ se informa por año. Período acotado: modelo "
            "primario reajustado solo con los años hidrológicos 1953–2009."
        ),
        "",
        "| Estación | Modelo | n | μ₁ (m³/s por unidad de ONI) | μ₂ (m³/s por año) | ξ con cov. | LRT χ² | p χ² |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sid, a in st.items():
        t, rs = a["trend"], a["restricted"]
        lines.append(
            f"| {sid} | con tendencia | {t['n']} | {_n(t['nonstationary']['mu1'], 1)} | {_n(t['nonstationary']['mu2'], 2)} | "
            f"{_n(t['nonstationary']['xi'], 3)} | {_n(t['lrt']['statistic'], 2)} | {_p(t['lrt']['p'])} |"
        )
        label = f"primario {rs['years'][0]}–{rs['years'][1]}"
        if not rs["available"]:
            lines.append(f"| {sid} | {label} | {rs['n']} | {rs['note']} | n/d | n/d | n/d | n/d |")
            continue
        lines.append(
            f"| {sid} | {label} | {rs['n']} | {_n(rs['nonstationary']['mu1'], 1)} | n/d | "
            f"{_n(rs['nonstationary']['xi'], 3)} | {_n(rs['lrt']['statistic'], 2)} | {_p(rs['lrt']['p'])} |"
        )
    g = ad["gate"]
    detail = (
        f" (p de permutación del LRT rezagado en {g['station_id']}: {_p(g['lagged_permutation_p'])}; "
        f"μ₁ rezagado {_n(g['lagged_mu1'], 1)} frente a μ₁ primario {_n(g['primary_mu1'], 1)})"
        if "lagged_mu1" in g
        else f" ({g['note']})"
    )
    lines += [
        "",
        (
            f"**Compuerta para F6.2: {g['outcome']}**{detail}. Regla: {g['rule']}. Consecuencia: {g['consequence_if_fails']}. "
            "La compuerta se fijó después del resultado primario y antes de correr la adenda."
        ),
        "",
    ]
    return lines


def write_outputs(results: list[dict], meta: dict, out: Path | str, report: Path | str,
                  addendum: dict | None = None) -> None:  # fmt: skip
    out, report = Path(out), Path(report)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"verdict": meta["verdict"], "meta": meta, "stations": results}
    if addendum:
        payload["addendum"] = {
            **addendum,
            "stations": {str(k): v for k, v in addendum["stations"].items()},
        }
    out.write_text(
        json.dumps(ar_enso._clean(payload), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(build_report(results, meta, addendum), encoding="utf-8")


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
    addendum: bool = True,
    addendum_n_perm: int = N_PERM,
) -> dict:
    """Phase tests and GEV-with-ONI comparison per station -> JSON and Markdown report.

    With ``addendum`` the post-hoc robustness checks of L12 run for the stations 12004 and 12010 among
    those requested; they never change ``meta`` (verdict, BH family) or the station results.
    """
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
                df, meta_all[sid], enso, in_verdict=sid in analysis, n_perm=n_perm, seed=seed
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
        "rule": rule_text(analysis),
    }
    ad = (
        build_addendum(results, enso, flow_dir, meta_all, addendum_n_perm, seed)
        if addendum
        else None
    )
    write_outputs(results, meta, out, report, ad)
    return {"meta": meta, "stations": results} | ({"addendum": ad} if ad else {})

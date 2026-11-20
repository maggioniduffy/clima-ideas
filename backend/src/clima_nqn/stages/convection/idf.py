"""IDF curves for Neuquén from IMERG only (F3.3, plan/03-convection.md).

Label: "IDF solo con IMERG, sin corrección de sesgo". IMERG under-reads intense point rain
(F3.0/F3.1: 7/4/2014 IMERG 92 mm/day vs station 118 mm/24 h). An optional correction
``f(depth_mm) -> depth_mm`` (F3.4) can be passed and is applied to the annual maxima before fitting.

Pure functions: ``annual_maxima``, ``fit_gev_lmom``, ``gev_quantile``, ``idf_table``.
Run: ``uv run python -m clima_nqn.stages.convection.idf``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

LABEL = "IDF solo con IMERG, sin corrección de sesgo"
DURATIONS_H: tuple[float, ...] = (0.5, 1, 2, 3, 6, 12, 24)
RETURN_PERIODS: tuple[float, ...] = (2, 5, 10, 25, 50, 100)
STEP_H = 0.5  # IMERG half-hour step
NEUQUEN_AERO = (-38.949, -68.156)
EULER_GAMMA = 0.5772156649015329
SEED = 20261120
N_BOOT = 1000

Params = tuple[float, float, float]  # (xi location, alpha scale, k Hosking shape; k = -shape_xi)

REPO_ROOT = Path(__file__).resolve().parents[5]
ZARR_PATH = REPO_ROOT / "backend/data/raw/imerg/neuquen.zarr"
OUT_PATH = REPO_ROOT / "backend/data/processed/idf/imerg_neuquen_idf.parquet"


# --------------------------------------------------------------------------- annual maxima
def hydro_year(index: pd.DatetimeIndex, start_month: int = 7) -> np.ndarray:
    """Hydrological year label = calendar year in which the year starts (July–June by default)."""
    idx = pd.DatetimeIndex(index)
    return np.where(idx.month >= start_month, idx.year, idx.year - 1)


def annual_maxima(
    series: pd.Series,
    durations: Sequence[float] = DURATIONS_H,
    *,
    start_month: int = 7,
    step_h: float = STEP_H,
) -> pd.DataFrame:
    """Annual maxima (mm) of rolling sums over consecutive steps, per hydrological year.

    ``series`` is depth per step (mm, e.g. mm/h * 0.5), indexed by step start. Windows never cross a
    hydrological-year boundary. Incomplete years (any missing/NaN step or missing timestamp) are dropped
    and listed in ``result.attrs["dropped_years"]``. Returns index ``hydro_year``, one column per duration.
    """
    s = series.sort_index()
    years = hydro_year(s.index, start_month)
    out: dict[int, dict[float, float]] = {}
    dropped: list[int] = []
    for y in np.unique(years):
        g = s[years == y]
        start = pd.Timestamp(year=int(y), month=start_month, day=1)
        end = start + pd.DateOffset(years=1)
        expected = round((end - start) / pd.Timedelta(hours=step_h))
        if len(g) != expected or g.isna().any():
            dropped.append(int(y))
            continue
        out[int(y)] = {}
        for d in durations:
            k = round(d / step_h)
            out[int(y)][d] = float(g.rolling(k).sum().max()) if k > 1 else float(g.max())
    df = pd.DataFrame.from_dict(out, orient="index", columns=list(durations)).sort_index()
    df.index.name = "hydro_year"
    df.attrs["dropped_years"] = dropped
    return df


# --------------------------------------------------------------------------- distributions
def lmoments(x: np.ndarray) -> tuple[float, float, float]:
    """Sample L-moments (l1, l2, t3) from probability-weighted moments (Hosking 1990)."""
    xs = np.sort(np.asarray(x, dtype=float))
    n = len(xs)
    i = np.arange(1, n + 1)
    b0 = xs.mean()
    b1 = np.sum((i - 1) / (n - 1) * xs) / n
    b2 = np.sum((i - 1) * (i - 2) / ((n - 1) * (n - 2)) * xs) / n
    l1, l2 = b0, 2 * b1 - b0
    l3 = 6 * b2 - 6 * b1 + b0
    return float(l1), float(l2), float(l3 / l2) if l2 > 0 else float("nan")


def fit_gev_lmom(x: np.ndarray, k_bounds: tuple[float, float] = (-0.9, 0.9)) -> Params:
    """GEV by L-moments (Hosking et al. 1985). Returns (xi, alpha, k); k = -shape (k < 0: heavy tail).

    k is clipped to ``k_bounds`` (only matters for pathological bootstrap resamples: k <= -1 has no mean).
    """
    l1, l2, t3 = lmoments(x)
    if not (l2 > 0) or not math.isfinite(t3):
        raise ValueError("degenerate sample: L-scale is not positive")
    c = 2.0 / (3.0 + t3) - math.log(2) / math.log(3)
    k = 7.8590 * c + 2.9554 * c * c
    k = min(max(k, k_bounds[0]), k_bounds[1])
    if abs(k) < 1e-6:  # Gumbel limit
        alpha = l2 / math.log(2)
        return l1 - EULER_GAMMA * alpha, alpha, 0.0
    g = math.gamma(1 + k)
    alpha = l2 * k / ((1 - 2.0**-k) * g)
    xi = l1 + alpha * (g - 1) / k
    return xi, alpha, k


def gev_quantile(params: Params, T: float | np.ndarray) -> float | np.ndarray:
    """GEV quantile for return period T (years, annual maxima)."""
    xi, alpha, k = params
    y = -np.log1p(-1.0 / np.asarray(T, dtype=float))  # -ln F, F = 1 - 1/T
    if abs(k) < 1e-6:
        return xi - alpha * np.log(y)
    return xi + alpha / k * (1 - y**k)


def gev_return_period(params: Params, x: float) -> float:
    """Return period (years) of depth ``x`` under the GEV; inf if beyond the upper bound (k > 0)."""
    xi, alpha, k = params
    if abs(k) < 1e-6:
        y = math.exp(-(x - xi) / alpha)
    else:
        arg = 1 - k * (x - xi) / alpha
        if arg <= 0:
            return math.inf
        y = arg ** (1 / k)
    F = math.exp(-y)
    return math.inf if F >= 1 else 1.0 / (1.0 - F)


def fit_gumbel_mom(x: np.ndarray) -> tuple[float, float]:
    """Gumbel by method of moments: (mu, beta), beta = s*sqrt(6)/pi, mu = mean - gamma*beta."""
    x = np.asarray(x, dtype=float)
    beta = float(np.std(x, ddof=1) * math.sqrt(6) / math.pi)
    return float(x.mean() - EULER_GAMMA * beta), beta


def gumbel_quantile(params: tuple[float, float], T: float | np.ndarray) -> float | np.ndarray:
    mu, beta = params
    return mu - beta * np.log(-np.log1p(-1.0 / np.asarray(T, dtype=float)))


def gumbel_return_period(params: tuple[float, float], x: float) -> float:
    mu, beta = params
    F = math.exp(-math.exp(-(x - mu) / beta))
    return math.inf if F >= 1 else 1.0 / (1.0 - F)


def weibull_positions(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sorted values and empirical return periods T = 1/(1-p), p = i/(n+1) (Weibull)."""
    xs = np.sort(np.asarray(x, dtype=float))
    n = len(xs)
    p = np.arange(1, n + 1) / (n + 1)
    return xs, 1.0 / (1.0 - p)


def empirical_quantile(x: np.ndarray, T: float) -> float:
    """Linear interpolation in ln T between Weibull plotting positions; NaN outside [T_min, n+1]."""
    xs, Ts = weibull_positions(x)
    if T < Ts[0] or T > Ts[-1]:
        return float("nan")
    return float(np.interp(math.log(T), np.log(Ts), xs))


# --------------------------------------------------------------------------- IDF table
def idf_table(
    am: pd.DataFrame,
    return_periods: Sequence[float] = RETURN_PERIODS,
    *,
    n_boot: int = N_BOOT,
    seed: int = SEED,
    ci: float = 0.90,
    correction: Callable[[np.ndarray], np.ndarray] | None = None,
) -> pd.DataFrame:
    """IDF table from annual maxima ``am`` (index years, columns durations in hours, depth mm).

    Methods: ``gev_lmom`` (main), ``gumbel_mom`` (baseline), ``empirical_weibull`` (no CI; only T <= n+1).
    CI: percentile bootstrap of the annual maxima (same resampled years for every duration and method).
    ``extrapolated`` marks T > 2 * n_years. ``correction`` maps depth_mm -> depth_mm and is applied to
    the annual maxima before fitting (F3.4 hook); ``None`` = no bias correction.
    """
    n = len(am)
    durations = [float(d) for d in am.columns]
    rng = np.random.default_rng(seed)
    boots = rng.integers(0, n, size=(n_boot, n))
    lo_q, hi_q = (1 - ci) / 2 * 100, (1 + ci) / 2 * 100
    Ts = np.asarray(return_periods, dtype=float)
    rows = []
    for d, col in zip(durations, am.columns, strict=True):
        x = am[col].to_numpy(dtype=float)
        if correction is not None:
            x = np.asarray(correction(x), dtype=float)
        gev_q = np.asarray(gev_quantile(fit_gev_lmom(x), Ts))
        gum_q = np.asarray(gumbel_quantile(fit_gumbel_mom(x), Ts))
        gev_b, gum_b = [], []
        for idx in boots:
            xb = x[idx]
            try:
                gev_b.append(gev_quantile(fit_gev_lmom(xb), Ts))
            except ValueError:
                pass
            if xb.std() > 0:
                gum_b.append(gumbel_quantile(fit_gumbel_mom(xb), Ts))
        gev_ci = np.percentile(np.asarray(gev_b), [lo_q, hi_q], axis=0)
        gum_ci = np.percentile(np.asarray(gum_b), [lo_q, hi_q], axis=0)
        for j, T in enumerate(Ts):
            extra = bool(T > 2 * n)
            for method, depth, lo, hi in (
                ("gev_lmom", gev_q[j], gev_ci[0, j], gev_ci[1, j]),
                ("gumbel_mom", gum_q[j], gum_ci[0, j], gum_ci[1, j]),
                ("empirical_weibull", empirical_quantile(x, T), np.nan, np.nan),
            ):
                if math.isnan(depth):
                    continue
                rows.append(
                    {
                        "duration_h": d,
                        "return_period_yr": float(T),
                        "method": method,
                        "depth_mm": float(depth),
                        "intensity_mm_h": float(depth) / d,
                        "ci_low": float(lo),  # CI of depth_mm
                        "ci_high": float(hi),
                        "ci_low_mm_h": float(lo) / d,  # same CI as intensity
                        "ci_high_mm_h": float(hi) / d,
                        "extrapolated": extra,
                    }
                )
    df = pd.DataFrame(rows)
    df.attrs.update(
        {
            "label": LABEL,
            "n_years": n,
            "ci_level": ci,
            "n_boot": n_boot,
            "seed": seed,
            "bias_correction": "none" if correction is None else "user-supplied",
        }
    )
    return df


def consistency_violations(table: pd.DataFrame, rel_tol: float = 1e-9) -> list[dict]:
    """Depth must not decrease with duration and intensity must not increase. Returns violations."""
    bad = []
    for (method, T), g in table.groupby(["method", "return_period_yr"]):
        g = g.sort_values("duration_h")
        d, dep, inten = (
            g["duration_h"].to_numpy(),
            g["depth_mm"].to_numpy(),
            g["intensity_mm_h"].to_numpy(),
        )
        for i in range(1, len(g)):
            if dep[i] < dep[i - 1] * (1 - rel_tol):
                bad.append(
                    {
                        "method": method,
                        "T": T,
                        "kind": "depth_decreases",
                        "from_h": d[i - 1],
                        "to_h": d[i],
                    }
                )
            if inten[i] > inten[i - 1] * (1 + rel_tol):
                bad.append(
                    {
                        "method": method,
                        "T": T,
                        "kind": "intensity_increases",
                        "from_h": d[i - 1],
                        "to_h": d[i],
                    }
                )
    return bad


def event_return_periods(
    am: pd.DataFrame,
    depths: dict[float, float],
    *,
    n_boot: int = N_BOOT,
    seed: int = SEED,
    ci: float = 0.90,
) -> pd.DataFrame:
    """Return period of an observed depth per duration (GEV and Gumbel) with bootstrap percentile range."""
    n = len(am)
    rng = np.random.default_rng(seed)
    boots = rng.integers(0, n, size=(n_boot, n))
    lo_q, hi_q = (1 - ci) / 2 * 100, (1 + ci) / 2 * 100
    rows = []
    for col in am.columns:
        x = am[col].to_numpy(dtype=float)
        dep = depths[float(col)]
        row = {
            "duration_h": float(col),
            "depth_mm": dep,
            "T_gev": gev_return_period(fit_gev_lmom(x), dep),
            "T_gumbel": gumbel_return_period(fit_gumbel_mom(x), dep),
        }
        tg = [gev_return_period(fit_gev_lmom(x[i]), dep) for i in boots]
        tm = [gumbel_return_period(fit_gumbel_mom(x[i]), dep) for i in boots]
        row["T_gev_lo"], row["T_gev_hi"] = np.percentile(tg, [lo_q, hi_q])
        row["T_gumbel_lo"], row["T_gumbel_hi"] = np.percentile(tm, [lo_q, hi_q])
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- IMERG driver
def _cell_series(precip: np.ndarray, times: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(precip * STEP_H, index=times)  # mm/h -> mm per half hour


def run(
    zarr_path: Path = ZARR_PATH,
    out_path: Path = OUT_PATH,
    correction: Callable[[np.ndarray], np.ndarray] | None = None,
) -> dict[str, pd.DataFrame]:
    """Build the IDF Parquet (main cell) and return main + sensitivity tables and annual maxima."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    import xarray as xr

    ds = xr.open_zarr(zarr_path, consolidated=False)
    lat0, lon0 = NEUQUEN_AERO
    i = int(np.abs(ds.lat.values - lat0).argmin())
    j = int(np.abs(ds.lon.values - lon0).argmin())
    block = ds.precipitation.isel(lat=slice(i - 1, i + 2), lon=slice(j - 1, j + 2)).load().values
    times = pd.DatetimeIndex(ds.time.values)
    main = _cell_series(block[:, 1, 1], times)
    mean3 = _cell_series(block.mean(axis=(1, 2)), times)

    am_main = annual_maxima(main)
    am_mean = annual_maxima(mean3)
    cells = [annual_maxima(_cell_series(block[:, a, b], times)) for a in range(3) for b in range(3)]
    am_max = pd.DataFrame(
        np.max([c.to_numpy() for c in cells], axis=0), index=am_main.index, columns=am_main.columns
    )

    tables = {
        "main": idf_table(am_main, correction=correction),
        "mean3x3": idf_table(am_mean, correction=correction),
        "max3x3": idf_table(am_max, correction=correction),
    }
    attrs = ds.attrs
    meta = {
        "label": LABEL,
        "source": attrs.get("source", ""),
        "product": attrs.get("product", ""),
        "doi": attrs.get("doi", ""),
        "period": f"hydrological years {am_main.index.min()}-{am_main.index.max() + 1} "
        f"(Jul {am_main.index.min()} to Jun {am_main.index.max() + 1}), n={len(am_main)}",
        "dropped_years": json.dumps(am_main.attrs["dropped_years"]),
        "cell_lat": f"{float(ds.lat.values[i]):.3f}",
        "cell_lon": f"{float(ds.lon.values[j]):.3f}",
        "target_lat_lon": f"{lat0},{lon0}",
        "fit": "GEV L-moments (main), Gumbel MoM (baseline), Weibull empirical; 90% CI bootstrap n=1000",
        "bias_correction": tables["main"].attrs["bias_correction"],
    }
    out = tables["main"].copy()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pandas(out, preserve_index=False)
    tbl = tbl.replace_schema_metadata(
        {**(tbl.schema.metadata or {}), **{k: str(v).encode() for k, v in meta.items()}}
    )
    pq.write_table(tbl, out_path)
    return {
        "am_main": am_main,
        "am_mean3": am_mean,
        "am_max3": am_max,
        **tables,
        "meta": pd.Series(meta),
    }


if __name__ == "__main__":
    res = run()
    print(res["main"].query("method == 'gev_lmom'").round(2).to_string(index=False))

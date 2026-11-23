"""Probabilistic scores for 3 ordered categories (low / mid / high tercile) and bootstrap skill."""

from __future__ import annotations

import numpy as np

N_BOOT = 1000
SEED = 20261122
CI = (2.5, 97.5)


def rps(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Ranked probability score per sample: sum over the first K-1 categories of (CDF_f - CDF_o)^2."""
    p = np.asarray(p, float)
    y = np.asarray(y, int)
    cf = np.cumsum(p, axis=1)[:, :-1]
    co = (y[:, None] <= np.arange(p.shape[1] - 1)[None, :]).astype(float)
    return ((cf - co) ** 2).sum(axis=1)


def brier(p: np.ndarray, y: np.ndarray, cls: int) -> np.ndarray:
    """Brier score of the event ``category == cls`` (0 = lower tercile, 2 = upper tercile)."""
    return (np.asarray(p, float)[:, cls] - (np.asarray(y) == cls)) ** 2


def year_means(values: np.ndarray, years: np.ndarray, mask: np.ndarray | None = None):
    """Mean of ``values`` per year (over ``mask``): ``(unique_years, means)``."""
    ok = np.isfinite(values) if mask is None else mask & np.isfinite(values)
    ys = np.unique(years[ok])
    return ys, np.array([values[ok & (years == y)].mean() for y in ys])


def skill_ci(model_by_year: np.ndarray, ref_by_year: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED):
    """``1 - mean(model)/mean(ref)`` over years with a bootstrap CI resampling years.

    Returns ``(skill, lo, hi)``; NaN when the reference mean is 0 or there are no years.
    """
    m, r = np.asarray(model_by_year, float), np.asarray(ref_by_year, float)
    n = len(m)
    if n == 0 or r.mean() == 0:
        return np.nan, np.nan, np.nan
    point = 1 - m.mean() / r.mean()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    den = r[idx].mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        boots = 1 - m[idx].mean(axis=1) / den
    boots = boots[np.isfinite(boots)]
    if len(boots) == 0:
        return float(point), np.nan, np.nan
    lo, hi = np.percentile(boots, CI)
    return float(point), float(lo), float(hi)

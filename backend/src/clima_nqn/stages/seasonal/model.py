"""Seasonal tercile model, baselines and nested selection (F6.2).

Design, fixed before seeing results
-----------------------------------
- Issue on the 1st of month M; lead k = 1..6 targets month M+k-1 (lead 1 = the month that starts on the
  issue date). Targets: tercile (low / mid / high) of the target-month value of (a) cordillera rain
  (ERA5 box 12004; sensitivity box 12010), (b) AR count (F1.3 catalog), (c) mean flow 12004 and 12010.
- Tercile classes per calendar month from the TRAINING target months of each fold only, with the
  mid-rank rule for ties: p = (n_below + 0.5 n_equal) / n; low if p < 1/3, high if p > 2/3, else mid.
  (Without ties this is the usual tercile split; AR counts have many ties, so the classes are not 1/3
  each; the number of tied labels is reported and ``clim_emp`` is the empirical-frequency baseline.)
- One model per target variable, POOLED over leads with the lead as a feature (per-lead logistic only
  as a sensitivity). Features available at issue (``data.py``): state anomalies, rain over 30/90 days
  ending 6 days before issue, target-month sin/cos, lead. Anomalies are per issue calendar month,
  standardized with training statistics. NO ENSO input (user decision 2026-11-22); ONI only for the
  ENSO-analog baseline and the per-phase scoring.
- Models: multinomial logistic (L2, C in a grid) and LightGBM multiclass (small grid). Hyperparameters
  and feature set in {S, SR, SRM} chosen by nested rolling-origin RPS over the outer-training years only.
- Baselines: ``clim`` (1/3 each), ``clim_emp`` (training class frequencies per target calendar month,
  Laplace +1), ``persist`` (tercile of the last fully available month at issue, one-hot; M-2 for rain
  and AR, M-1 for flow), ``persist_cond`` (training frequencies of the target class given the persistence
  class and lead, Laplace +1; extra, stronger than one-hot persistence), ``enso`` (training frequencies
  of the same issue month and lead with the same ONI phase at issue, Laplace +1).
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence

import numpy as np
import pandas as pd

from clima_nqn.stages.seasonal import folds
from clima_nqn.stages.seasonal.data import (
    ANOM_COLS,
    FEATURE_SETS,
    SELECTABLE_SETS,
    Samples,
)
from clima_nqn.stages.seasonal.score import rps

LOGIT_GRID = [{"C": c} for c in (0.01, 0.1, 1.0)]
LGBM_GRID = [
    {"num_leaves": nl, "min_child_samples": 50, "n_estimators": ne, "learning_rate": 0.05}
    for nl in (4, 8)
    for ne in (50, 120)
]
GRIDS = {"logit": LOGIT_GRID, "lgbm": LGBM_GRID}
MIN_INNER_YEARS = 15
INNER_BLOCK_YEARS = 5
LAPLACE = 1.0


# --- terciles --------------------------------------------------------------------------------


def tercile_classes(ref: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Classes 0/1/2 of ``x`` against the reference values ``ref`` (training only), mid-rank ties.

    Returns ``(classes, tied)``; ``tied`` marks values equal to some reference value.
    """
    ref = np.sort(np.asarray(ref, float))
    x = np.asarray(x, float)
    n = len(ref)
    lo = np.searchsorted(ref, x, side="left")
    hi = np.searchsorted(ref, x, side="right")
    p = (lo + 0.5 * (hi - lo)) / n
    cls = np.where(p < 1 / 3, 0, np.where(p > 2 / 3, 2, 1))
    cls = np.where(np.isnan(x), -1, cls)
    return cls.astype(int), (hi > lo)


def class_labels(
    series: pd.Series, ref_months: pd.DatetimeIndex, months: pd.DatetimeIndex, values: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Classes for ``values`` observed in ``months``, edges per calendar month from ``ref_months`` only."""
    ref_months = pd.DatetimeIndex(np.unique(np.asarray(ref_months)))
    ref_vals = series.reindex(ref_months)
    ref_vals = ref_vals[ref_vals.notna()]
    values = np.asarray(values, float)
    cls = np.full(len(values), -1, int)
    tied = np.zeros(len(values), bool)
    cal = pd.DatetimeIndex(months).month.values
    for m in np.unique(cal):
        sel = cal == m
        ref = ref_vals[ref_vals.index.month == m].values
        if len(ref) < 3:
            continue
        cls[sel], tied[sel] = tercile_classes(ref, values[sel])
    return cls, tied


def fold_labels(S: Samples, train_idx, idx) -> tuple[np.ndarray, np.ndarray]:
    """Labels of samples ``idx`` with edges from the target months of ``train_idx`` only."""
    tm = S.meta["target_month"]
    return class_labels(
        S.series, tm.iloc[train_idx].values, tm.iloc[idx].values, S.meta["y"].iloc[idx].values
    )


# --- features --------------------------------------------------------------------------------


class Prep:
    """Per issue-month anomalies from training rows (fit on training only) + raw columns."""

    def __init__(self, cols: Sequence[str]):
        self.cols = list(cols)

    def fit(self, X: pd.DataFrame, issue_month: np.ndarray) -> Prep:
        self.stats: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.anom = [c for c in self.cols if c in ANOM_COLS]
        if not self.anom:
            return self
        a = X[self.anom].values.astype(float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            gstd = np.nan_to_num(np.nanstd(a, axis=0))
            for m in np.unique(issue_month):
                v = a[issue_month == m]
                mu = np.nan_to_num(np.nanmean(v, axis=0))
                sd = np.nan_to_num(np.nanstd(v, axis=0))
                self.stats[int(m)] = (mu, np.maximum(sd, 0.1 * gstd + 1e-12))
        return self

    def transform(self, X: pd.DataFrame, issue_month: np.ndarray) -> np.ndarray:
        out = np.zeros((len(X), len(self.cols)))
        ai = {c: i for i, c in enumerate(self.anom)}
        for j, c in enumerate(self.cols):
            if c in ai:
                v = X[c].values.astype(float).copy()
                for m in np.unique(issue_month):
                    sel = issue_month == m
                    mu, sd = self.stats[int(m)]
                    v[sel] = (v[sel] - mu[ai[c]]) / sd[ai[c]]
                out[:, j] = np.nan_to_num(v)  # missing recent flow -> mean (0)
            elif c == "lead":
                out[:, j] = (X[c].values - 3.5) / 1.7
            else:
                out[:, j] = X[c].values
        return out


# --- models ----------------------------------------------------------------------------------


def _make(kind: str, cfg: dict):
    if kind == "logit":
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(C=cfg["C"], max_iter=1000)
    import lightgbm as lgb

    return lgb.LGBMClassifier(
        objective="multiclass", num_leaves=cfg["num_leaves"],
        min_child_samples=cfg["min_child_samples"], n_estimators=cfg["n_estimators"],
        learning_rate=cfg["learning_rate"], reg_lambda=1.0, n_jobs=1, random_state=0,
        verbose=-1, deterministic=True, force_row_wise=True,
    )  # fmt: skip


def fit_model(S: Samples, kind: str, cfg: dict, fset: str, train_idx, ytr=None):
    """Fit on ``train_idx``; returns ``(model, prep)``."""
    cols = FEATURE_SETS[fset]
    train_idx = np.asarray(train_idx)
    if ytr is None:
        ytr, _ = fold_labels(S, train_idx, train_idx)
    keep = ytr >= 0
    im = S.meta["issue"].dt.month.values
    prep = Prep(cols).fit(S.X.iloc[train_idx[keep]], im[train_idx[keep]])
    Xtr = prep.transform(S.X.iloc[train_idx[keep]], im[train_idx[keep]])
    mdl = _make(kind, cfg)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mdl.fit(Xtr, ytr[keep])
    return mdl, prep


def predict(S: Samples, mdl, prep: Prep, test_idx) -> np.ndarray:
    test_idx = np.asarray(test_idx)
    im = S.meta["issue"].dt.month.values
    Xte = prep.transform(S.X.iloc[test_idx], im[test_idx])
    proba = np.zeros((len(test_idx), 3))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        proba[:, mdl.classes_.astype(int)] = mdl.predict_proba(Xte)
    return proba


def fit_predict(S, kind, cfg, fset, train_idx, test_idx, ytr=None) -> np.ndarray:
    mdl, prep = fit_model(S, kind, cfg, fset, train_idx, ytr)
    return predict(S, mdl, prep, test_idx)


def inner_score(S: Samples, kind: str, cfg: dict, fset: str, inner, lead: int | None = None) -> float:
    """Mean RPS over the inner validation blocks (pooled samples)."""
    tot, n = 0.0, 0
    for tr, va in inner:
        if lead is not None:
            tr = tr[S.meta["lead"].values[tr] == lead]
            va = va[S.meta["lead"].values[va] == lead]
        if len(tr) < 30 or len(va) == 0:
            continue
        ytr, _ = fold_labels(S, tr, tr)
        yva, _ = fold_labels(S, tr, va)
        ok = yva >= 0
        p = fit_predict(S, kind, cfg, fset, tr, va[ok], ytr)
        r = rps(p, yva[ok])
        tot += r.sum()
        n += len(r)
    return tot / n if n else np.inf


def select(S: Samples, kind: str, train_idx, lead: int | None = None, sets=SELECTABLE_SETS):
    """Best ``(cfg, fset, score, table)`` by nested rolling-origin RPS inside ``train_idx``."""
    inner = folds.inner_folds(
        S.meta["issue"], S.meta["target_month"], train_idx, MIN_INNER_YEARS, INNER_BLOCK_YEARS
    )
    best, table = (None, None, np.inf), []
    for fset in sets:
        for cfg in GRIDS[kind]:
            sc = inner_score(S, kind, cfg, fset, inner, lead)
            table.append({"fset": fset, **cfg, "inner_rps": sc})
            if sc < best[2]:
                best = (cfg, fset, sc)
    if best[0] is None:  # no inner split (too few years): fall back to the first spec
        best = (GRIDS[kind][0], sets[0], np.nan)
    return best[0], best[1], best[2], table


# --- baselines -------------------------------------------------------------------------------


def baseline_probs(S: Samples, train_idx, test_idx) -> dict[str, np.ndarray]:
    """Baseline probabilities for ``test_idx`` using ``train_idx`` only (rows with NaN = undefined)."""
    m = S.meta
    train_idx, test_idx = np.asarray(train_idx), np.asarray(test_idx)
    ytr, _ = fold_labels(S, train_idx, train_idx)
    n = len(test_idx)
    out = {"clim": np.full((n, 3), 1 / 3)}

    # empirical frequencies per target calendar month, from the unique training target months
    tmu = pd.DatetimeIndex(np.unique(m["target_month"].values[train_idx]))
    cu, _ = class_labels(S.series, tmu, tmu, S.series.reindex(tmu).values)
    freq = {}
    for cal in range(1, 13):
        c = cu[(tmu.month == cal) & (cu >= 0)]
        cnt = np.bincount(c, minlength=3) + LAPLACE
        freq[cal] = cnt / cnt.sum()
    out["clim_emp"] = np.array([freq[t.month] for t in m["target_month"].iloc[test_idx]])

    # persistence classes (own calendar-month edges from training target months)
    pm = pd.DatetimeIndex(m["persist_month"].values)
    pc, _ = class_labels(S.series, tmu, pm, m["persist_val"].values)
    pc_te = pc[test_idx]
    pers = np.full((n, 3), np.nan)
    ok = pc_te >= 0
    pers[ok] = np.eye(3)[pc_te[ok]]
    out["persist"] = pers
    # conditional persistence: P(target class | persistence class, lead)
    tr_ok = (pc[train_idx] >= 0) & (ytr >= 0)
    pcond = np.full((n, 3), np.nan)
    lead = m["lead"].values
    for i, j in enumerate(test_idx):
        if pc[j] < 0:
            continue
        sel = tr_ok & (pc[train_idx] == pc[j]) & (lead[train_idx] == lead[j])
        cnt = np.bincount(ytr[sel], minlength=3) + LAPLACE
        pcond[i] = cnt / cnt.sum()
    out["persist_cond"] = pcond
    # ENSO analogs: same issue month, lead and ONI phase at issue
    ph = m["phase"].values
    im = m["issue"].dt.month.values
    en = np.full((n, 3), np.nan)
    for i, j in enumerate(test_idx):
        if not ph[j]:
            continue
        sel = (ytr >= 0) & (ph[train_idx] == ph[j]) & (im[train_idx] == im[j]) & (lead[train_idx] == lead[j])
        cnt = np.bincount(ytr[sel], minlength=3) + LAPLACE
        en[i] = cnt / cnt.sum()
    out["enso"] = en
    return out

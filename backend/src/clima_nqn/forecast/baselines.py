"""Baseline models for the 1-10 day horizon (F6.4 emission, start of the registry "con baselines solos").

Pure functions over a daily flow frame of ONE station (`date`, `q_m3s`, as written by ``io/flow``).

Models
------
* ``climatologia``: empirical quantiles of daily flow per day of year (window +-7 days, circular, Feb 29
  folded onto Feb 28) over the training period.
* ``persistencia``: last observed value; uncertainty from the empirical distribution of the log-ratio
  log Q(t+h)/Q(t) over the training period, per horizon h and month of the origin day (all months when the
  month has fewer than ``MIN_MONTH_PAIRS`` pairs). The quantile set is centered so its median is the last
  observed value; the exceedance probability uses the uncentered empirical ratios (conditional frequency).

High-flow threshold: "umbral provisional p95 del período de entrenamiento" - the 95th percentile of all daily
flows in the training period. It is a provisional choice of this task (F6.4 baselines), not the F6.7 / F2.2
flood threshold, and is stored in every record.

Lead and latency: the lead is counted from the ISSUE date. SNIH data arrive late, so persistence uses the last
observation <= issue date and its effective horizon is ``lead + lag`` (lag = issue date - last observation).

Leakage: only rows inside ``train_period`` (inclusive) are ever used for fitting; later rows are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
LEADS = tuple(range(1, 11))
WINDOW_DAYS = 7
THRESHOLD_QUANTILE = 0.95
THRESHOLD_NOTE = "umbral provisional p95 del período de entrenamiento"
MODELS = ("climatologia", "persistencia")
VAR_FLOW = "caudal_diario"
VAR_PROB = "p_caudal_alto"
MIN_MONTH_PAIRS = 30
_EPS = 0.01  # m3/s floor so log-ratios exist at zero flow

Period = tuple[date, date]


def parse_period(period: str | Period) -> Period:
    """'YYYY-MM-DD/YYYY-MM-DD' or a (start, end) pair -> (start, end) dates."""
    if isinstance(period, str):
        a, b = period.split("/")
        start, end = date.fromisoformat(a), date.fromisoformat(b)
    else:
        start, end = period
    if start > end:
        raise ValueError("train_period start is after its end")
    return start, end


def period_str(period: Period) -> str:
    return f"{period[0].isoformat()}/{period[1].isoformat()}"


def _series(flow: pd.DataFrame) -> pd.Series:
    s = flow.set_index(pd.to_datetime(flow["date"]))["q_m3s"].astype(float)
    return s[~s.index.duplicated()].sort_index()


def _training(flow: pd.DataFrame, period: Period) -> pd.Series:
    """Daily series restricted to the period (inclusive), reindexed to consecutive days (NaN gaps)."""
    s = _series(flow)
    s = s[(s.index >= pd.Timestamp(period[0])) & (s.index <= pd.Timestamp(period[1]))]
    if s.notna().sum() == 0:
        raise ValueError("no valid flow rows inside train_period")
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))


def day_of_year(index: pd.DatetimeIndex) -> np.ndarray:
    """Day of year 1..365 with Feb 29 folded onto Feb 28."""
    doy = np.asarray(index.day_of_year)
    leap = np.asarray(index.is_leap_year)
    return doy - (leap & (doy >= 60)).astype(int)


def wilson(k: float, n: float, z: float = 1.6449) -> tuple[float, float]:
    """Wilson score interval (90 %) for a frequency k/n; (0, 1) when n == 0."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return float(max(0.0, c - h)), float(min(1.0, c + h))


@dataclass(frozen=True)
class Climatology:
    threshold: float
    quantiles: np.ndarray  # (366, 5); row d = day of year d (row 0 unused)
    p_exceed: np.ndarray  # (366,)
    n_window: np.ndarray  # (366,) samples in each day-of-year window
    train_period: Period
    n_train: int

    def at(self, day: date | pd.Timestamp) -> tuple[np.ndarray, float, int]:
        d = int(day_of_year(pd.DatetimeIndex([pd.Timestamp(day)]))[0])
        return self.quantiles[d], float(self.p_exceed[d]), int(self.n_window[d])


def fit_climatology(flow: pd.DataFrame, train_period: str | Period) -> Climatology:
    period = parse_period(train_period)
    s = _training(flow, period).dropna()
    doy = day_of_year(s.index)
    vals = s.to_numpy()
    thr = float(np.quantile(vals, THRESHOLD_QUANTILE))
    q = np.full((366, len(LEVELS)), np.nan)
    pe = np.full(366, np.nan)
    nw = np.zeros(366, dtype=int)
    for d in range(1, 366):
        dist = np.abs(doy - d)
        w = vals[np.minimum(dist, 365 - dist) <= WINDOW_DAYS]
        nw[d] = len(w)
        if len(w):
            q[d] = np.quantile(w, LEVELS)
            pe[d] = float(np.mean(w > thr))
    return Climatology(thr, q, pe, nw, period, len(vals))


@dataclass
class Persistence:
    """Persistence with empirical log-ratio uncertainty; ratios are computed lazily per horizon."""

    threshold: float
    train_period: Period
    series: pd.Series = field(repr=False)
    _cache: dict[int, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict, repr=False)

    def ratios(self, h: int) -> tuple[np.ndarray, np.ndarray]:
        """(origin month, log Q(t+h)/Q(t)) over training pairs with both ends observed."""
        if h not in self._cache:
            s = self.series
            now, fut = s.to_numpy(), s.shift(-h).to_numpy()
            ok = ~np.isnan(now) & ~np.isnan(fut)
            lr = np.log(np.maximum(fut[ok], _EPS) / np.maximum(now[ok], _EPS))
            self._cache[h] = (np.asarray(s.index.month)[ok], lr)
        return self._cache[h]

    def forecast(self, last_value: float, origin: date, h: int) -> dict[str, Any]:
        """Quantiles and P(Q > threshold) ``h`` days after the last observation (made on ``origin``)."""
        months, all_lr = self.ratios(h)
        lr = all_lr[months == pd.Timestamp(origin).month]
        if len(lr) < MIN_MONTH_PAIRS:
            lr = all_lr
        if len(lr) == 0:
            raise ValueError(f"no training pairs for horizon {h}")
        q0 = max(last_value, _EPS)
        centered = lr - np.median(lr)  # median forecast = last observed value
        quant = q0 * np.exp(np.quantile(centered, LEVELS))
        exceed = q0 * np.exp(lr) > self.threshold
        return {
            "quantiles": quant,
            "p_exceed": float(exceed.mean()),
            "n_pairs": len(lr),
        }


def fit_persistence(
    flow: pd.DataFrame, train_period: str | Period, leads: range | tuple[int, ...] = LEADS
) -> Persistence:
    """Fit persistence; ratios for the given horizons are built now, others on demand."""
    period = parse_period(train_period)
    s = _training(flow, period)
    thr = float(np.quantile(s.dropna().to_numpy(), THRESHOLD_QUANTILE))
    p = Persistence(thr, period, s)
    for lead in leads:
        p.ratios(lead)
    return p


def last_observation(flow: pd.DataFrame, issue_date: date) -> tuple[date, float]:
    s = _series(flow).dropna()
    s = s[s.index <= pd.Timestamp(issue_date)]
    if s.empty:
        raise ValueError("no observation on or before the issue date")
    return s.index[-1].date(), float(s.iloc[-1])


def _quant_dict(q: np.ndarray) -> dict[str, float]:
    return {f"{lv:g}": float(v) for lv, v in zip(LEVELS, q, strict=True)}


def build_drafts(
    station: str,
    flow: pd.DataFrame,
    issue_date: datetime,
    model_version: str,
    train_period: str | Period,
    inputs: list[InputSource],
) -> list[PredictionDraft]:
    """The 10 leads x 2 variables x 2 models drafts for one station."""
    period = parse_period(train_period)
    day = issue_date.date()
    if period[1] > day:
        raise ValueError("train_period ends after the issue date")
    clim = fit_climatology(flow, period)
    pers = fit_persistence(flow, period)
    obs_date, obs_q = last_observation(flow, day)
    lag = (day - obs_date).days
    in_hash = hash_inputs(
        {
            "station": station,
            "train_period": period_str(period),
            "last_obs_date": obs_date.isoformat(),
            "last_obs_q_m3s": obs_q,
            "n_rows": int(_series(flow).notna().sum()),
            "inputs": [i.model_dump() for i in inputs],
        }
    )
    common: dict[str, Any] = {
        "issue_date": issue_date,
        "region": station,
        "training_period": period_str(period),
        "inputs": inputs,
        "inputs_sha256": in_hash,
        "interval_level": 0.9,
    }
    base = {
        "threshold_note": THRESHOLD_NOTE,
        "last_obs_date": obs_date.isoformat(),
        "lag_days": lag,
    }
    drafts: list[PredictionDraft] = []
    for lead in LEADS:
        valid = day + timedelta(days=lead)
        cq, cp, cn = clim.at(valid)
        h = lead + lag
        pf = pers.forecast(obs_q, obs_date, h)
        models = (
            ("climatologia", cq, cp, cn, clim.threshold, {}),
            (
                "persistencia",
                pf["quantiles"],
                pf["p_exceed"],
                pf["n_pairs"],
                pers.threshold,
                {"effective_horizon_days": h},
            ),
        )
        for name, quant, p, n, thr, extra in models:
            meta = {
                **common,
                "lead_days": lead,
                "valid_date": valid,
                "model_name": name,
                "model_version": f"{name}-{model_version}",
            }
            details = {**base, "threshold_m3s": thr, "n_samples": n, **extra}
            drafts.append(
                PredictionDraft(
                    **meta,
                    variable=VAR_FLOW,
                    kind="value",
                    value=float(quant[2]),
                    interval_low=float(quant[0]),
                    interval_high=float(quant[-1]),
                    details={**details, "quantiles": _quant_dict(quant)},
                )
            )
            lo, hi = wilson(p * n, n)
            drafts.append(
                PredictionDraft(
                    **meta,
                    variable=VAR_PROB,
                    kind="probability",
                    value=float(p),
                    interval_low=min(lo, p),
                    interval_high=max(hi, p),
                    details={**details, "clim_prob": float(cp)},
                )
            )
    return drafts


def emit(
    registry: PredictionRegistry,
    station: str,
    flow: pd.DataFrame,
    issue_date: datetime | date,
    model_version: str,
    train_period: str | Period,
    inputs: list[InputSource],
) -> list[PredictionRecord]:
    """Build and append the baseline predictions of one station; returns the appended records.

    ``model_version`` is stored as ``<model_name>-<model_version>`` so the two models do not collide on the
    registry's duplicate key (version, variable, region, lead, day).
    A plain ``date`` issue date is stamped with the registry clock, which must be on that day.
    """
    if not isinstance(issue_date, datetime):
        now = registry.now()
        if now.date() != issue_date:
            raise ValueError(f"issue date {issue_date} is not the registry's today ({now.date()})")
        issue_date = now
    drafts = build_drafts(station, flow, issue_date, model_version, train_period, inputs)
    return [registry.append(d) for d in drafts]

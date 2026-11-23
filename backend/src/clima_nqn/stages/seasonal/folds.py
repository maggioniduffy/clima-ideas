"""Leak-free partitions for the seasonal model (F6.2), as pure functions on sample dates.

A sample is (issue date, lead); its target month starts ``lead - 1`` months after the issue month
(lead 1 = the month that starts on the issue date). Hydrological year ``y`` runs April ``y`` to
March ``y+1`` and is labelled by its starting year; a sample belongs to the hydrological year of
its issue date.

- ``outer_folds``: each hydrological year is once the test (samples with issue in that year). The
  *zone* is [start - 6 months, end + 6 months) (end = the 1st of April after the year); every sample
  whose issue date OR target month (the whole month) touches the zone is out of training. The test
  targets that spill past March (up to August) fall inside the zone.
- ``inner_folds``: nested rolling origin over the outer-training samples only: sorted training
  hydrological years, the first ``min_years`` always train, then blocks of ``block_years`` validate.
  Inner train = outer-training samples issued before the block and whose target month ended before it.
- ``rolling_origin``: control; train strictly before year t (target months ended by April 1 of t),
  predict year t.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

GAP_MONTHS = 6


def hydro_year(ts) -> np.ndarray:
    """Hydrological year (April-March) labelled by its starting year, for datetimes."""
    idx = pd.DatetimeIndex(ts)
    return np.where(idx.month >= 4, idx.year, idx.year - 1)


def target_month_start(issue, lead) -> pd.DatetimeIndex:
    """First day of the target month: issue month + lead - 1 months."""
    iss = pd.DatetimeIndex(issue).to_period("M")
    return pd.DatetimeIndex(
        [(p + int(k) - 1).to_timestamp() for p, k in zip(iss, np.broadcast_to(lead, len(iss)))]
    )


def _next_month(ts: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return ts + pd.offsets.MonthBegin(1)


@dataclass(frozen=True)
class Fold:
    test_year: int
    train: np.ndarray  # positional indices
    test: np.ndarray
    gap: np.ndarray  # dropped from training because they touch the zone (test excluded)


def outer_folds(issue, target_month, test_years, gap_months: int = GAP_MONTHS) -> list[Fold]:
    issue = pd.DatetimeIndex(issue)
    tm = pd.DatetimeIndex(target_month)
    tm_end = _next_month(tm)  # exclusive
    folds = []
    for y in test_years:
        start, end = pd.Timestamp(int(y), 4, 1), pd.Timestamp(int(y) + 1, 4, 1)
        lo = start - pd.DateOffset(months=gap_months)
        hi = end + pd.DateOffset(months=gap_months)  # exclusive
        test = (issue >= start) & (issue < end)
        touches = ((issue >= lo) & (issue < hi)) | ((tm_end > lo) & (tm < hi))
        folds.append(
            Fold(int(y), np.flatnonzero(~touches), np.flatnonzero(test), np.flatnonzero(touches & ~test))
        )
    return folds


def inner_folds(
    issue, target_month, train_idx, min_years: int = 15, block_years: int = 5
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Nested rolling-origin ``(inner_train, validation)`` positional index pairs."""
    issue = pd.DatetimeIndex(issue)
    tm_end = _next_month(pd.DatetimeIndex(target_month))
    train_idx = np.asarray(train_idx)
    hy = hydro_year(issue[train_idx])
    years = np.unique(hy)
    out = []
    for j in range(min_years, len(years), block_years):
        val = train_idx[np.isin(hy, years[j : j + block_years])]
        val_start = issue[val].min()
        tr = train_idx[(issue[train_idx] < val_start) & (tm_end[train_idx] <= val_start)]
        if len(tr):
            out.append((tr, val))
    return out


def rolling_origin(issue, target_month, test_years) -> list[Fold]:
    issue = pd.DatetimeIndex(issue)
    tm_end = _next_month(pd.DatetimeIndex(target_month))
    folds = []
    for y in test_years:
        start, end = pd.Timestamp(int(y), 4, 1), pd.Timestamp(int(y) + 1, 4, 1)
        train = (issue < start) & (tm_end <= start)
        test = (issue >= start) & (issue < end)
        folds.append(Fold(int(y), np.flatnonzero(train), np.flatnonzero(test), np.array([], int)))
    return folds

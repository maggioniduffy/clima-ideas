"""IMERG bias against a station accumulation series, and quantile-mapping correction (plan/03 F3.4).

Pairs: for each station accumulation of ``period_h`` hours reported at ``T`` (UTC), the IMERG total over
``[T - period_h, T)`` at the nearest grid cell (main) and the 3x3 cell mean around it (sensitivity). IMERG
half-hourly times are the *start* of each half hour and the variable is a rate in mm/h, so each step is worth
``0.5`` mm per mm/h. Only windows with every half hour present are paired.

Usage (from ``backend/``)::

    uv run python -m clima_nqn.stages.convection.bias
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

WET_MM = 1.0
HALF_HOUR = pd.Timedelta(minutes=30)
STATION_LAT, STATION_LON = -38.949, -68.156


# ----------------------------------------------------------------------------------------------- pairs


def window_totals(rate: pd.Series, ends: pd.DatetimeIndex, period_h: int) -> np.ndarray:
    """IMERG totals (mm) over ``[end - period_h, end)`` for each end time; NaN where the window is incomplete.

    ``rate`` is mm/h indexed by half-hour start times (NaN = missing, absent times = missing). An end time that is
    not on a half-hour boundary gives NaN.
    """
    steps = int(period_h * 2)
    full = pd.date_range(rate.index.min(), rate.index.max(), freq=HALF_HOUR)
    vals = rate.reindex(full).to_numpy(dtype="float64")
    valid = ~np.isnan(vals)
    csum = np.concatenate([[0.0], np.cumsum(np.where(valid, vals, 0.0))])
    ccnt = np.concatenate([[0], np.cumsum(valid)])
    out = np.full(len(ends), np.nan)
    start0 = full[0]
    for k, end in enumerate(ends):
        offset = (end - start0) / HALF_HOUR
        if offset != int(offset):
            continue
        i1 = int(offset)  # index of first step NOT in the window
        i0 = i1 - steps
        if i0 < 0 or i1 > len(vals):
            continue
        if ccnt[i1] - ccnt[i0] == steps:
            out[k] = (csum[i1] - csum[i0]) * 0.5
    return out


def load_imerg_point(
    zarr_path: Path, lat: float = STATION_LAT, lon: float = STATION_LON
) -> tuple[pd.Series, pd.Series, tuple[float, float]]:
    """Nearest-cell and 3x3-mean rate series (mm/h) around a point, and the nearest cell's (lat, lon)."""
    import xarray as xr

    ds = xr.open_zarr(zarr_path, consolidated=False)
    i = int(np.abs(ds.lat.values - lat).argmin())
    j = int(np.abs(ds.lon.values - lon).argmin())
    block = ds["precipitation"].isel(lat=slice(i - 1, i + 2), lon=slice(j - 1, j + 2)).load()
    near = block.isel(lat=1, lon=1).to_series()
    mean9 = block.mean(dim=("lat", "lon"), skipna=False).to_series()
    return near, mean9, (float(ds.lat.values[i]), float(ds.lon.values[j]))


def build_pairs(
    station: pd.DataFrame, near: pd.Series, mean9: pd.Series, period_h: int
) -> pd.DataFrame:
    """Pairs for one accumulation period. ``station`` has ``time`` (report time) and ``depth_mm``, one row per window."""
    st = station.loc[station["period_h"] == period_h].sort_values("time")
    ends = pd.DatetimeIndex(st["time"])
    pairs = st.reset_index(drop=True).copy()
    pairs["imerg"] = window_totals(near, ends, period_h)
    pairs["imerg9"] = window_totals(mean9, ends, period_h)
    pairs = pairs.dropna(subset=["imerg", "imerg9"]).reset_index(drop=True)
    pairs["year"] = pairs["time"].dt.year
    return pairs.rename(columns={"depth_mm": "station"})


# --------------------------------------------------------------------------------------------- metrics


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    return float(pd.Series(x).rank().corr(pd.Series(y).rank()))


def total_ratio(imerg: np.ndarray, station: np.ndarray) -> float:
    s = float(np.sum(station))
    return float(np.sum(imerg)) / s if s > 0 else float("nan")


def bootstrap_ratio_ci(
    imerg: np.ndarray,
    station: np.ndarray,
    n_boot: int = 1000,
    seed: int = 20260101,
    level: float = 0.90,
) -> tuple[float, float]:
    """Percentile CI for sum(imerg)/sum(station), resampling pairs with replacement."""
    n = len(imerg)
    if n < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    num = imerg[idx].sum(axis=1)
    den = station[idx].sum(axis=1)
    ratios = num / np.where(den > 0, den, np.nan)
    lo, hi = np.nanpercentile(ratios, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return float(lo), float(hi)


def pair_metrics(pairs: pd.DataFrame, col: str = "imerg", wet: float = WET_MM) -> dict[str, float]:
    """n, years, contingency at ``wet`` mm, both-wet bias (total ratio + bootstrap CI + median ratio), Spearman."""
    x = pairs[col].to_numpy()
    y = pairs["station"].to_numpy()
    sw, iw = y >= wet, x >= wet
    hits = int(np.sum(sw & iw))
    misses = int(np.sum(sw & ~iw))
    false = int(np.sum(~sw & iw))
    both = sw & iw
    lo, hi = bootstrap_ratio_ci(x[both], y[both])
    return {
        "n": len(pairs),
        "years": int(pairs["year"].nunique()),
        "n_station_wet": int(sw.sum()),
        "n_imerg_wet": int(iw.sum()),
        "hits": hits,
        "misses": misses,
        "false_alarms": false,
        "pod": hits / (hits + misses) if hits + misses else float("nan"),
        "far": false / (hits + false) if hits + false else float("nan"),
        "n_both_wet": int(both.sum()),
        "sum_imerg": float(x[both].sum()),
        "sum_station": float(y[both].sum()),
        "ratio": total_ratio(x[both], y[both]),
        "ratio_lo": lo,
        "ratio_hi": hi,
        "median_ratio": float(np.median(x[both] / y[both])) if both.any() else float("nan"),
        "spearman_both_wet": spearman(x[both], y[both]),
        "spearman_all": spearman(x, y),
    }


def top_events(pairs: pd.DataFrame, k: int = 20, min_mm: float | None = None) -> pd.DataFrame:
    """Station's largest events (top ``k``, or every event >= ``min_mm``) with the IMERG value and ratio."""
    if min_mm is None:
        ev = pairs.nlargest(k, "station")
    else:
        ev = pairs.loc[pairs["station"] >= min_mm]
    ev = ev.sort_values("station", ascending=False).copy()
    ev["ratio"] = ev["imerg"] / ev["station"]
    ev["ratio9"] = ev["imerg9"] / ev["station"]
    return ev


# --------------------------------------------------------------------------------------- screening

MAX_P24_MM = 150.0
CORROB_ABS_MM = 5.0
CORROB_REL = 0.5


def corroborate_p24(p24: pd.DataFrame, p6: pd.DataFrame) -> pd.DataFrame:
    """Flag each 24 h station accumulation against the four 6 h accumulations that make up the same window.

    Adds ``n6`` (how many of the 6 h values ending at T-18, T-12, T-6, T exist), ``sum6`` and ``flag``:
    ``implausible`` (> ``MAX_P24_MM``), ``inconsistent`` (all four 6 h values exist and differ from the 24 h value by
    more than max(5 mm, 50 %)), ``corroborated`` (all four exist and agree), ``unchecked`` (fewer than four 6 h values).
    """
    lookup = p6.set_index("time")["depth_mm"]
    out = p24.copy()
    n6, sum6 = [], []
    for t in out["time"]:
        vals = [lookup.get(t - pd.Timedelta(hours=h)) for h in (18, 12, 6, 0)]
        vals = [v for v in vals if v is not None and not np.isnan(v)]
        n6.append(len(vals))
        sum6.append(float(sum(vals)))
    out["n6"], out["sum6"] = n6, sum6
    flag = np.where(
        out["depth_mm"] > MAX_P24_MM,
        "implausible",
        np.where(
            out["n6"] < 4,
            "unchecked",
            np.where(
                (out["depth_mm"] - out["sum6"]).abs()
                > np.maximum(CORROB_ABS_MM, CORROB_REL * out["depth_mm"]),
                "inconsistent",
                "corroborated",
            ),
        ),
    )
    out["flag"] = flag
    return out


# ------------------------------------------------------------------------------------------- correction


@dataclass(frozen=True)
class QM:
    """Empirical quantile map IMERG -> station on wet totals. ``src``/``dst`` are matched quantiles (increasing)."""

    src: np.ndarray
    dst: np.ndarray
    ratio_low: float  # dst/src at the lowest fitted quantile, used below the range
    ratio_high: float  # dst/src at the highest fitted quantile, used above the range


def fit_qm(
    imerg: np.ndarray,
    station: np.ndarray,
    n_quantiles: int = 50,
    lower_prob: float = 0.01,
    upper_prob: float = 0.99,
) -> QM:
    """Fit on wet totals (the caller passes only values at or above the wet threshold; the two samples may differ in size).

    Quantiles are taken at ``n_quantiles`` probabilities between ``lower_prob`` and ``upper_prob`` (the extreme tail is
    left to the constant-ratio extrapolation, not to a handful of points).
    """
    imerg = np.asarray(imerg, dtype="float64")
    station = np.asarray(station, dtype="float64")
    imerg, station = imerg[np.isfinite(imerg)], station[np.isfinite(station)]
    if len(imerg) < 2 or len(station) < 2:
        raise ValueError("need at least 2 wet values in each sample")
    probs = np.linspace(lower_prob, upper_prob, n_quantiles)
    src = np.quantile(imerg, probs)
    dst = np.quantile(station, probs)
    # np.interp needs strictly increasing x: collapse ties (average of dst)
    uniq, inv = np.unique(src, return_inverse=True)
    dst_u = np.bincount(inv, weights=dst) / np.bincount(inv)
    if np.any(uniq <= 0):
        raise ValueError("wet IMERG quantiles must be positive")
    return QM(uniq, dst_u, float(dst_u[0] / uniq[0]), float(dst_u[-1] / uniq[-1]))


def apply_qm(qm: QM, values: np.ndarray) -> np.ndarray:
    """Map values through the quantile map; constant ratio outside the fitted range; 0 stays 0."""
    v = np.asarray(values, dtype="float64")
    out = np.interp(v, qm.src, qm.dst)
    out = np.where(v < qm.src[0], v * qm.ratio_low, out)
    out = np.where(v > qm.src[-1], v * qm.ratio_high, out)
    return out


def fit_factor(imerg: np.ndarray, station: np.ndarray) -> float:
    """Baseline: a single multiplicative factor = sum(station)/sum(imerg) (inverse of the total-ratio bias)."""
    s = float(np.sum(imerg))
    if s <= 0:
        raise ValueError("IMERG sum must be positive")
    return float(np.sum(station)) / s


def apply_factor(factor: float, values: np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype="float64") * factor


def leave_one_year_out(pairs: pd.DataFrame, wet: float = WET_MM) -> pd.DataFrame:
    """Out-of-fold corrections: for each year, fit on the other years and correct that year's IMERG totals.

    QM is fitted on the marginal wet totals of the training years (IMERG >= wet, station >= wet, unpaired); the factor
    on the both-wet training pairs. ``qm_both`` is a sensitivity: the same map fitted on the both-wet training pairs.
    Adds ``qm``, ``qm_both`` and ``factor`` columns (NaN for years where fitting is impossible).
    """
    out = pairs.copy()
    out["qm"] = np.nan
    out["qm_both"] = np.nan
    out["factor"] = np.nan
    for year in sorted(out["year"].unique()):
        train = out.loc[out["year"] != year]
        test_idx = out.index[out["year"] == year]
        both = train.loc[(train["station"] >= wet) & (train["imerg"] >= wet)]
        iw = train.loc[train["imerg"] >= wet, "imerg"].to_numpy()
        sw = train.loc[train["station"] >= wet, "station"].to_numpy()
        if len(both) < 2 or len(iw) < 2 or len(sw) < 2:
            continue
        qm = fit_qm(iw, sw)
        qm_both = fit_qm(both["imerg"].to_numpy(), both["station"].to_numpy())
        f = fit_factor(both["imerg"].to_numpy(), both["station"].to_numpy())
        vals = out.loc[test_idx, "imerg"].to_numpy()
        out.loc[test_idx, "qm"] = np.where(vals >= wet, apply_qm(qm, vals), vals)
        out.loc[test_idx, "qm_both"] = np.where(vals >= wet, apply_qm(qm_both, vals), vals)
        out.loc[test_idx, "factor"] = apply_factor(f, vals)
    return out


def cv_scores(oof: pd.DataFrame, subset: pd.Series) -> dict[str, dict[str, float]]:
    """MAE and bias (mean of corrected - station, mm) per method on a boolean subset of ``oof``."""
    sub = oof.loc[subset].dropna(subset=["qm", "qm_both", "factor"])
    res = {}
    for name, col in (("raw", "imerg"), ("factor", "factor"), ("qm", "qm"), ("qm_both", "qm_both")):
        err = sub[col] - sub["station"]
        res[name] = {"n": len(sub), "mae": float(err.abs().mean()), "bias": float(err.mean())}
    return res


# ------------------------------------------------------------------------------------------------- report


def _fmt(v: float, nd: int = 2) -> str:
    return "n/d" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}"


def _metrics_table(pairs: pd.DataFrame) -> list[str]:
    rows = [
        "| celda | n | años | estación húm. | IMERG húm. | POD | FAR | n ambos húm. | sesgo (ratio) | IC90 | mediana | Spearman |"
    ]
    rows.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|")
    for name, col in (("más cercana", "imerg"), ("media 3x3", "imerg9")):
        m = pair_metrics(pairs, col)
        rows.append(
            f"| {name} | {m['n']} | {m['years']} | {m['n_station_wet']} | {m['n_imerg_wet']} | {_fmt(m['pod'])} | "
            f"{_fmt(m['far'])} | {m['n_both_wet']} | {_fmt(m['ratio'])} | {_fmt(m['ratio_lo'])}–{_fmt(m['ratio_hi'])} | "
            f"{_fmt(m['median_ratio'])} | {_fmt(m['spearman_both_wet'])} (todos: {_fmt(m['spearman_all'])}) |"
        )
    return rows


def _cv_table(oof: pd.DataFrame, top: pd.DataFrame) -> list[str]:
    both = (oof["station"] >= WET_MM) & (oof["imerg"] >= WET_MM)
    rows = [
        "| subconjunto | método | n | MAE (mm) | sesgo medio (mm) |",
        "|---|---|---:|---:|---:|",
    ]
    for label, mask in (
        ("ambos húmedos", both),
        ("top-20 estación", pd.Series(oof.index.isin(top.index), index=oof.index)),
    ):
        for name, r in cv_scores(oof, mask).items():
            rows.append(f"| {label} | {name} | {r['n']} | {_fmt(r['mae'])} | {_fmt(r['bias'])} |")
    return rows


def run(
    zarr_path: Path = Path("data/raw/imerg/neuquen.zarr"),
    isd_dir: Path = Path("data/raw/isd"),
    years: range = range(2000, 2026),
) -> str:
    """Compute every number of reports/03/F3.4.md and return it as Markdown (downloads missing ISD years)."""
    from clima_nqn.io import isd

    paths = isd.download_years(years, isd_dir)
    groups = isd.load_all_groups(paths)
    near, mean9, cell = load_imerg_point(zarr_path)
    out = [f"IMERG cell: lat {cell[0]:.2f}, lon {cell[1]:.2f}; AA groups parsed: {len(groups)}"]
    out.append(
        f"all AA groups, period 6/24 by (period, condition, quality):\n{groups[groups['period_h'].isin([6, 24])].groupby(['period_h', 'condition', 'quality']).size().to_string()}"
    )
    kept = isd.admissible(groups)
    out.append(
        f"kept groups by (period, condition): {kept.groupby(['period_h', 'condition']).size().to_dict()}"
    )
    dedup, disagree = isd.dedupe_windows(kept)
    out.append(
        f"windows after dedupe: {len(dedup)}; duplicate windows with differing depths: {disagree}"
    )
    n_dup = len(kept) - len(dedup)
    out.append(f"duplicate groups dropped: {n_dup}")

    p6_all = dedup[dedup["period_h"] == 6]
    p24_flagged = corroborate_p24(dedup[dedup["period_h"] == 24], p6_all)
    out.append(f"p24 flags: {p24_flagged['flag'].value_counts().to_dict()}")
    out.append(
        "p24 flags by condition:\n" + p24_flagged.groupby(["condition", "flag"]).size().to_string()
    )
    out.append(
        "p24 hour of day (UTC): "
        + str(p24_flagged["time"].dt.hour.value_counts().sort_index().to_dict())
    )

    screened24 = p24_flagged[p24_flagged["flag"].isin(["corroborated", "unchecked"])].drop(
        columns=["n6", "sum6", "flag"]
    )
    variants = {
        "A (principal): p24 filtrado (sin implausible/inconsistente), p6 sin filtrar": pd.concat(
            [screened24, p6_all]
        ),
        "B: como A sin condición 3": pd.concat([screened24, p6_all]).query("condition != '3'"),
        "C: sin filtrar": dedup,
    }
    for label, sel in variants.items():
        out.append(f"\n## Variante {label}")
        for period in (24, 6):
            pairs = build_pairs(sel, near, mean9, period)
            out.append(
                f"\n### p{period}: ventanas de estación {int((sel['period_h'] == period).sum())}, con ventana IMERG completa {len(pairs)}"
            )
            out += _metrics_table(pairs)
            top = top_events(pairs, 20)
            ge20 = top_events(pairs, min_mm=20.0)
            out.append(
                f"\n>=20 mm: n={len(ge20)}, suma IMERG/suma estación = {_fmt(total_ratio(ge20['imerg'].to_numpy(), ge20['station'].to_numpy()))}; "
                f"top-20: suma IMERG/suma estación = {_fmt(total_ratio(top['imerg'].to_numpy(), top['station'].to_numpy()))}, "
                f"mediana ratio {_fmt(float(top['ratio'].median()))}"
            )
            cols = ["time", "station", "imerg", "imerg9", "ratio", "condition", "report_type"]
            if period == 24:
                top = top.merge(p24_flagged[["time", "n6", "sum6", "flag"]], on="time", how="left")
                cols += ["n6", "sum6", "flag"]
            out.append("top-20:\n" + top[cols].to_string(index=False))
            oof = leave_one_year_out(pairs)
            out += _cv_table(oof, top if period == 6 else top_events(pairs, 20))
            if period == 24:
                cor = top_events(pairs, min_mm=20.0).merge(
                    p24_flagged[["time", "flag"]], on="time", how="left"
                )
                cor = cor[cor["flag"] == "corroborated"]
                out.append(
                    f">=20 mm y corroborado con p6: n={len(cor)}, suma IMERG/suma estación = "
                    f"{_fmt(total_ratio(cor['imerg'].to_numpy(), cor['station'].to_numpy()))}; ratios: "
                    f"{[round(float(r), 2) for r in cor['ratio']]}"
                )
                rows = pairs.loc[pairs["time"] == pd.Timestamp("2014-04-07 12:00")]
                out.append(
                    "2014-04-07 12Z p24:\n"
                    + rows[["time", "station", "imerg", "imerg9"]].to_string(index=False)
                )
    return "\n".join(out)


if __name__ == "__main__":
    print(run())

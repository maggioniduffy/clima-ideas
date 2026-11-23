"""Conditional climatology of high flow by AR-event characteristics (plan/06, F6.9).

Question: given an atmospheric-river (AR) event with its maximum IVT, maximum 0 degC level and season, how
often does the daily flow of a station exceed a high-flow threshold in the days after the event, and does
this frequency beat the climatology and persistence in a leave-one-event-out test?

Method, fixed before looking at results:

1. Responses. For every event x station the V8 rule of ``stages.ar.response.station_response`` is used
   unchanged (peak window = first day .. last day + 10 days, ``q_before`` = flow the day before the first
   day; ``end`` of the catalog is exclusive). This reproduces the ``q_before`` / ``q_peak`` of
   ``responses.json`` of the ``ar-events`` layer for the stations given; it was not compared file by file
   (sin verificar) because the function is the same one.
2. Target. ``exceed = q_peak > threshold``. Main threshold per station: the provisional p95 of daily flow
   used by ``forecast.baselines`` (``p_caudal_alto``, ``THRESHOLD_QUANTILE``), recomputed in every fold
   WITHOUT the held-out window +- ``GAP_DAYS`` days. Sensitivity: median of the annual maxima (a proxy of
   the 2-year return level, ``extremes.annual_maxima`` F2.2 rule), also per fold.
3. Model. Exceedance frequency per cell of: terciles of ``ivt_max`` x terciles of ``deg0l_max`` x season
   (May-Sep vs Oct-Apr), per station. A month-only version (12 cells), an IVT-only version and a pooled-station
   version are sensitivities. Bin edges come from the training events only. Each cell frequency is shrunk
   toward the station's training exceedance frequency with a Beta prior of ``K_PRIOR = 2`` pseudo-events
   (fixed now, not tuned): ``p = (n_exceed + K * p0) / (n + K)``. A cell without training events gets ``p0``.
4. Validation. Leave-one-event-group-out. Events whose response windows overlap, or whose starts are within
   ``GAP_DAYS`` days of each other, form one group; one group is held out at a time and every event whose
   response window overlaps the held-out window +- ``GAP_DAYS`` days is dropped from training.
   ``folds(events_df)`` exposes the partition. Thresholds, bin edges and frequencies come only from training
   rows and from flow days outside the held-out window +- ``GAP_DAYS``.
5. Baselines. (a) climatology: training exceedance frequency of the station and the same season; (b)
   persistence: training frequency of exceedance given ``q_before > threshold`` (two bins), and the raw 0/1
   persistence as a second row. Persistence is not operational: SNIH has no real-time flow (236-day lag, F6.1).
   Rows with missing ``q_before`` use the station's training frequency in both persistence rows.
6. Scores. Brier score and BSS vs climatology and vs persistence, per station and pooled, with a 95 %
   bootstrap CI that resamples event groups (``N_BOOT`` = 1000 resamples, fixed seed). Reliability table.
   "insuficiente" when the test rows hold fewer than ``MIN_EXCEEDANCES`` = 10 exceedances.
7. Forecast inputs. For the events covered by the F5.10 cases, ``ivt_max`` is replaced by the maximum, over
   the event days of the F5.1 case(s), of the GEFS c00 IVT maximum over the grid cells inside the polygon of
   the catalog (``catalog.CORDILLERA_POLYGON``, same region as the catalog's ``ivt_max``), at each lead
   1..10; the model is still fit on ERA5 training events. ``deg0l_max`` stays ERA5 ("isoterma ERA5, no
   pronosticada"). GEFS IVT is a daily mean of four 6-hourly samples and ERA5 ``ivt_max`` an hourly maximum,
   so the scales differ; no correction is applied.
8. F6.7 interface: ``fit(train_df, threshold, ...) -> Model`` and ``predict_proba(model, df)`` on rows with
   ``ivt_max``, ``deg0l_max``, ``month``, ``station_id``.

Not an official alert; retrospective and not operational.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.forecast import baselines
from clima_nqn.io import forcing  # noqa: F401  (import order: breaks the io.snow <-> io.forcing cycle)
from clima_nqn.stages.ar import catalog as ar_catalog
from clima_nqn.stages.ar import response
from clima_nqn.stages.flood import causes, extremes

K_PRIOR = 2.0
GAP_DAYS = 10
N_BOOT = 1000
SEED = 20261123
MIN_EXCEEDANCES = 10
WET_MONTHS = (5, 6, 7, 8, 9)
LEADS = tuple(range(1, 11))
STATIONS = ("12004", "12010", "12012")
REL_EDGES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0)
THRESHOLD_KINDS = ("p95", "annmax_median")
VARIANTS: dict[str, dict] = {
    "main": {"features": ("ivt", "deg0l", "season"), "pooled": False},
    "month_only": {"features": ("month",), "pooled": False},
    "ivt_only": {"features": ("ivt",), "pooled": False},
    "pooled": {"features": ("ivt", "deg0l", "season"), "pooled": True},
}
REFS = ("clim", "pers", "pers_raw")
REPORT_DIR = Path(__file__).resolve().parents[5] / "reports" / "06"
Threshold = float | Mapping[str, float]


# --- groups and folds ----------------------------------------------------------------------


def _windows(events: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    first, last = causes._event_days(events)
    return first, last + pd.Timedelta(days=response.RESPONSE_DAYS_AFTER)


def event_groups(events: pd.DataFrame) -> np.ndarray:
    """Group id per event row: chained overlap of response windows or starts within ``GAP_DAYS`` days."""
    first, wend = _windows(events)
    order = np.argsort(first.to_numpy(), kind="stable")
    out = np.zeros(len(events), dtype=int)
    gid, cur_end, prev_first = -1, None, None
    gap = pd.Timedelta(days=GAP_DAYS)
    for i in order:
        f, e = first.iloc[i], wend.iloc[i]
        if cur_end is None or (f > cur_end and f - prev_first > gap):
            gid += 1
            cur_end = e
        else:
            cur_end = max(cur_end, e)
        prev_first = f
        out[i] = gid
    return out


def fold_window(events: pd.DataFrame, test_idx: np.ndarray) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Held-out response window of the test events, extended by ``GAP_DAYS`` on both sides."""
    first, wend = _windows(events)
    gap = pd.Timedelta(days=GAP_DAYS)
    return first.iloc[test_idx].min() - gap, wend.iloc[test_idx].max() + gap


def folds(events_df: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    """Leave-one-event-group-out ``(train_idx, test_idx)`` positions in ``events_df`` (needs start, end).

    No training event has a response window overlapping the test window +- ``GAP_DAYS`` days.
    """
    events_df = events_df.reset_index(drop=True)
    first, wend = _windows(events_df)
    groups = event_groups(events_df)
    out = []
    for g in np.unique(groups):
        test = np.flatnonzero(groups == g)
        lo, hi = fold_window(events_df, test)
        overlap = ((first <= hi) & (wend >= lo)).to_numpy()
        train = np.flatnonzero(~overlap & (groups != g))
        out.append((train, test))
    return out


# --- response table ------------------------------------------------------------------------


def season_of(month) -> np.ndarray:
    """1 for May-Sep (wet season), 0 for Oct-Apr."""
    return np.isin(np.asarray(month), WET_MONTHS).astype(int)


def build_table(events: pd.DataFrame, series: Mapping[str, pd.Series]) -> pd.DataFrame:
    """One row per event x station with the V8 response (``station_response``) and the predictors."""
    events = events.reset_index(drop=True)
    firsts, lasts = causes._event_days(events)
    groups = event_groups(events)
    rows = []
    for i, ev in events.iterrows():
        for st, s in series.items():
            res = response.station_response(s, firsts.iloc[i], lasts.iloc[i])
            if res is None:
                continue
            rows.append(
                {
                    "event_idx": int(i),
                    "event_id": ev["event_id"],
                    "station_id": st,
                    "group": int(groups[i]),
                    "first": firsts.iloc[i],
                    "last": lasts.iloc[i],
                    "month": int(ev["start"].month),
                    "ivt_max": float(ev["ivt_max"]),
                    "deg0l_max": float(ev["deg0l_max"]),
                    "q_before": np.nan if res["q_before"] is None else res["q_before"],
                    "q_peak": res["q_peak"],
                }
            )
    return pd.DataFrame(rows)


# --- thresholds ----------------------------------------------------------------------------


def station_threshold(
    series: pd.Series, lo: pd.Timestamp, hi: pd.Timestamp, kind: str = "p95"
) -> float:
    """Threshold from the flow outside ``[lo, hi]`` (the held-out window +- gap)."""
    keep = series[(series.index < lo) | (series.index > hi)].dropna()
    if kind == "p95":
        return float(np.quantile(keep.to_numpy(), baselines.THRESHOLD_QUANTILE))
    if kind == "annmax_median":
        full = pd.DataFrame({"date": series.index, "q_m3s": series.to_numpy(dtype=float)})
        full.loc[(full["date"] >= lo) & (full["date"] <= hi), "q_m3s"] = np.nan
        maxima, _ = extremes.annual_maxima(full)
        return float(maxima["q_m3s"].median())
    raise ValueError(f"unknown threshold kind {kind!r}")


def fold_thresholds(
    series: Mapping[str, pd.Series], lo: pd.Timestamp, hi: pd.Timestamp, kind: str = "p95"
) -> dict[str, float]:
    return {st: station_threshold(s, lo, hi, kind) for st, s in series.items()}


def _thr_of(df: pd.DataFrame, threshold: Threshold) -> np.ndarray:
    if isinstance(threshold, Mapping):
        return df["station_id"].astype(str).map(threshold).to_numpy(dtype=float)
    return np.full(len(df), float(threshold))


def exceedance(df: pd.DataFrame, threshold: Threshold) -> np.ndarray:
    return (df["q_peak"].to_numpy(dtype=float) > _thr_of(df, threshold)).astype(float)


# --- model ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Model:
    features: tuple[str, ...]
    pooled: bool
    k: float
    edges: dict[str, tuple[float, float]]
    p0: dict[str, float]  # per station ("*" = all rows)
    cells: dict[tuple, tuple[float, int]] = field(repr=False)  # (station, cell) -> (exceed, n)
    n_train: int = 0


def _bins(x: np.ndarray, edges: tuple[float, float]) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = (x > edges[0]).astype(int) + (x > edges[1]).astype(int)
    return np.where(np.isnan(x), -1, out)


def _cell_keys(df: pd.DataFrame, features: Sequence[str], edges: Mapping) -> list[tuple]:
    cols = []
    for f in features:
        if f == "ivt":
            cols.append(_bins(df["ivt_max"].to_numpy(), edges["ivt"]))
        elif f == "deg0l":
            cols.append(_bins(df["deg0l_max"].to_numpy(), edges["deg0l"]))
        elif f == "season":
            cols.append(season_of(df["month"].to_numpy()))
        elif f == "month":
            cols.append(df["month"].to_numpy(dtype=int))
        else:
            raise ValueError(f"unknown feature {f!r}")
    return list(zip(*cols, strict=True)) if cols else [()] * len(df)


def fit(
    train_df: pd.DataFrame,
    threshold: Threshold,
    features: Sequence[str] = ("ivt", "deg0l", "season"),
    pooled: bool = False,
    k: float = K_PRIOR,
) -> Model:
    """Shrunk exceedance frequency per cell; edges, frequencies and ``p0`` from ``train_df`` only."""
    ev = train_df.drop_duplicates("event_id")
    edges = {
        "ivt": tuple(np.nanquantile(ev["ivt_max"].to_numpy(dtype=float), [1 / 3, 2 / 3])),
        "deg0l": tuple(np.nanquantile(ev["deg0l_max"].to_numpy(dtype=float), [1 / 3, 2 / 3])),
    }
    y = exceedance(train_df, threshold)
    stations = (
        np.full(len(train_df), "*") if pooled else train_df["station_id"].astype(str).to_numpy()
    )
    keys = _cell_keys(train_df, features, edges)
    cells: dict[tuple, list[float]] = {}
    for st, key, yy in zip(stations, keys, y, strict=True):
        c = cells.setdefault((st, key), [0.0, 0])
        c[0] += yy
        c[1] += 1
    p0 = {"*": float(y.mean()) if len(y) else 0.0}
    for st in np.unique(train_df["station_id"].astype(str)):
        m = train_df["station_id"].astype(str).to_numpy() == st
        p0[st] = float(y[m].mean())
    if pooled:
        p0 = {**p0, **dict.fromkeys(p0, p0["*"])}
    return Model(
        tuple(features),
        pooled,
        float(k),
        {a: (float(b[0]), float(b[1])) for a, b in edges.items()},
        p0,
        {a: (b[0], int(b[1])) for a, b in cells.items()},
        len(train_df),
    )


def predict_proba(model: Model, df: pd.DataFrame) -> np.ndarray:
    """``(n_exceed + k p0) / (n + k)`` per row; unseen cells and stations fall back to ``p0``."""
    stations = df["station_id"].astype(str).to_numpy()
    keys = _cell_keys(df, model.features, model.edges)
    out = np.empty(len(df))
    for i, (st, key) in enumerate(zip(stations, keys, strict=True)):
        p0 = model.p0.get(st, model.p0["*"])
        n_exc, n = model.cells.get(("*" if model.pooled else st, key), (0.0, 0))
        out[i] = (n_exc + model.k * p0) / (n + model.k)
    return out


def baseline_probs(
    train_df: pd.DataFrame, test_df: pd.DataFrame, threshold: Threshold
) -> dict[str, np.ndarray]:
    """Climatology (station x season) and persistence (two-bin and raw 0/1) from training rows."""
    y = exceedance(train_df, threshold)
    tr_st = train_df["station_id"].astype(str).to_numpy()
    tr_season = season_of(train_df["month"].to_numpy())
    tr_high = train_df["q_before"].to_numpy(dtype=float) > _thr_of(train_df, threshold)
    tr_known = ~np.isnan(train_df["q_before"].to_numpy(dtype=float))
    overall = float(y.mean()) if len(y) else 0.0
    te_st = test_df["station_id"].astype(str).to_numpy()
    te_season = season_of(test_df["month"].to_numpy())
    qb = test_df["q_before"].to_numpy(dtype=float)
    te_high = qb > _thr_of(test_df, threshold)
    te_known = ~np.isnan(qb)
    clim, pers, raw = np.empty(len(test_df)), np.empty(len(test_df)), np.empty(len(test_df))
    for i in range(len(test_df)):
        s = tr_st == te_st[i]
        st_freq = float(y[s].mean()) if s.any() else overall
        m = s & (tr_season == te_season[i])
        clim[i] = float(y[m].mean()) if m.any() else st_freq
        if te_known[i]:
            m = s & tr_known & (tr_high == te_high[i])
            pers[i] = float(y[m].mean()) if m.any() else st_freq
            raw[i] = 1.0 if te_high[i] else 0.0
        else:
            pers[i] = raw[i] = st_freq
    return {"clim": clim, "pers": pers, "pers_raw": raw}


# --- scores --------------------------------------------------------------------------------


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(y, float) - np.asarray(p, float)) ** 2))


def bootstrap_bss(
    y: np.ndarray,
    p_model: np.ndarray,
    p_ref: np.ndarray,
    groups: np.ndarray,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> tuple[float, float, float, np.ndarray]:
    """BSS = 1 - BS_model / BS_ref with a cluster bootstrap over ``groups``: ``(bss, lo, hi, boot)``."""
    y, p_model, p_ref = (np.asarray(a, dtype=float) for a in (y, p_model, p_ref))
    _, inv = np.unique(np.asarray(groups), return_inverse=True)
    n_groups = int(inv.max()) + 1
    sm = np.bincount(inv, (y - p_model) ** 2, n_groups)
    sr = np.bincount(inv, (y - p_ref) ** 2, n_groups)
    point = 1.0 - sm.sum() / sr.sum() if sr.sum() > 0 else math.nan
    idx = np.random.default_rng(seed).integers(0, n_groups, size=(n_boot, n_groups))
    bm, br = sm[idx].sum(axis=1), sr[idx].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        boot = np.where(br > 0, 1.0 - bm / br, np.nan)
    if np.isnan(boot).all():
        return point, math.nan, math.nan, boot
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    return point, float(lo), float(hi), boot


def score_entity(
    pred: pd.DataFrame, p_col: str, ref_col: str, n_boot: int = N_BOOT, seed: int = SEED
) -> dict:
    y = pred["exceed"].to_numpy(dtype=float)
    n_exc = int(y.sum())
    bss, lo, hi, _ = bootstrap_bss(
        y, pred[p_col].to_numpy(), pred[ref_col].to_numpy(), pred["group"].to_numpy(), n_boot, seed
    )
    return {
        "n": len(pred),
        "n_exceed": n_exc,
        "n_groups": int(pred["group"].nunique()),
        "n_groups_exceed": int(pred.loc[pred["exceed"] > 0, "group"].nunique()),
        "brier_model": brier(y, pred[p_col]),
        "brier_ref": brier(y, pred[ref_col]),
        "bss": bss,
        "ci_lo": lo,
        "ci_hi": hi,
        "ci_excludes_0": bool(lo > 0 or hi < 0) if not math.isnan(lo) else None,
        "status": "insuficiente" if n_exc < MIN_EXCEEDANCES else "ok",
    }


def score_table(
    pred: pd.DataFrame,
    p_col: str,
    refs: Sequence[str] = REFS,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict[str, dict[str, dict]]:
    """``{ref: {station or 'pooled': score}}`` for one model column of ``pred``."""
    out: dict[str, dict[str, dict]] = {}
    for ref in refs:
        out[ref] = {"pooled": score_entity(pred, p_col, f"p_{ref}", n_boot, seed)}
        for st in STATIONS:
            sub = pred[pred["station_id"] == st]
            if len(sub):
                out[ref][st] = score_entity(sub, p_col, f"p_{ref}", n_boot, seed)
    return out


def reliability(y: np.ndarray, p: np.ndarray, edges: Sequence[float] = REL_EDGES) -> list[dict]:
    y, p = np.asarray(y, float), np.asarray(p, float)
    b = np.clip(np.digitize(p, edges[1:-1]), 0, len(edges) - 2)
    rows = []
    for i in range(len(edges) - 1):
        m = b == i
        rows.append(
            {
                "bin": f"{edges[i]:.2f}-{edges[i + 1]:.2f}",
                "n": int(m.sum()),
                "mean_p": float(p[m].mean()) if m.any() else None,
                "obs_freq": float(y[m].mean()) if m.any() else None,
            }
        )
    return rows


# --- GEFS inputs ---------------------------------------------------------------------------


def gefs_event_ivt(zarr_path: Path | str, cases_path: Path | str) -> pd.DataFrame:
    """Per event and lead: max over the event's case days of the polygon-region max of GEFS c00 IVT.

    Columns ``event_id`` and ``L1``..``L10`` (NaN where the entry is missing or errored).
    """
    import xarray as xr

    ds = xr.open_zarr(zarr_path, consolidated=False)
    mask = ar_catalog.polygon_mask(ds["lat"].values, ds["lon"].values)
    if not bool(mask.any()):
        raise ValueError("catalog polygon covers no GEFS cell")
    ivt = ds["ivt"].isel(member=0).where(ds["status"].isel(member=0) == 0)
    region = ivt.where(mask).max(("lat", "lon")).transpose("case", "lead").load()
    cases = pd.read_parquet(cases_path)
    kind = dict(zip(cases["case_id"], cases["kind"], strict=True))
    case_ids = [str(c) for c in ds["case"].values]
    ev_ids = [str(c) for c in ds["event_id"].values]
    df = pd.DataFrame(region.values, columns=[f"L{int(lead)}" for lead in region["lead"].values])
    df.insert(0, "event_id", ev_ids)
    df = df[[kind.get(c) == "event" for c in case_ids]]
    return df.groupby("event_id", as_index=False).max()


# --- evaluation ----------------------------------------------------------------------------


def evaluate(
    table: pd.DataFrame,
    events: pd.DataFrame,
    series: Mapping[str, pd.Series],
    kind: str = "p95",
    variants: Mapping[str, dict] = VARIANTS,
    gefs: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Out-of-fold predictions of every variant and baseline for each held-out group.

    Columns: row keys, ``exceed``, ``p_<variant>``, ``p_<ref>`` and, with ``gefs``, ``p_gefs_L<k>`` (main
    variant with the GEFS IVT; NaN where there is no GEFS value).
    """
    events = events.reset_index(drop=True)
    parts = []
    for train_idx, test_idx in folds(events):
        lo, hi = fold_window(events, test_idx)
        thr = fold_thresholds(series, lo, hi, kind)
        tr = table[table["event_idx"].isin(train_idx)]
        te = table[table["event_idx"].isin(test_idx)]
        if te.empty or tr.empty:
            continue
        out = te[
            ["event_idx", "event_id", "station_id", "group", "month", "q_before", "q_peak"]
        ].copy()
        out["threshold"] = _thr_of(te, thr)
        out["exceed"] = exceedance(te, thr)
        models = {name: fit(tr, thr, **spec) for name, spec in variants.items()}
        for name, mdl in models.items():
            out[f"p_{name}"] = predict_proba(mdl, te)
        for name, p in baseline_probs(tr, te, thr).items():
            out[f"p_{name}"] = p
        if gefs is not None:
            lookup = gefs.set_index("event_id")
            for lead in LEADS:
                col = f"L{lead}"
                x = (
                    te["event_id"].map(lookup[col])
                    if col in lookup
                    else pd.Series(np.nan, te.index)
                )
                p = predict_proba(models["main"], te.assign(ivt_max=x.to_numpy()))
                out[f"p_gefs_{col}"] = np.where(x.isna(), np.nan, p)
        parts.append(out)
    return pd.concat(parts, ignore_index=True)


def _num(x):
    if isinstance(x, dict):
        return {str(k): _num(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_num(v) for v in x]
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def run(
    events_path: Path | str,
    flow_dir: Path | str,
    ivt_zarr: Path | str | None = None,
    cases_path: Path | str | None = None,
    out_dir: Path | str = REPORT_DIR,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    """Run the whole F6.9 pipeline and write ``F6.9.json`` and ``F6.9.md`` in ``out_dir``."""
    flow_dir, out_dir = Path(flow_dir), Path(out_dir)
    events = pd.read_parquet(events_path).sort_values("start").reset_index(drop=True)
    cat_meta = ar_catalog.read_metadata(events_path)
    meta = json.loads((flow_dir / "stations.json").read_text(encoding="utf-8"))
    names = {str(s["id"]): s["name"] for s in meta["stations"]}
    series, flow_period = {}, {}
    for st in STATIONS:
        df = pd.read_parquet(flow_dir / f"{st}.parquet")
        s = df.set_index(pd.to_datetime(df["date"]).dt.normalize())["q_m3s"].astype(float)
        series[st] = s[~s.index.duplicated()].sort_index()
        v = series[st].dropna()
        flow_period[st] = f"{v.index.min().date()}/{v.index.max().date()}"
    table = build_table(events, series)
    gefs = gefs_event_ivt(ivt_zarr, cases_path) if ivt_zarr and cases_path else None
    groups = event_groups(events)
    sizes = np.bincount(groups)
    result: dict = {
        "task": "F6.9",
        "params": {
            "k_prior": K_PRIOR,
            "gap_days": GAP_DAYS,
            "response_days_after": response.RESPONSE_DAYS_AFTER,
            "n_boot": n_boot,
            "seed": seed,
            "min_exceedances": MIN_EXCEEDANCES,
            "threshold_quantile": baselines.THRESHOLD_QUANTILE,
            "variants": {
                k: {"features": list(v["features"]), "pooled": v["pooled"]}
                for k, v in VARIANTS.items()
            },
        },
        "sources": {
            "events": {
                "source": cat_meta.get("source"),
                "period": cat_meta.get("period"),
                "n_events": len(events),
                "license": cat_meta.get("license"),
            },
            "flow": {
                "source": "SNIH (SIPH) - Red Hidrologica Nacional",
                "stations": {
                    st: {"name": names.get(st), "period": flow_period[st]} for st in STATIONS
                },
            },
        },
        "n_events": len(events),
        "n_rows": len(table),
        "n_rows_by_station": table["station_id"].value_counts().sort_index().to_dict(),
        "n_missing_q_before": int(table["q_before"].isna().sum()),
        "n_missing_predictors": int(table[["ivt_max", "deg0l_max"]].isna().any(axis=1).sum()),
        "groups": {
            "n_groups": len(sizes),
            "max_size": int(sizes.max()),
            "n_singletons": int((sizes == 1).sum()),
        },
        "thresholds_all_data": {
            kind: {
                st: station_threshold(
                    series[st], pd.Timestamp("2100-01-01"), pd.Timestamp("2100-01-02"), kind
                )
                for st in STATIONS
            }
            for kind in THRESHOLD_KINDS
        },
        "results": {},
        "reliability": {},
        "threshold_range_folds": {},
    }
    preds = {}
    for kind in THRESHOLD_KINDS:
        pred = evaluate(table, events, series, kind, gefs=gefs if kind == "p95" else None)
        preds[kind] = pred
        result["results"][kind] = {
            name: score_table(pred, f"p_{name}", n_boot=n_boot, seed=seed) for name in VARIANTS
        }
        result["threshold_range_folds"][kind] = {
            st: [
                float(pred.loc[pred.station_id == st, "threshold"].min()),
                float(pred.loc[pred.station_id == st, "threshold"].max()),
            ]
            for st in STATIONS
        }
        result.setdefault("exceed_rate", {})[kind] = {
            "pooled": float(pred["exceed"].mean()),
            **{st: float(pred.loc[pred.station_id == st, "exceed"].mean()) for st in STATIONS},
        }
    main = preds["p95"]
    result["reliability"] = {
        "pooled": reliability(main["exceed"], main["p_main"]),
        **{
            st: reliability(
                main.loc[main.station_id == st, "exceed"], main.loc[main.station_id == st, "p_main"]
            )
            for st in STATIONS
        },
    }
    if gefs is not None:
        result["gefs"] = _gefs_results(main, events, gefs, ivt_zarr, n_boot, seed)
    result = _num(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "F6.9.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out_dir / "F6.9.md").write_text(render_report(result), encoding="utf-8")
    return result


def _gefs_results(pred, events, gefs, ivt_zarr, n_boot, seed) -> dict:
    import xarray as xr

    attrs = dict(xr.open_zarr(ivt_zarr, consolidated=False).attrs)
    era5 = events.set_index("event_id")["ivt_max"]
    leads = {}
    for lead in LEADS:
        col = f"p_gefs_L{lead}"
        sub = pred[pred[col].notna()]
        if sub.empty:
            continue
        ratio = gefs.set_index("event_id")[f"L{lead}"].dropna()
        rel = (ratio / era5.reindex(ratio.index)).median()
        leads[str(lead)] = {
            "n_events": int(sub["event_idx"].nunique()),
            "gefs_vs_era5_ivt_median_ratio": float(rel),
            "gefs": score_table(sub, col, ("clim", "pers"), n_boot, seed),
            "era5_same_rows": score_table(sub, "p_main", ("clim", "pers"), n_boot, seed),
        }
    return {
        "source": attrs.get("source"),
        "period": attrs.get("period"),
        "license": attrs.get("license"),
        "lead_convention": attrs.get("lead_convention"),
        "leads": leads,
    }


# --- report --------------------------------------------------------------------------------


def _f(x, nd: int = 3) -> str:
    return "n/d" if x is None else f"{x:.{nd}f}"


def _cell(s: dict | None) -> str:
    if not s:
        return "n/d"
    txt = f"{_f(s['bss'], 2)} [{_f(s['ci_lo'], 2)}, {_f(s['ci_hi'], 2)}]"
    return f"{txt} (insuficiente)" if s["status"] == "insuficiente" else txt


def render_report(res: dict) -> str:
    """Spanish Markdown report from the ``F6.9.json`` dictionary."""
    p, src = res["params"], res["sources"]
    ent = ["pooled", *STATIONS]
    names = {st: f"{st} {src['flow']['stations'][st]['name']}" for st in STATIONS}
    names["pooled"] = "Conjunto"
    L: list[str] = []
    a = L.append
    a("# F6.9 Climatología condicional de caudal alto")
    a("")
    a(
        "**No es una alerta oficial.** Ante una diferencia, siga los avisos de SMN, AIC y Defensa Civil. Análisis "
        'retrospectivo, estado "Experimental"; no indica qué hacer. Persistencia no es operativa: el SNIH no '
        "tiene caudal en tiempo real (rezago de 236 días, F6.1)."
    )
    a("")
    a("## Fuentes y períodos")
    a("")
    a(
        f"- Eventos de río atmosférico: {src['events']['source']}; período {src['events']['period']}; "
        f"{src['events']['n_events']} eventos; licencia {src['events']['license']}. IVT máximo y nivel de 0 °C máximo de ERA5."
    )
    for st in STATIONS:
        s = src["flow"]["stations"][st]
        a(
            f"- Caudal diario {st} {s['name']}: {src['flow']['source']}; período con datos {s['period']}."
        )
    if "gefs" in res:
        g = res["gefs"]
        a(
            f"- IVT pronosticado: {g['source']}; válido {g['period']}; miembro c00; {g['license']}. "
            f"Convención: {g['lead_convention']}"
        )
    a("")
    a("## Método")
    a("")
    a(
        f"- Respuestas: regla V8 (`station_response`): ventana del pico desde el primer día hasta {p['response_days_after']} "
        "días después del último; `q_before` es el caudal del día anterior. La ventana de 10 días es un supuesto, "
        "no un rezago verificado. No se comparó archivo por archivo con `responses.json` (sin verificar)."
    )
    a(
        f"- Objetivo: `q_peak` > umbral. Umbral principal: p{int(p['threshold_quantile'] * 100)} provisional del caudal diario "
        "(el de `p_caudal_alto`), recalculado en cada partición sin los días de la ventana retenida ±"
        f"{p['gap_days']} días. Sensibilidad: mediana de los máximos anuales (proxy de retorno de 2 años)."
    )
    a(
        "- Modelo: frecuencia de superar el umbral por terciles de IVT máximo × terciles de isoterma de 0 °C máxima × "
        "temporada (mayo–septiembre vs. octubre–abril), por estación, con bordes de los terciles tomados solo del "
        f"entrenamiento y contracción hacia la frecuencia de entrenamiento de la estación con prior Beta de {p['k_prior']:g} "
        "pseudo-eventos (fijo, sin ajustar). Variantes: solo mes (12 celdas), solo IVT, y estaciones agrupadas."
    )
    g = res["groups"]
    a(
        f"- Validación: dejar afuera un grupo de eventos (ventanas superpuestas o inicios a ≤ {p['gap_days']} días) por vez, "
        f"quitando del entrenamiento todo evento cuya ventana toque la retenida ±{p['gap_days']} días. "
        f"{g['n_groups']} grupos ({g['n_singletons']} de un solo evento; el mayor tiene {g['max_size']} eventos)."
    )
    a(
        "- Referencias: climatología = frecuencia de entrenamiento de la estación y temporada; persistencia = frecuencia "
        "de entrenamiento condicionada a `q_before` > umbral (dos clases), y persistencia cruda 0/1. "
        f"Filas sin `q_before`: {res['n_missing_q_before']} (usan la frecuencia de la estación)."
    )
    a(
        f"- Puntajes: Brier y BSS con IC 95 % bootstrap por grupo de eventos ({p['n_boot']} remuestreos, semilla {p['seed']}). "
        f'"insuficiente" con menos de {p["min_exceedances"]} superaciones.'
    )
    a(
        f"- Tabla: {res['n_events']} eventos, {res['n_rows']} pares evento × estación "
        f"({', '.join(f'{k}: {v}' for k, v in res['n_rows_by_station'].items())}). Estaciones del conjunto: las tres "
        "estaciones naturales de F2.2; las reguladas (p. ej. 11803 Paso Flores) quedan afuera porque reflejan la operación "
        "de las represas."
    )
    a("")
    a("## Umbrales")
    a("")
    a(
        "| Estación | p95 (todos los datos, m³/s) | p95 rango entre particiones | Mediana máx. anuales (todos) | rango entre particiones | Frecuencia de superación p95 | Frecuencia mediana máx. anuales |"
    )
    a("|---|---|---|---|---|---|---|")
    for st in STATIONS:
        t, r = res["thresholds_all_data"], res["threshold_range_folds"]
        e = res["exceed_rate"]
        a(
            f"| {names[st]} | {_f(t['p95'][st], 1)} | {_f(r['p95'][st][0], 1)}–{_f(r['p95'][st][1], 1)} | "
            f"{_f(t['annmax_median'][st], 1)} | {_f(r['annmax_median'][st][0], 1)}–{_f(r['annmax_median'][st][1], 1)} | "
            f"{_f(e['p95'][st], 2)} | {_f(e['annmax_median'][st], 2)} |"
        )
    a("")
    main = res["results"]["p95"]["main"]
    a("## Resultado principal (entradas ERA5, umbral p95, modelo principal)")
    a("")
    a(
        "| Entidad | n | superaciones | grupos | Brier modelo | Brier clim. | Brier pers. | BSS vs. clim. [IC 95 %] | BSS vs. pers. [IC 95 %] | BSS vs. pers. cruda [IC 95 %] |"
    )
    a("|---|---|---|---|---|---|---|---|---|---|")
    for e in ent:
        c, ps, pr = main["clim"].get(e), main["pers"].get(e), main["pers_raw"].get(e)
        if not c:
            continue
        a(
            f"| {names[e]} | {c['n']} | {c['n_exceed']} | {c['n_groups']} | {_f(c['brier_model'])} | {_f(c['brier_ref'])} | "
            f"{_f(ps['brier_ref'])} | {_cell(c)} | {_cell(ps)} | {_cell(pr)} |"
        )
    a("")
    a("## Sensibilidad (BSS [IC 95 %], conjunto y por estación)")
    for ref, label in (("clim", "climatología"), ("pers", "persistencia")):
        a("")
        a(f"BSS vs. {label}:")
        a("")
        a("| Umbral | Variante | " + " | ".join(names[e] for e in ent) + " |")
        a("|---|---|" + "---|" * len(ent))
        for kind in THRESHOLD_KINDS:
            for var in VARIANTS:
                row = res["results"][kind][var][ref]
                a(f"| {kind} | {var} | " + " | ".join(_cell(row.get(e)) for e in ent) + " |")
    a("")
    a("## Confiabilidad (modelo principal, umbral p95, conjunto)")
    a("")
    a("| Bin de probabilidad | n | probabilidad media | frecuencia observada |")
    a("|---|---|---|---|")
    for r in res["reliability"]["pooled"]:
        a(f"| {r['bin']} | {r['n']} | {_f(r['mean_p'])} | {_f(r['obs_freq'])} |")
    if "gefs" in res:
        a("")
        a("## Entradas de pronóstico (IVT GEFS c00 por anticipación)")
        a("")
        a(
            "IVT = máximo de los días de evento de la caja regional del catálogo (celdas dentro del polígono de la "
            "cordillera) del IVT GEFS c00; el modelo se ajusta con eventos ERA5. Isoterma ERA5, no pronosticada. "
            "El IVT GEFS es un promedio diario de cuatro muestras de 6 h y el de ERA5 un máximo horario: las escalas "
            "difieren y no se corrigió. Umbral p95, modelo principal; referencias sobre las mismas filas. "
            "Los eventos cubiertos son los de los casos F5.1 (2000–2019)."
        )
        a("")
        a(
            "| Anticipación (L) | eventos | filas | superaciones | IVT GEFS / IVT ERA5 (mediana) | BSS vs. clim. [IC 95 %] | BSS vs. pers. [IC 95 %] | ERA5 mismas filas, BSS vs. clim. [IC 95 %] |"
        )
        a("|---|---|---|---|---|---|---|---|")
        for lead, r in res["gefs"]["leads"].items():
            c = r["gefs"]["clim"]["pooled"]
            a(
                f"| {lead} | {r['n_events']} | {c['n']} | {c['n_exceed']} | {_f(r['gefs_vs_era5_ivt_median_ratio'], 2)} | "
                f"{_cell(c)} | {_cell(r['gefs']['pers']['pooled'])} | {_cell(r['era5_same_rows']['clim']['pooled'])} |"
            )
        a("")
        a("BSS por estación y anticipación vs. climatología:")
        a("")
        a("| L | " + " | ".join(names[e] for e in STATIONS) + " |")
        a("|---|" + "---|" * len(STATIONS))
        for lead, r in res["gefs"]["leads"].items():
            a(f"| {lead} | " + " | ".join(_cell(r["gefs"]["clim"].get(e)) for e in STATIONS) + " |")
    a("")
    a("## Advertencias")
    a("")
    a(
        "- Retrospectivo: no es una alerta oficial ni una perspectiva operativa; sirve como un modelo simple más para el "
        "criterio 3 de la compuerta de evidencia, que exige además los otros criterios (eventos independientes, prospectiva)."
    )
    a(
        "- El caudal de la ventana coincide con el evento; no prueba que el río atmosférico lo haya causado."
    )
    a(
        "- Los grupos de eventos no son independientes del todo (sistemas vecinos, años ENSO); el IC por grupo no lo corrige."
    )
    a(
        "- Un mismo evento cuenta en las tres estaciones en el conjunto; el bootstrap remuestrea grupos, no filas."
    )
    a(
        "- Umbrales de las estaciones y rango de entrenamiento: caudales fuera del rango entrenado no se evaluaron aquí (sin verificar)."
    )
    a(
        "- Reproducción de `responses.json`: misma función; no se comparó el archivo publicado (sin verificar)."
    )
    a("")
    return "\n".join(L)

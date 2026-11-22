"""F5.3: "risk day" classifier on GEFS reforecasts of every day, with a per-mechanism comparison.

Definitions (fixed before running; see ``plan/05-hindcast.md`` and ``RULE_LINES``):

- regions: cordillera norte / sur (F1 polygon split at -38.5) and Confluencia (F3.6 box), cos(lat)-weighted means;
- label: region-mean ERA5 daily precipitation >= the ``q`` quantile of the TRAIN days (2000-2011);
- mechanism of a risk day: ``ar`` (day touches an F1.3 event) > ``convective`` (cp/tp >= 0.5) > ``other``;
- models per (region, lead): monthly climatology, logistic baseline, LightGBM; split train/valid/test in time.

numpy/pandas/xarray plus scikit-learn (and LightGBM, optional); the ML imports are lazy so the module (and the
region/label/mechanism helpers) import without the ``ml`` dependency group.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.stages.ar import catalog
from clima_nqn.stages.ar.extremes import wilson_interval
from clima_nqn.stages.convection.enso import CONFLUENCIA
from clima_nqn.stages.hindcast import verify as v

REGIONS = ("cordillera_norte", "cordillera_sur", "confluencia")
REGION_LABELS = {
    "cordillera_norte": "Cordillera norte",
    "cordillera_sur": "Cordillera sur",
    "confluencia": "Confluencia",
}
LAT_SPLIT = -38.5
MECHANISMS = ("ar", "convective", "other")
MECH_LABELS = {"ar": "río atmosférico", "convective": "convectivo", "other": "otro"}
MODELS = ("clim", "log", "lgbm")
MODEL_LABELS = {"clim": "climatología", "log": "logística", "lgbm": "LightGBM"}
SEASONS = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}
TRAIN = ("2000-01-01", "2011-12-31")
VALID = ("2012-01-01", "2014-12-31")
TEST = ("2015-01-01", "2019-12-31")
CP_FRAC = 0.5
MIN_EVENTS = 20
SENS_LEADS = (1, 3, 5, 7, 10)
LGBM_GRID = (
    {"num_leaves": 4, "learning_rate": 0.05, "min_child_samples": 20},
    {"num_leaves": 8, "learning_rate": 0.05, "min_child_samples": 20},
    {"num_leaves": 4, "learning_rate": 0.02, "min_child_samples": 40},
    {"num_leaves": 8, "learning_rate": 0.02, "min_child_samples": 40},
)
LGBM_MAX_TREES = 400
LGBM_PATIENCE = 30


# --- regions, labels, mechanisms ---------------------------------------------------------------


def regions(lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    """Boolean (lat, lon) masks by cell center: the two halves of the cordillera polygon and Confluencia."""
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    poly = catalog.polygon_mask(lat, lon).values
    lat2d = np.broadcast_to(lat[:, None], poly.shape)
    lon2d = np.broadcast_to(lon[None, :], poly.shape)
    la, lo = CONFLUENCIA["lat"], CONFLUENCIA["lon"]
    conf = (lat2d >= la[0]) & (lat2d <= la[1]) & (lon2d >= lo[0]) & (lon2d <= lo[1])
    return {
        "cordillera_norte": poly & (lat2d >= LAT_SPLIT),
        "cordillera_sur": poly & (lat2d < LAT_SPLIT),
        "confluencia": conf,
    }


def region_means(da: xr.DataArray, masks: dict[str, np.ndarray]) -> dict[str, xr.DataArray]:
    """cos(lat)-weighted NaN-aware mean over each region's cells (``da`` has lat, lon dims)."""
    out = {}
    for name, m in masks.items():
        mask = xr.DataArray(m, dims=("lat", "lon"), coords={"lat": da["lat"], "lon": da["lon"]})
        out[name] = v.box_mean(da.where(mask))
    return out


def period_mask(dates, period: tuple[str, str]) -> np.ndarray:
    d = pd.to_datetime(np.asarray(dates))
    return np.asarray((d >= pd.Timestamp(period[0])) & (d <= pd.Timestamp(period[1])))


def split_masks(dates) -> dict[str, np.ndarray]:
    return {
        "train": period_mask(dates, TRAIN),
        "valid": period_mask(dates, VALID),
        "test": period_mask(dates, TEST),
    }


def train_threshold(series: pd.Series, q: float) -> float:
    """The ``q`` quantile of the region-mean series over TRAIN days only (no later day can move it)."""
    s = series[period_mask(series.index, TRAIN)].dropna()
    return float(s.quantile(q)) if len(s) else float("nan")


def _naive(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s)
    return s.dt.tz_convert("UTC").dt.tz_localize(None) if s.dt.tz is not None else s


def ar_touch(dates, events: pd.DataFrame, pad_days: int = 0) -> np.ndarray:
    """True for days D whose [D 00:00, D+1 00:00) overlaps an event [start, end), each side widened by pad."""
    days = pd.to_datetime(np.asarray(dates)).normalize()
    out = np.zeros(len(days), dtype=bool)
    if len(events) == 0:
        return out
    pad = pd.Timedelta(days=pad_days)
    start = _naive(events["start"]) - pad
    end = _naive(events["end"]) + pad
    day_ns = days.values.astype("datetime64[ns]")
    order = np.argsort(day_ns, kind="stable")
    sorted_ns = day_ns[order]
    one = np.timedelta64(1, "D")
    touched = np.zeros(len(days), dtype=bool)
    for s, e in zip(start.values.astype("datetime64[ns]"), end.values.astype("datetime64[ns]")):
        first = s.astype("datetime64[D]").astype("datetime64[ns]")  # D+1 > s  <=>  D >= floor(s)
        e_floor = e.astype("datetime64[D]")
        e_ceil = e_floor + one if e_floor.astype("datetime64[ns]") < e else e_floor
        last = (e_ceil - one).astype("datetime64[ns]")  # D < e  <=>  D <= ceil(e) - 1 day
        lo = np.searchsorted(sorted_ns, first, side="left")
        hi = np.searchsorted(sorted_ns, last, side="right")
        if hi > lo:
            touched[lo:hi] = True
    out[order] = touched
    return out


def mechanism(
    dates,
    events: pd.DataFrame,
    tp: np.ndarray,
    cp: np.ndarray,
    cp_frac: float = CP_FRAC,
    ar_pad_days: int = 0,
) -> np.ndarray:
    """Mechanism per day (meaningful on risk days): ar > convective (cp/tp >= cp_frac, tp > 0) > other."""
    is_ar = ar_touch(dates, events, ar_pad_days)
    tp, cp = np.asarray(tp, dtype=float), np.asarray(cp, dtype=float)
    with np.errstate(all="ignore"):
        conv = (tp > 0) & (cp / np.where(tp > 0, tp, 1.0) >= cp_frac)
    out = np.where(is_ar, "ar", np.where(conv, "convective", "other"))
    return out.astype("<U10")


def season_of(dates) -> np.ndarray:
    months = pd.to_datetime(np.asarray(dates)).month.to_numpy()
    lookup = {m: s for s, ms in SEASONS.items() for m in ms}
    return np.array([lookup[int(m)] for m in months])


def preponderance(dates, risk: np.ndarray, mech: np.ndarray) -> dict:
    """Per season and ``all``: risk-day count and share of each mechanism with Wilson 95 % CI."""
    seas = season_of(dates)
    risk, mech = np.asarray(risk, dtype=bool), np.asarray(mech)
    out = {}
    for name in (*SEASONS, "all"):
        sel = risk if name == "all" else risk & (seas == name)
        n = int(sel.sum())
        row: dict = {"n": n}
        for m in MECHANISMS:
            k = int((sel & (mech == m)).sum())
            lo, hi = wilson_interval(k, n)
            row[m] = {"k": k, "share": k / n if n else float("nan"), "lo": lo, "hi": hi}
        out[name] = row
    return out


def event_blocks(dates, risk_any: np.ndarray) -> np.ndarray:
    """Block id per date (input order): runs of consecutive risk days (of ANY region) share one block,
    every non-risk day is its own block."""
    d = pd.to_datetime(np.asarray(dates))
    risk_any = np.asarray(risk_any, dtype=bool)
    order = np.argsort(d.to_numpy(), kind="stable")
    ds, rs = d[order], risk_any[order]
    gap = np.diff(ds.values.astype("datetime64[D]").astype(np.int64), prepend=-10)
    cont = rs & np.concatenate([[False], rs[:-1]]) & (gap == 1)
    ids_sorted = np.cumsum(~cont) - 1
    out = np.empty(len(d), dtype="int64")
    out[order] = ids_sorted
    return out


# --- features and models -----------------------------------------------------------------------


def _stats(m: np.ndarray, thr: float) -> dict[str, np.ndarray]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean, mx, sd = np.nanmean(m, axis=1), np.nanmax(m, axis=1), np.nanstd(m, axis=1)
    nv = (~np.isnan(m)).sum(axis=1)
    frac = np.where(nv > 0, np.nansum(m >= thr, axis=1) / np.maximum(nv, 1), np.nan)
    return {"mean": mean, "max": mx, "std": sd, "frac": frac}


def feature_frame(
    members: dict[str, np.ndarray], region: str, lead_idx: int, thr: dict[str, float], dates
) -> pd.DataFrame:
    """Inputs for (region, lead): ensemble mean/max/std/fraction>=threshold of the own and the two other
    regions, month sin/cos. ``members[r]`` is (case, lead, member); NaN members are ignored per row."""
    cols: dict[str, np.ndarray] = {}
    for r in (region, *[x for x in REGIONS if x != region]):
        prefix = "own" if r == region else r
        for k, val in _stats(members[r][:, lead_idx, :], thr[r]).items():
            cols[f"{prefix}_{k}"] = val
    month = pd.to_datetime(np.asarray(dates)).month.to_numpy()
    cols["month_sin"] = np.sin(2 * np.pi * month / 12)
    cols["month_cos"] = np.cos(2 * np.pi * month / 12)
    return pd.DataFrame(cols, index=pd.to_datetime(np.asarray(dates)))


def climatology_rates(month: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Base rate per calendar month (index 1..12 -> rates[m-1]); empty months fall back to the overall rate."""
    y = np.asarray(y, dtype=float)
    overall = float(y.mean()) if len(y) else 0.0
    return np.array([y[month == m].mean() if (month == m).any() else overall for m in range(1, 13)])


def climatology_predict(rates: np.ndarray, month: np.ndarray) -> np.ndarray:
    return rates[np.asarray(month, dtype=int) - 1]


def _logistic_x(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack(
        [
            np.log1p(np.clip(df["own_mean"].to_numpy(), 0, None)),
            df["own_frac"].to_numpy(),
            df["month_sin"].to_numpy(),
            df["month_cos"].to_numpy(),
        ]
    )


def fit_logistic(x_fit: pd.DataFrame, y_fit: np.ndarray, x_new: pd.DataFrame) -> np.ndarray:
    """Standardized logistic regression (C = 1.0); a single-class fit falls back to its base rate."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if len(np.unique(y_fit)) < 2:
        return np.full(len(x_new), float(np.mean(y_fit)) if len(y_fit) else 0.0)
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
    model.fit(_logistic_x(x_fit), y_fit)
    return model.predict_proba(_logistic_x(x_new))[:, 1]


def lightgbm_available() -> bool:
    try:
        import lightgbm  # noqa: F401
    except ImportError:
        return False
    return True


def fit_lightgbm(
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    x_valid: pd.DataFrame,
    y_valid: np.ndarray,
    x_test: pd.DataFrame,
    seed: int = 0,
) -> tuple[np.ndarray, dict]:
    """Pick (hyperparams, n_trees) by valid Brier with early stopping, refit on train+valid, predict test."""
    import lightgbm as lgb

    def make(params: dict, n: int):
        return lgb.LGBMClassifier(
            n_estimators=n,
            random_state=seed,
            deterministic=True,
            force_row_wise=True,
            n_jobs=1,
            verbose=-1,
            **params,
        )

    if len(np.unique(y_train)) < 2 or len(np.unique(y_valid)) < 2:
        base = float(np.mean(np.concatenate([y_train, y_valid])))
        return np.full(len(x_test), base), {"note": "una sola clase; tasa base"}
    best = None
    for params in LGBM_GRID:
        m = make(params, LGBM_MAX_TREES)
        m.fit(
            x_train,
            y_train,
            eval_X=x_valid,
            eval_y=y_valid,
            callbacks=[lgb.early_stopping(LGBM_PATIENCE, verbose=False)],
        )
        n_best = int(m.best_iteration_ or LGBM_MAX_TREES)
        p = m.predict_proba(x_valid, num_iteration=n_best)[:, 1]
        score = v.brier(p, y_valid)
        if best is None or score < best[0]:
            best = (score, params, n_best)
    assert best is not None
    _, params, n_best = best
    final = make(params, max(n_best, 10))
    final.fit(pd.concat([x_train, x_valid]), np.concatenate([y_train, y_valid]))
    info = {**params, "n_estimators": max(n_best, 10), "valid_brier": best[0]}
    return final.predict_proba(x_test)[:, 1], info


# --- metrics ------------------------------------------------------------------------------------


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    idx = np.minimum((np.asarray(p) * bins).astype(int), bins - 1)
    out = []
    for b in range(bins):
        s = idx == b
        out.append(
            {
                "bin": b,
                "mean_p": float(np.mean(p[s])) if s.any() else float("nan"),
                "obs_freq": float(np.mean(y[s])) if s.any() else float("nan"),
                "n": int(s.sum()),
            }
        )
    return out


def pr_auc(p: np.ndarray, y: np.ndarray) -> float:
    from sklearn.metrics import average_precision_score

    if int(np.sum(y)) == 0:
        return float("nan")
    return float(average_precision_score(y, p))


def _skill(se_m: np.ndarray, se_ref: np.ndarray) -> float:
    d = se_ref.mean() if len(se_ref) else 0.0
    return float(1.0 - se_m.mean() / d) if d > 0 else float("nan")


def bss_with_ci(
    se_m: np.ndarray, se_ref: np.ndarray, ids: np.ndarray | None, n_boot: int, seed: int
) -> tuple[float, float, float]:
    """BSS = 1 - Brier(m)/Brier(ref) from per-day squared errors; CI by resampling event blocks ``ids``."""
    val = _skill(se_m, se_ref)
    if ids is None or len(se_m) == 0:
        return val, float("nan"), float("nan")
    lo, hi = v.bootstrap_ci(lambda i: _skill(se_m[i], se_ref[i]), ids, n_boot, seed)
    return val, lo, hi


def _ci_dict(t: tuple[float, float, float]) -> dict:
    return {"value": t[0], "lo": t[1], "hi": t[2]}


def _score_region_lead(
    probs: dict[str, np.ndarray],
    y: np.ndarray,
    mech: np.ndarray,
    ids: np.ndarray,
    base_fit: float,
    n_boot: int,
    seed: int,
    light: bool,
    mech_variants: dict[str, np.ndarray],
) -> dict:
    """Test-set scores of every model plus the per-mechanism table (see module docs)."""
    se = {m: (p - y) ** 2 for m, p in probs.items()}
    ci_ids = None if light else ids
    out: dict = {"n_days": len(y), "base_rate": float(y.mean()) if len(y) else float("nan")}
    out["n_risk_days"] = int(y.sum())
    out["n_events"] = len(np.unique(ids[y == 1]))
    models: dict = {}
    for m, p in probs.items():
        row: dict = {"brier": float(se[m].mean())}
        if m != "clim":
            row["bss_clim"] = _ci_dict(bss_with_ci(se[m], se["clim"], ci_ids, n_boot, seed))
        if m == "lgbm" and "log" in probs:
            row["bss_log"] = _ci_dict(bss_with_ci(se[m], se["log"], ci_ids, n_boot, seed))
        if not light:
            row["pr_auc"] = pr_auc(p, y)
            row["reliability"] = reliability(p, y)
        models[m] = row
    out["models"] = models
    out["mechanisms"] = {}
    out["mechanism_variants"] = {}
    risk = y == 1
    for mech_name in MECHANISMS:
        sel_risk = risk & (mech == mech_name)
        sub = (~risk) | sel_risk
        n_ev = len(np.unique(ids[sel_risk]))
        entry: dict = {
            "n_risk_days": int(sel_risk.sum()),
            "n_events": n_ev,
            "sin_verificar": n_ev < MIN_EVENTS,
            "models": {},
        }
        if not light:
            for m, p in probs.items():
                row = {
                    "mean_p": float(p[sel_risk].mean()) if sel_risk.any() else float("nan"),
                    "pod_05": float((p[sel_risk] >= 0.5).mean())
                    if sel_risk.any()
                    else float("nan"),
                    "pod_2base": float((p[sel_risk] >= 2 * base_fit).mean())
                    if sel_risk.any()
                    else float("nan"),
                }
                if m != "clim":
                    row["bss_clim"] = _ci_dict(
                        bss_with_ci(se[m][sub], se["clim"][sub], ids[sub], n_boot, seed)
                    )
                entry["models"][m] = row
        out["mechanisms"][mech_name] = entry
    for name, mech_v in mech_variants.items():
        res = {}
        for mech_name in MECHANISMS[:2]:
            sub = (~risk) | (risk & (mech_v == mech_name))
            if "log" in se:
                res[mech_name] = {
                    "bss_log": _skill(se["log"][sub], se["clim"][sub]),
                    "n_events": len(np.unique(ids[risk & (mech_v == mech_name)])),
                }
        out["mechanism_variants"][name] = res
    return out


# --- orchestration ------------------------------------------------------------------------------


def build_context(
    dates,
    leads,
    members: dict[str, np.ndarray],
    tp: pd.DataFrame,
    cp: pd.DataFrame,
    events: pd.DataFrame,
) -> dict:
    """Bundle the inputs. ``members[r]`` (case, lead, member) mm/day; ``tp``/``cp`` daily region means."""
    d = pd.to_datetime(np.asarray(dates)).normalize()
    order = np.argsort(d.to_numpy(), kind="stable")
    return {
        "dates": d[order],
        "leads": [int(x) for x in leads],
        "members": {r: np.asarray(a, dtype="float64")[order] for r, a in members.items()},
        "tp": tp.sort_index(),
        "cp": cp.sort_index(),
        "events": events,
    }


def _evaluate(
    ctx: dict,
    q: float,
    models: tuple[str, ...],
    n_boot: int,
    seed: int,
    light: bool,
    variants: dict[str, dict] | None = None,
) -> dict:
    tp, cp, events = ctx["tp"], ctx["cp"], ctx["events"]
    obs_dates = tp.index
    thr = {r: train_threshold(tp[r], q) for r in REGIONS}
    risk_obs = {r: (tp[r] >= thr[r]).to_numpy() & tp[r].notna().to_numpy() for r in REGIONS}
    mech_main = {
        r: mechanism(obs_dates, events, tp[r].to_numpy(), cp[r].to_numpy()) for r in REGIONS
    }
    mech_var = {
        name: {
            r: mechanism(obs_dates, events, tp[r].to_numpy(), cp[r].to_numpy(), **kw)
            for r in REGIONS
        }
        for name, kw in (variants or {}).items()
    }
    test_obs = period_mask(obs_dates, TEST)
    any_risk = np.any([risk_obs[r] for r in REGIONS], axis=0)
    blocks = pd.Series(
        event_blocks(obs_dates[test_obs], any_risk[test_obs]), index=obs_dates[test_obs]
    )
    n_pooled = len(np.unique(blocks.to_numpy()[any_risk[test_obs]]))
    dates = ctx["dates"]
    sp = split_masks(dates)
    month = dates.month.to_numpy()
    result: dict = {
        "quantile": q,
        "thresholds": thr,
        "n_events_pooled_test": n_pooled,
        "pooled_sin_verificar": n_pooled < MIN_EVENTS,
        "preponderance": {},
        "regions": {},
    }
    for r in REGIONS:
        valid_obs = tp[r].notna().reindex(dates).fillna(False).to_numpy(dtype=bool)
        y_all = (
            pd.Series(risk_obs[r], index=obs_dates).reindex(dates).fillna(False).to_numpy(dtype=int)
        )
        result["preponderance"][r] = preponderance(
            obs_dates[tp[r].notna().to_numpy()],
            risk_obs[r][tp[r].notna().to_numpy()],
            mech_main[r][tp[r].notna().to_numpy()],
        )
        result["regions"][r] = {}
        mech_r = pd.Series(mech_main[r], index=obs_dates).reindex(dates).to_numpy()
        mech_v_r = {
            n: pd.Series(m[r], index=obs_dates).reindex(dates).to_numpy()
            for n, m in mech_var.items()
        }
        for li, lead in enumerate(ctx["leads"]):
            feat = feature_frame(ctx["members"], r, li, thr, dates)
            ok = valid_obs & ~np.isnan(feat["own_mean"].to_numpy())
            tr, va, te = sp["train"] & ok, sp["valid"] & ok, sp["test"] & ok
            if not te.any() or not (tr | va).any():
                continue
            fit = tr | va
            probs: dict[str, np.ndarray] = {}
            rates = climatology_rates(month[fit], y_all[fit])
            probs["clim"] = climatology_predict(rates, month[te])
            info: dict = {}
            if "log" in models:
                probs["log"] = fit_logistic(feat[fit], y_all[fit], feat[te])
            if "lgbm" in models:
                if lightgbm_available():
                    probs["lgbm"], info = fit_lightgbm(
                        feat[tr], y_all[tr], feat[va], y_all[va], feat[te], seed
                    )
                else:
                    info = {"note": "lightgbm no instalado"}
            ids = blocks.reindex(dates[te]).to_numpy()
            if np.isnan(ids.astype(float)).any():  # forecast date outside the observed test days
                keep = ~np.isnan(ids.astype(float))
                probs = {k: p[keep] for k, p in probs.items()}
                te_idx = np.flatnonzero(te)[keep]
            else:
                te_idx = np.flatnonzero(te)
            ids = blocks.reindex(dates[te_idx]).to_numpy().astype(int)
            res = _score_region_lead(
                probs,
                y_all[te_idx].astype(float),
                mech_r[te_idx],
                ids,
                float(y_all[fit].mean()),
                n_boot,
                seed,
                light,
                {n: m[te_idx] for n, m in mech_v_r.items()},
            )
            res["lgbm_info"] = info
            res["base_rate_fit"] = float(y_all[fit].mean())
            result["regions"][r][str(lead)] = res
    return result


def analyze(
    ctx: dict,
    n_boot: int = 1000,
    seed: int = 0,
    quantiles: tuple[float, ...] = (0.95, 0.90, 0.98),
    models: tuple[str, ...] = MODELS,
) -> dict:
    """Main run at ``quantiles[0]`` (all models, CIs, mechanism variants) + light sensitivity runs."""
    variants = {
        "ar_pm1": {"ar_pad_days": 1},
        "cp_0.4": {"cp_frac": 0.4},
        "cp_0.6": {"cp_frac": 0.6},
    }
    main = _evaluate(ctx, quantiles[0], models, n_boot, seed, False, variants)
    sens_q = {}
    for q in quantiles[1:]:
        sens_q[str(q)] = _evaluate(ctx, q, ("log",), n_boot, seed, True)
    main["sensitivity_quantile"] = sens_q
    main["lgbm_available"] = lightgbm_available()
    return main


# --- inputs from disk ---------------------------------------------------------------------------


def load_inputs(fc_path: Path, obs_path: Path, events_path: Path) -> dict:
    fc = xr.open_zarr(fc_path, consolidated=False)
    kinds = v.str_values(fc["kind"])
    if (kinds == "all").any():
        fc = fc.isel(case=np.flatnonzero(kinds == "all"))
    prec = fc["precip_mm"].where(fc["status"] == 0)
    masks = regions(fc["lat"].values, fc["lon"].values)
    means = region_means(prec, masks)
    members = {r: means[r].transpose("case", "lead", "member").values for r in REGIONS}
    dates = pd.to_datetime(fc["valid_date"].values)
    obs = xr.open_zarr(obs_path, consolidated=False)
    if "cp_mm" not in obs:
        raise ValueError("obs store has no cp_mm; run `hindcast observe --variables tp,cp`")
    omasks = regions(obs["lat"].values, obs["lon"].values)
    tp = pd.DataFrame({r: x.to_series() for r, x in region_means(obs["precip_mm"], omasks).items()})
    cp = pd.DataFrame({r: x.to_series() for r, x in region_means(obs["cp_mm"], omasks).items()})
    events = pd.read_parquet(events_path, columns=["event_id", "start", "end"])
    ctx = build_context(dates, [int(x) for x in fc["lead"].values], members, tp, cp, events)
    ctx["fc_attrs"] = {k: str(val) for k, val in dict(fc.attrs).items()}
    return ctx


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(val) for k, val in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(val) for val in x]
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float) and np.isnan(x):
        return None
    return x


def run(
    fc_path: Path,
    obs_path: Path,
    events_path: Path,
    out_dir: Path,
    n_boot: int = 1000,
    seed: int = 0,
    quantiles: tuple[float, ...] = (0.95, 0.90, 0.98),
) -> dict:
    ctx = load_inputs(Path(fc_path), Path(obs_path), Path(events_path))
    results = _clean(analyze(ctx, n_boot, seed, tuple(quantiles)))
    meta = {
        "fc_source": ctx.get("fc_attrs", {}).get("source", "GEFSv12 reforecast"),
        "fc_period": f"{ctx['dates'].min().date()} … {ctx['dates'].max().date()}",
        "n_boot": n_boot,
        "seed": seed,
        "quantiles": list(quantiles),
        "n_cases": len(ctx["dates"]),
        "n_catalog_events": len(ctx["events"]),
    }
    results["meta"] = meta
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "F5.3.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    (out / "F5.3.md").write_text(render_md(results, meta), encoding="utf-8")
    return results


# --- report -------------------------------------------------------------------------------------


def _nan(x) -> float:
    return float("nan") if x is None else float(x)


def _ci3(d: dict | None) -> str:
    if not d:
        return "—"
    return v._ci(_nan(d.get("value")), _nan(d.get("lo")), _nan(d.get("hi")))


def _pct(x, d: int = 0) -> str:
    x = _nan(x)
    return "—" if np.isnan(x) else v._f(100 * x, d) + " %"


RULE_LINES = [
    (
        "- Regiones (centros de celda de la grilla 0,25°): cordillera norte = polígono de la cordillera (F1) con "
        "lat ≥ −38,5; cordillera sur = el mismo polígono con lat < −38,5; Confluencia = caja de F3.6 "
        "(−39,2…−38,7 / −68,4…−67,8). Media regional ponderada por cos(lat), ignorando celdas sin dato."
    ),
    (
        "- Día de riesgo: media regional de ERA5 `tp` del día D ≥ cuantil {q} de los días de entrenamiento "
        "(2000–2011) de esa región. Sensibilidad: cuantiles {sens}."
    ),
    (
        "- Mecanismo de un día de riesgo, en este orden: río atmosférico si el día D (de 00:00 a 24:00 UTC) toca un "
        "evento del catálogo F1.3 `[inicio, fin)`; si no, convectivo si cp/tp de la media regional ≥ 0,5 "
        "(tp = 0 → no convectivo); si no, otro. Sensibilidad: río atmosférico a ±1 día; cp/tp 0,4 y 0,6."
    ),
    "- Preponderancia: por región y estación (DJF, MAM, JJA, SON) y todo el año, días de riesgo 2000–2019; IC de Wilson 95 %.",
    "- Partición temporal: entrenamiento 2000–2011, validación 2012–2014, test 2015–2019 (reajuste en 2000–2014).",
    (
        "- Entradas por (región, día, anticipación L): media, máximo, desvío del ensamble de la lluvia regional y "
        "fracción de miembros ≥ umbral de la región; lo mismo para las otras dos regiones; mes (seno y coseno). Con "
        "miembros faltantes se usan los disponibles; sin miembros se descarta la fila."
    ),
    (
        "- Modelos por región y L: (1) climatología = tasa base mensual; (2) regresión logística (log1p media del "
        "ensamble, fracción de miembros, mes; estandarizada; C = 1,0); (3) LightGBM con todas las entradas (grilla "
        "chica de 4 hiperparámetros y parada temprana elegidos por Brier en validación)."
    ),
    (
        "- Métricas en test: Brier, BSS contra la climatología (y de LightGBM contra la logística), PR-AUC, "
        "confiabilidad en 10 bins. IC 95 % por bootstrap de bloques ({n_boot} remuestreos, semilla {seed}): días de "
        "riesgo consecutivos de cualquier región forman un bloque; cada día sin riesgo es su propio bloque. Sin exactitud."
    ),
    (
        "- Por mecanismo: POD con p ≥ 0,5 y con p ≥ 2 × tasa base de ajuste; probabilidad media pronosticada en los "
        "días de riesgo del mecanismo; BSS sobre (días de riesgo del mecanismo ∪ todos los días sin riesgo) contra "
        "la climatología. Menos de {min_ev} eventos en test → «sin verificar»."
    ),
]


def render_md(results: dict, meta: dict) -> str:
    """Spanish report (see ``RULE_LINES``); ``results`` as returned by ``analyze`` (NaN or None for missing)."""
    q = _nan(results.get("quantile", 0.95))
    sens_q = results.get("sensitivity_quantile", {})
    thr = results.get("thresholds", {})
    n_pool = results.get("n_events_pooled_test")
    L = ["# F5.3 — Clasificador de día de riesgo y comparación por mecanismo (GEFS reforecast)", ""]
    L += ["## Veredicto", "", "<!-- veredicto: lo escribe Opus -->", ""]
    pooled = "sin dato" if n_pool is None else str(n_pool)
    flag = " — **sin verificar** (< 20)" if n_pool is not None and n_pool < MIN_EVENTS else ""
    L.append(f"- Eventos independientes en test (agrupados entre regiones): {pooled}{flag}.")
    if not results.get("lgbm_available", True):
        L.append("- LightGBM no estaba instalado: solo climatología y logística.")
    L += ["", "## Fuente y alcance", ""]
    L.append(
        f"- Pronóstico: {meta.get('fc_source', 'GEFSv12 reforecast')}; {meta.get('fc_period', '')}; "
        f"{meta.get('n_cases', '?')} días, 1–10 días de anticipación, 5 miembros."
    )
    L.append(
        "- Observado: ERA5 `tp` y `convective_precipitation` diarios, 2000–2019, misma grilla."
    )
    L.append(f"- Catálogo de ríos atmosféricos F1.3: {meta.get('n_catalog_events', '?')} eventos.")
    L += ["", "## Regla fijada antes de correr", ""]
    sens_txt = ", ".join(v._f(float(k), 2) for k in sens_q) or "—"
    for line in RULE_LINES:
        L.append(
            line.replace("{q}", v._f(q, 2))
            .replace("{sens}", sens_txt)
            .replace("{n_boot}", str(meta.get("n_boot", 1000)))
            .replace("{seed}", str(meta.get("seed", 0)))
            .replace("{min_ev}", str(MIN_EVENTS))
        )
    L.append("")
    L += ["## Preponderancia de mecanismos (días de riesgo 2000–2019)", ""]
    for r in REGIONS:
        prep = results.get("preponderance", {}).get(r)
        if not prep:
            continue
        L += [f"### {REGION_LABELS[r]}", ""]
        rows = []
        for season in (*SEASONS, "all"):
            row = prep[season]
            cells = [("todo el año" if season == "all" else season), str(row["n"])]
            for m in MECHANISMS:
                d = row[m]
                cells.append(
                    f"{d['k']} ({_pct(d['share'])} [{_pct(d['lo'])}; {_pct(d['hi'])}])"
                    if row["n"]
                    else "—"
                )
            rows.append(cells)
        L += v._table(["Estación", "Días de riesgo", *[MECH_LABELS[m] for m in MECHANISMS]], rows)
    for r in REGIONS:
        reg = results.get("regions", {}).get(r, {})
        if not reg:
            continue
        leads = sorted(int(k) for k in reg)
        first = reg[str(leads[0])]
        L += [f"## {REGION_LABELS[r]}", ""]
        L.append(
            f"Umbral de riesgo: {v._f(_nan(thr.get(r)), 2)} mm/día (entrenamiento); tasa base en test "
            f"{_pct(first['base_rate'], 1)}; {first['n_days']} días y {first['n_events']} eventos en test"
            + (" — **sin verificar** (< 20 eventos)." if first["n_events"] < MIN_EVENTS else ".")
        )
        L.append("")
        rows = []
        for lead in leads:
            m = reg[str(lead)]["models"]
            g = lambda name, key, m=m: m.get(name, {}).get(key)
            br = lambda name, m=m: v._f(_nan(m.get(name, {}).get("brier")), 4)
            rows.append(
                [
                    str(lead),
                    br("clim"),
                    br("log"),
                    br("lgbm"),
                    _ci3(g("log", "bss_clim")),
                    _ci3(g("lgbm", "bss_clim")),
                    _ci3(g("lgbm", "bss_log")),
                    v._f(_nan(g("clim", "pr_auc"))),
                    v._f(_nan(g("log", "pr_auc"))),
                    v._f(_nan(g("lgbm", "pr_auc"))),
                ]
            )
        L += v._table(
            [
                "L (días)",
                "Brier clim.",
                "Brier log.",
                "Brier LGBM",
                "BSS log. vs clim. [IC]",
                "BSS LGBM vs clim. [IC]",
                "BSS LGBM vs log. [IC]",
                "PR-AUC clim.",
                "PR-AUC log.",
                "PR-AUC LGBM",
            ],
            rows,
        )
        L += [f"### {REGION_LABELS[r]}: acierto por mecanismo (test)", ""]
        ev = ", ".join(
            f"{MECH_LABELS[mm]}: {first['mechanisms'][mm]['n_events']} eventos"
            + (" (sin verificar)" if first["mechanisms"][mm]["sin_verificar"] else "")
            for mm in MECHANISMS
        )
        L += [ev + ".", ""]
        for model in ("log", "lgbm"):
            if not any(model in reg[str(lead)]["models"] for lead in leads):
                continue
            L += [
                f"**{MODEL_LABELS[model]}** (POD con p ≥ 0,5 / p ≥ 2×tasa base; BSS vs clim. [IC])",
                "",
            ]
            rows = []
            for lead in leads:
                mech = reg[str(lead)]["mechanisms"]
                row = [str(lead)]
                for mm in MECHANISMS:
                    e = mech[mm]
                    d = e["models"].get(model, {})
                    cell_pod = f"{v._f(_nan(d.get('pod_05')))} / {v._f(_nan(d.get('pod_2base')))}"
                    cell_bss = _ci3(d.get("bss_clim"))
                    if e["sin_verificar"]:
                        cell_pod += " (sin verificar)"
                        cell_bss += " (sin verificar)"
                    row += [cell_pod, cell_bss]
                rows.append(row)
            header = ["L (días)"]
            for mm in MECHANISMS:
                header += [f"POD {MECH_LABELS[mm]}", f"BSS {MECH_LABELS[mm]} [IC]"]
            L += v._table(header, rows)
        L += [
            "Probabilidad media pronosticada en los días de riesgo de cada mecanismo (logística):",
            "",
        ]
        rows = []
        for lead in leads:
            mech = reg[str(lead)]["mechanisms"]
            rows.append(
                [str(lead)]
                + [v._f(_nan(mech[mm]["models"].get("log", {}).get("mean_p"))) for mm in MECHANISMS]
            )
        L += v._table(["L (días)", *[MECH_LABELS[mm] for mm in MECHANISMS]], rows)
    L += ["## Sensibilidad", ""]
    leads_txt = ", ".join(map(str, SENS_LEADS))
    L += [
        f"BSS de la logística contra la climatología, anticipaciones {leads_txt} (valores puntuales).",
        "",
    ]
    header = ["Variante", "Región", *[f"L={x}" for x in SENS_LEADS]]
    rows = []
    sources = [(f"cuantil {v._f(q, 2)} (principal)", results)] + [
        (f"cuantil {v._f(float(k), 2)}", val) for k, val in sens_q.items()
    ]
    for label, res in sources:
        for r in REGIONS:
            reg = res.get("regions", {}).get(r, {})
            row = [label, REGION_LABELS[r]]
            for lead in SENS_LEADS:
                lg = reg.get(str(lead), {}).get("models", {}).get("log", {}).get("bss_clim")
                row.append(v._f(_nan(lg.get("value"))) if lg else "—")
            rows.append(row)
    L += v._table(header, rows)
    L += [
        "Regla de mecanismo: BSS de la logística sobre (días de riesgo del mecanismo ∪ sin riesgo).",
        "",
    ]
    rows = []
    for var in ("ar_pm1", "cp_0.4", "cp_0.6"):
        for r in REGIONS:
            reg = results.get("regions", {}).get(r, {})
            for mm in MECHANISMS[:2]:
                row = [var, REGION_LABELS[r], MECH_LABELS[mm]]
                for lead in SENS_LEADS:
                    d = reg.get(str(lead), {}).get("mechanism_variants", {}).get(var, {}).get(mm)
                    row.append(v._f(_nan(d.get("bss_log"))) if d else "—")
                rows.append(row)
    L += v._table(["Variante", "Región", "Mecanismo", *[f"L={x}" for x in SENS_LEADS]], rows)
    L += [
        "## Advertencias",
        "",
        (
            "- La referencia es ERA5, un reanálisis: es débil para convección (F3.4) y subestima la lluvia intensa; "
            "los aciertos incluyen el error de la referencia."
        ),
        (
            "- El catálogo F1.3 se detectó sobre la cordillera: en Confluencia «río atmosférico» significa que había "
            "un río atmosférico sobre Neuquén ese día."
        ),
        "- Menos de 20 eventos independientes en test (en total o por mecanismo) → «sin verificar».",
        "- Esto es retrospectivo y no es un sistema de alerta oficial; los avisos oficiales son del SMN, la AIC y Defensa Civil.",
        "",
    ]
    return "\n".join(L)

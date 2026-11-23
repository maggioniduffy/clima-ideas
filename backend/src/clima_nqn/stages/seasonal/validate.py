"""Nested validation of the seasonal model (F6.2): outer leave-one-hydro-year-out with a gap, and the
pure rolling-origin control. Predictions are cached per (scheme, target) in ``data/seasonal/preds/``.

Models per outer fold: ``logit`` and ``lgbm`` (pooled over leads; spec chosen by nested rolling origin
inside the training years), and sensitivities ``logit_lead`` (one logistic per lead) and ``logit_flow``
(feature set SRMF with the last monthly flow, which is NOT available operationally at issue).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from clima_nqn.stages.seasonal import data, folds, model
from clima_nqn.stages.seasonal.fetch import DATA_DIR

PRED_DIR = DATA_DIR / "preds"
OUTER_YEARS = list(
    range(1981, 2025)
)  # complete hydrological years (Apr y .. Mar y+1) with full features
CONTROL_YEARS = list(range(1995, 2025))
MODELS = ("logit", "lgbm", "logit_lead", "logit_flow")
BASELINES = ("clim", "clim_emp", "persist", "persist_cond", "enso")


def _flow_select(S, train_idx):
    """Logistic with SRMF: only C is chosen (inner), the feature set is fixed."""
    cfg, fset, _sc, _ = model.select(S, "logit", train_idx, sets=("SRMF",))
    return cfg, fset


def run_fold(S: data.Samples, fold: folds.Fold, models=MODELS) -> tuple[pd.DataFrame, list[dict]]:
    tr, te = fold.train, fold.test
    m = S.meta.iloc[te]
    ytest, tied = model.fold_labels(S, tr, te)
    out = pd.DataFrame(
        {
            "test_year": fold.test_year,
            "issue": m["issue"].values,
            "lead": m["lead"].values,
            "target_month": m["target_month"].values,
            "phase": m["phase"].values,
            "y": ytest,
            "tied": tied,
        }
    )
    cfgs: list[dict] = []

    def put(name, p):
        for c in range(3):
            out[f"p_{name}_{c}"] = p[:, c]

    for name, p in model.baseline_probs(S, tr, te).items():
        put(name, p)
    for name in models:
        if name in ("logit", "lgbm"):
            kind = name
            cfg, fset, sc, _ = model.select(S, kind, tr)
            cfgs.append(
                {"test_year": fold.test_year, "model": name, "fset": fset, **cfg, "inner_rps": sc}
            )
            put(name, model.fit_predict(S, kind, cfg, fset, tr, te))
        elif name == "logit_lead":
            p = np.full((len(te), 3), np.nan)
            for k in data.LEADS:
                trk = tr[S.meta["lead"].values[tr] == k]
                sel = m["lead"].values == k
                if not sel.any():
                    continue
                cfg, fset, sc, _ = model.select(S, "logit", trk, lead=None)
                cfgs.append({"test_year": fold.test_year, "model": f"logit_lead{k}", "fset": fset, **cfg,
                             "inner_rps": sc})  # fmt: skip
                p[sel] = model.fit_predict(S, "logit", cfg, fset, trk, te[sel])
            put(name, p)
        elif name == "logit_flow":
            cfg, fset = _flow_select(S, tr)
            cfgs.append({"test_year": fold.test_year, "model": name, "fset": fset, **cfg})
            put(name, model.fit_predict(S, "logit", cfg, fset, tr, te))
    return out, cfgs


def run_scheme(
    scheme: str,
    target: str,
    inp: data.Inputs,
    n_jobs: int = 2,
    force: bool = False,
    models=MODELS,
    log=print,
) -> Path:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    path = PRED_DIR / f"{scheme}-{target}.parquet"
    if path.exists() and not force:
        log(f"skip {path} (exists)")
        return path
    S = data.build_samples(inp, target)
    if scheme == "outer":
        fl = folds.outer_folds(S.meta["issue"], S.meta["target_month"], OUTER_YEARS)
    elif scheme == "control":
        fl = folds.rolling_origin(S.meta["issue"], S.meta["target_month"], CONTROL_YEARS)
    else:
        raise ValueError(scheme)
    t0 = time.monotonic()
    log(f"{scheme}/{target}: {len(fl)} folds, {len(S)} samples")
    res = Parallel(n_jobs=n_jobs)(delayed(run_fold)(S, f, models) for f in fl)
    preds = pd.concat([r[0] for r in res], ignore_index=True)
    cfgs = pd.DataFrame([c for r in res for c in r[1]])
    preds.attrs["configs"] = json.dumps(cfgs.to_dict("records"), default=float)
    preds.attrs["input_hashes"] = json.dumps(inp.hashes)
    tmp = path.with_name(path.name + ".tmp")
    preds.to_parquet(tmp, index=False)
    tmp.replace(path)
    cfgs.to_parquet(path.with_name(path.stem + ".configs.parquet"), index=False)
    log(f"{scheme}/{target}: done in {time.monotonic() - t0:.0f}s -> {path}")
    return path

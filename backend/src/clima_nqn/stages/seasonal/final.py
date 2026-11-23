"""Final model fitted on all years (only for targets that beat climatology in the outer scheme)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.stages.seasonal import data, model

MODEL_DIR = Path("models/seasonal-v1")


def fit_final(inp: data.Inputs, target: str, kind: str, out_dir: Path = MODEL_DIR) -> dict:
    """Select the spec by nested rolling origin over all years, fit on all years and save."""
    S = data.build_samples(inp, target)
    idx = np.arange(len(S))
    cfg, fset, inner_rps, table = model.select(S, kind, idx)
    ytr, _ = model.fold_labels(S, idx, idx)
    mdl, prep = model.fit_model(S, kind, cfg, fset, idx, ytr)
    tm = pd.DatetimeIndex(np.unique(S.meta["target_month"].values))
    ref = S.series.reindex(tm).dropna()
    meta = {
        "version": "seasonal-v1",
        "target": target,
        "kind": kind,
        "feature_set": fset,
        "features": data.FEATURE_SETS[fset],
        "config": cfg,
        "inner_rps": inner_rps,
        "inner_table": table,
        "classes": ["low", "mid", "high"],
        "leads": list(data.LEADS),
        "training_issues": [str(S.meta["issue"].min().date()), str(S.meta["issue"].max().date())],
        "training_target_months": [str(tm.min().date()), str(tm.max().date())],
        "n_samples": len(S),
        "tercile_rule": "mid-rank: p=(n_below+0.5 n_equal)/n per calendar month; low p<1/3, high p>2/3",
        "tercile_reference": {
            str(m): sorted(ref[ref.index.month == m].tolist()) for m in range(1, 13)
        },
        "anomaly_stats": {
            str(m): {c: [float(mu[i]), float(sd[i])] for i, c in enumerate(prep.anom)}
            for m, (mu, sd) in prep.stats.items()
        },
        "input_hashes": inp.hashes,
        "no_enso_input": True,
        "note": "Experimental; not an official alert. ERA5 0.25 deg, not ERA5-Land; boxes sin verificar.",
    }
    meta["input_hash"] = hashlib.sha256(
        json.dumps(inp.hashes, sort_keys=True).encode()
    ).hexdigest()[:16]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if kind == "logit":
        meta["coef"] = mdl.coef_.tolist()
        meta["intercept"] = mdl.intercept_.tolist()
    else:
        mdl.booster_.save_model(str(out_dir / f"{target}.txt"))
    (out_dir / f"{target}.json").write_text(json.dumps(meta, indent=1, default=float) + "\n")
    return {
        k: meta[k]
        for k in ("target", "kind", "feature_set", "config", "training_issues", "input_hash")
    }

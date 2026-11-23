"""Scores, skill tables and verdicts from the cached predictions -> ``reports/06/F6.2.json``."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.stages.seasonal import data, score, validate
from clima_nqn.stages.seasonal.fetch import DATA_DIR

REPORT_JSON = Path("../reports/06/F6.2.json")
MODEL_NAMES = ("logit", "lgbm", "logit_lead", "logit_flow")
REF_NAMES = validate.BASELINES
LEADS_ALL = [*data.LEADS, "all"]
VERDICT_MODELS = ("logit", "lgbm")


def _probs(df: pd.DataFrame, name: str) -> np.ndarray:
    return df[[f"p_{name}_{c}" for c in range(3)]].values


def skill_row(df: pd.DataFrame, model: str, ref: str, lead) -> dict | None:
    """RPSS and Brier skill (upper / lower tercile) of ``model`` vs ``ref``, bootstrap over test years."""
    d = df if lead == "all" else df[df["lead"] == lead]
    pm, pr = _probs(d, model), _probs(d, ref)
    ok = np.isfinite(pm).all(1) & np.isfinite(pr).all(1) & (d["y"].values >= 0)
    if not ok.any():
        return None
    y, yr = d["y"].values[ok], d["test_year"].values[ok]
    pm, pr = pm[ok], pr[ok]
    row = {"model": model, "ref": ref, "lead": lead, "n_samples": int(ok.sum()),
           "n_years": int(len(np.unique(yr)))}  # fmt: skip
    for key, fm, fr in (
        ("rps", score.rps(pm, y), score.rps(pr, y)),
        ("bs_upper", score.brier(pm, y, 2), score.brier(pr, y, 2)),
        ("bs_lower", score.brier(pm, y, 0), score.brier(pr, y, 0)),
    ):
        _, bm = score.year_means(fm, yr)
        _, br = score.year_means(fr, yr)
        sk, lo, hi = score.skill_ci(bm, br)
        row[key] = float(bm.mean())
        row[f"{key}_ref"] = float(br.mean())
        row[f"{key}_skill"] = sk
        row[f"{key}_lo"] = lo
        row[f"{key}_hi"] = hi
    return row


def by_year(df: pd.DataFrame, oni: pd.DataFrame, models: list[str]) -> list[dict]:
    rows = []
    for y, g in df.groupby("test_year"):
        row = {"year": int(y), "phase": data.hydro_phase(oni, int(y)), "n": int(len(g))}
        for name in [*models, *REF_NAMES]:
            p = _probs(g, name)
            ok = np.isfinite(p).all(1) & (g["y"].values >= 0)
            row[f"rps_{name}"] = float(score.rps(p[ok], g["y"].values[ok]).mean()) if ok.any() else None
            row[f"bs_upper_{name}"] = (
                float(score.brier(p[ok], g["y"].values[ok], 2).mean()) if ok.any() else None
            )
            row[f"bs_lower_{name}"] = (
                float(score.brier(p[ok], g["y"].values[ok], 0).mean()) if ok.any() else None
            )
        rows.append(row)
    return rows


def by_phase(df: pd.DataFrame, oni: pd.DataFrame, models: list[str]) -> list[dict]:
    df = df.assign(year_phase=[data.hydro_phase(oni, int(y)) for y in df["test_year"]])
    rows = []
    for ph, g in df.groupby("year_phase"):
        for model in models:
            for ref in ("clim", "clim_emp", "persist", "persist_cond", "enso"):
                r = skill_row(g, model, ref, "all")
                if r:
                    r["phase"] = ph
                    rows.append(r)
    return rows


def summarize_target(target: str, scheme: str, oni: pd.DataFrame, pred_dir: Path = validate.PRED_DIR) -> dict | None:
    path = Path(pred_dir) / f"{scheme}-{target}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    models = [m for m in MODEL_NAMES if f"p_{m}_0" in df]
    skill = []
    for model in models:
        for ref in REF_NAMES:
            for lead in LEADS_ALL:
                r = skill_row(df, model, ref, lead)
                if r:
                    skill.append(r)
    # RPS of the baselines against climatology (context), pooled
    base = []
    for ref in REF_NAMES[1:]:
        for lead in LEADS_ALL:
            r = skill_row(df, ref, "clim", lead)
            if r:
                base.append(r)
    valid = df["y"] >= 0
    cfgs = json.loads(df.attrs.get("configs", "[]")) if df.attrs.get("configs") else []
    return {
        "n_test_samples": int(valid.sum()),
        "tied_fraction": float(df.loc[valid, "tied"].mean()),
        "class_freq_test": [float((df.loc[valid, "y"] == c).mean()) for c in range(3)],
        "years": [int(df["test_year"].min()), int(df["test_year"].max())],
        "skill": skill,
        "baseline_vs_clim": base,
        "by_year": by_year(df, oni, models),
        "by_phase": by_phase(df, oni, models),
        "configs": cfgs,
    }


def verdicts(outer: dict) -> list[dict]:
    """``beats_climatology`` per target, lead and model: RPSS > 0 with the 95 % CI excluding 0 (outer)."""
    out = []
    for target, res in outer.items():
        if res is None:
            continue
        idx = {(r["model"], r["ref"], r["lead"]): r for r in res["skill"]}
        for lead in LEADS_ALL:
            for model in VERDICT_MODELS:
                a, b = idx.get((model, "clim", lead)), idx.get((model, "clim_emp", lead))
                if not a or not b:
                    continue
                third = bool(a["rps_lo"] > 0)
                emp = bool(b["rps_lo"] > 0)
                out.append({
                    "target": target, "lead": lead, "model": model,
                    "rpss_vs_clim": a["rps_skill"], "ci_vs_clim": [a["rps_lo"], a["rps_hi"]],
                    "rpss_vs_clim_emp": b["rps_skill"], "ci_vs_clim_emp": [b["rps_lo"], b["rps_hi"]],
                    "beats_clim_third": third, "beats_clim_emp": emp,
                    "beats_climatology": third and emp,
                })  # fmt: skip
    return out


def build(oni: pd.DataFrame, inp_hashes: dict | None = None) -> dict:
    targets = [*data.MAIN_TARGETS, *data.SENSITIVITY_TARGETS]
    res = {s: {t: summarize_target(t, s, oni) for t in targets} for s in ("outer", "control")}
    return {"results": res, "verdicts": verdicts(res["outer"]), "targets": targets}


def sanitize(obj):
    """Replace NaN / inf by None so the JSON is strictly valid."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return None if not np.isfinite(obj) else float(obj)
    return obj


def write_json(obj: dict, path: Path = REPORT_JSON) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize(obj), indent=1, default=float, allow_nan=False) + "\n")
    return path

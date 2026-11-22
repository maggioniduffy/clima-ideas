"""Frozen F5.3 logistic risk-day model, run on operational GEFS (F6.3, risk-day half).

Frozen exactly as the F5.8 gate evaluated it (``stages/hindcast/riskday.py``, imported, not copied):

* label: region-mean ERA5 ``tp`` >= the 0.95 quantile of the TRAIN days (2000-2011) of that region;
* fit period: TRAIN + VALID (2000-01-01..2014-12-31); nothing later is ever read for fitting;
* logistic regression on (log1p ensemble mean of the own region, fraction of members >= threshold, month
  sin/cos), standardized, C = 1.0, per (region, lead 1..10);
* climatology: monthly base rate over the same fit period.

Uncertainty: ``N_BOOT`` (200) coefficient sets from a block bootstrap over the fit rows. Blocks are the F5.3
event blocks (``riskday.event_blocks``: consecutive risk days of ANY region form one block, every other day
is its own block), resampled with replacement, seed 0. Each replicate refits the logistic on the *frozen*
scaler. The 90 % interval is the 5-95 % quantiles of the replicate probabilities, widened if needed so it
contains the point estimate (the bootstrap quantiles need not bracket the full-sample estimate).

Inference (``predict``) is numpy-only and reads a JSON file (``write_model`` / ``load_model``); sklearn is only
imported inside ``fit_frozen``.

Lead / valid_date: the GEFS lead L is the accumulation over hours (24(L-1), 24L] of the 00 UTC run, so
``valid = init + L - 1`` (``forecasts.LEAD_CONVENTION``). The registry demands ``valid = issue day +
lead_days``, so the record's ``lead_days`` is ``valid - issue day`` (= L - 1 when issued on the init day) and
the GEFS lead is kept in ``details["gefs_lead"]`` (the scoring table groups by it). Leads whose valid day
already passed (stale snapshot) cannot be issued and are skipped.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from clima_nqn.forecast.baselines import wilson
from clima_nqn.forecast.registry import (
    InputSource,
    PredictionDraft,
    PredictionRecord,
    PredictionRegistry,
    hash_inputs,
)
from clima_nqn.ops.ingest import INFO as _INGEST_INFO
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import riskday as rd

VAR_RISK = "p_dia_riesgo"
MODELS = ("logistica", "climatologia")
SCHEMA_VERSION = 1
N_BOOT = 200
SEED = 0
QUANTILE = 0.95
FIT_PERIOD = (rd.TRAIN[0], rd.VALID[1])
FIT_PERIOD_STR = f"{FIT_PERIOD[0]}/{FIT_PERIOD[1]}"
LEADS = tuple(range(1, 11))
ESTADO = "Experimental"
FEATURES = ("log1p_ens_mean_mm", "member_frac", "month_sin", "month_cos")
OPERATIONAL_SOURCE = f"{_INGEST_INFO['gefs_regions'].source}; media regional por miembro"
_CAP = 500.0


class RiskDayModelError(Exception):
    """The model file does not cover the request, or the inputs are unusable."""


def _sigmoid(x: np.ndarray | float) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -_CAP, _CAP)))


def _logit(p: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return float(np.log(p / (1 - p)))


# --- fit ------------------------------------------------------------------------------------------


def _fit_lr(z: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Logistic (C = 1.0, as ``riskday.fit_logistic``) on standardized ``z``; a single class -> its base rate."""
    from sklearn.linear_model import LogisticRegression

    if len(np.unique(y)) < 2:
        return np.zeros(z.shape[1]), _logit(float(np.mean(y)) if len(y) else 0.0)
    lr = LogisticRegression(C=1.0, max_iter=1000).fit(z, y)
    return lr.coef_[0].copy(), float(lr.intercept_[0])


def _block_groups(blocks: np.ndarray) -> list[np.ndarray]:
    order = np.argsort(blocks, kind="stable")
    cuts = np.flatnonzero(np.diff(blocks[order])) + 1
    return np.split(order, cuts)


def fit_frozen(ctx: dict, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Fit every (region, lead) as F5.8 did and return the JSON-ready model dict (see module docs).

    ``ctx`` is ``riskday.load_inputs`` output (or ``riskday.build_context``). Only rows dated within
    ``FIT_PERIOD`` are used for coefficients and climatology; the threshold only sees TRAIN days.
    """
    from sklearn.preprocessing import StandardScaler

    tp, dates, leads = ctx["tp"], ctx["dates"], ctx["leads"]
    obs_dates = tp.index
    thr = {r: rd.train_threshold(tp[r], QUANTILE) for r in rd.REGIONS}
    risk_obs = {r: (tp[r] >= thr[r]).to_numpy() & tp[r].notna().to_numpy() for r in rd.REGIONS}
    any_risk = pd.Series(np.any([risk_obs[r] for r in rd.REGIONS], axis=0), index=obs_dates)
    any_risk_d = any_risk.reindex(dates).fillna(False).to_numpy(dtype=bool)
    sp = rd.split_masks(dates)
    in_fit = sp["train"] | sp["valid"]
    month = dates.month.to_numpy()
    regions: dict[str, dict] = {}
    last_fit_date = None
    for ri, r in enumerate(rd.REGIONS):
        valid_obs = tp[r].notna().reindex(dates).fillna(False).to_numpy(dtype=bool)
        y_all = (
            pd.Series(risk_obs[r], index=obs_dates).reindex(dates).fillna(False).to_numpy(dtype=int)
        )
        for li, lead in enumerate(leads):
            feat = rd.feature_frame(ctx["members"], r, li, thr, dates)
            ok = valid_obs & ~np.isnan(feat["own_mean"].to_numpy())
            fit = in_fit & ok
            if not fit.any():
                continue
            x, y = rd._logistic_x(feat[fit]), y_all[fit]
            scaler = StandardScaler().fit(x)
            z = scaler.transform(x)
            coef, icpt = _fit_lr(z, y)
            groups = _block_groups(rd.event_blocks(dates[fit], any_risk_d[fit]))
            rng = np.random.default_rng([seed, ri, int(lead)])
            bcoef = np.empty((n_boot, z.shape[1]))
            bicpt = np.empty(n_boot)
            for b in range(n_boot):
                pick = rng.integers(0, len(groups), len(groups))
                rows = np.concatenate([groups[i] for i in pick])
                bcoef[b], bicpt[b] = _fit_lr(z[rows], y[rows])
            fm = month[fit]
            rates = rd.climatology_rates(fm, y)
            last = dates[fit].max()
            last_fit_date = last if last_fit_date is None else max(last_fit_date, last)
            regions.setdefault(r, {})[str(int(lead))] = {
                "scaler_mean": scaler.mean_.tolist(),
                "scaler_scale": scaler.scale_.tolist(),
                "coef": coef.tolist(),
                "intercept": icpt,
                "boot_coef": bcoef.tolist(),
                "boot_intercept": bicpt.tolist(),
                "threshold_mm": thr[r],
                "clim_rates": [float(v) for v in rates],
                "clim_n": [int((fm == m).sum()) for m in range(1, 13)],
                "n_fit": int(fit.sum()),
                "n_fit_risk_days": int(y.sum()),
                "prob_cap": None,  # filled by a later run (F5.8 reliability cap)
            }
    return {
        "meta": {
            "model_name": "logistica",
            "schema_version": SCHEMA_VERSION,
            "fit_period": FIT_PERIOD_STR,
            "fit_last_date": None if last_fit_date is None else f"{last_fit_date:%Y-%m-%d}",
            "train_period_threshold": f"{rd.TRAIN[0]}/{rd.TRAIN[1]}",
            "threshold_quantile": QUANTILE,
            "source": fc.SOURCE_GEFS,
            "members": list(fc.GEFS_MEMBERS),
            "lead_convention": fc.LEAD_CONVENTION,
            "features": list(FEATURES),
            "n_boot": n_boot,
            "seed": seed,
            "bootstrap": "block bootstrap over riskday.event_blocks, frozen scaler; interval = 5-95 %",
            "interval_level": 0.9,
        },
        "regions": regions,
    }


# --- JSON io --------------------------------------------------------------------------------------


def dumps_model(model: dict) -> str:
    """Deterministic JSON (sorted keys, no NaN)."""
    return json.dumps(model, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def write_model(model: dict, path: Path) -> str:
    """Write ``model`` and return the SHA-256 of the file."""
    text = dumps_model(model)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_model(path: Path) -> tuple[dict, str]:
    """(model dict, SHA-256 of the file bytes)."""
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def model_version(sha256: str, kind: str = "log") -> str:
    """``riskday-log-v1-<8 hex>`` (``kind`` "log" or "clim"), tied to the JSON file."""
    return f"riskday-{kind}-v{SCHEMA_VERSION}-{sha256[:8]}"


# --- inference (numpy only) -----------------------------------------------------------------------


def _entry(model: dict, region: str, lead: int) -> dict:
    try:
        return model["regions"][region][str(int(lead))]
    except KeyError as e:
        raise RiskDayModelError(f"model has no entry for region {region!r}, lead {lead}") from e


def predict(
    model: dict, region: str, lead: int, members_mm: dict[str, Any], month: int
) -> tuple[float, float, float, float, dict[str, float]]:
    """(p, p05, p95, clim_p, features) for ``region`` at GEFS ``lead`` valid in ``month`` (1..12).

    ``members_mm[region]``: regional-mean mm of every ensemble member for that lead; NaN members are ignored,
    none left -> ``RiskDayModelError``. The 90 % interval is the bootstrap 5-95 % quantiles clamped to contain
    ``p`` (``p05 <= p <= p95`` always holds).
    """
    e = _entry(model, region, lead)
    if region not in members_mm:
        raise RiskDayModelError(f"no members for region {region!r}")
    m = np.asarray(members_mm[region], dtype=float).ravel()
    m = m[~np.isnan(m)]
    if m.size == 0:
        raise RiskDayModelError(f"no valid members for {region!r}, lead {lead}")
    thr = float(e["threshold_mm"])
    mean, frac = float(m.mean()), float((m >= thr).sum() / m.size)
    ang = 2 * np.pi * int(month) / 12
    x = np.array([np.log1p(max(mean, 0.0)), frac, np.sin(ang), np.cos(ang)])
    z = (x - np.asarray(e["scaler_mean"])) / np.asarray(e["scaler_scale"])
    p = float(_sigmoid(z @ np.asarray(e["coef"]) + e["intercept"]))
    boot = _sigmoid(z @ np.asarray(e["boot_coef"]).T + np.asarray(e["boot_intercept"]))
    lo, hi = np.quantile(boot, [0.05, 0.95])
    feats = {
        "ens_mean_mm": mean,
        "ens_max_mm": float(m.max()),
        "member_frac": frac,
        "n_members": int(m.size),
        "threshold_mm": thr,
    }
    return p, min(float(lo), p), max(float(hi), p), float(e["clim_rates"][int(month) - 1]), feats


# --- operational snapshot and emission ------------------------------------------------------------

SNAPSHOT_COLUMNS = ("init_date", "lead", "valid_date", "member", "region", "tp_mm", "available_on")


def latest_snapshot(directory: Path, day: date) -> Path:
    """Newest ``<YYYY-MM-DD>.parquet`` with a date <= ``day``."""
    found = []
    for p in Path(directory).glob("*.parquet"):
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d <= day:
            found.append((d, p))
    if not found:
        raise FileNotFoundError(f"no GEFS regional snapshot <= {day} in {directory}")
    return max(found)[1]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


CAP_RULE = (
    "Tope de probabilidad vigente (F5.8, decisión del usuario 2026-11-22): borde superior del bin de "
    "confiabilidad más alto con al menos 20 días pronosticados, agrupando los días de test de las "
    "anticipaciones L-1, L y L+1, y no creciente en L. Por encima del tope se muestra «> tope»."
)


def caps_path(model_path: Path) -> Path:
    """Sidecar next to the model (``x.json`` -> ``x.caps.json``); the model file itself is never rewritten, so
    its sha256 (and the ``model_version`` derived from it) does not change when the caps do."""
    p = Path(model_path)
    return p.with_name(p.stem + ".caps.json")


def caps_from_gate(gate_path: Path) -> dict:
    """Region -> GEFS lead -> cap in force, read from ``F5.8.json`` (key ``prob_cap_vigente``)."""
    raw = Path(gate_path).read_bytes()
    gate = json.loads(raw)
    caps: dict[str, dict[str, float | None]] = {}
    for region, leads in gate["regions"].items():
        caps[region] = {
            str(k): leads[str(k)].get("prob_cap_vigente") for k in sorted(leads, key=int)
        }
    return {
        "source": Path(gate_path).name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "rule": CAP_RULE,
        "caps": caps,
    }


def write_caps(gate_path: Path, model_path: Path) -> Path:
    out = caps_path(model_path)
    out.write_text(
        json.dumps(caps_from_gate(gate_path), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out


def load_caps(model_path: Path) -> dict | None:
    p = caps_path(model_path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def build_drafts(
    model: dict,
    model_sha: str,
    snapshot: pd.DataFrame,
    snapshot_sha: str,
    issue_date: datetime,
    models: tuple[str, ...] = MODELS,
    caps: dict | None = None,
) -> list[PredictionDraft]:
    """Region x lead drafts per requested model (logistica, climatologia) from one GEFS snapshot."""
    unknown = set(models) - set(MODELS)
    if unknown or not models:
        raise ValueError(f"unknown models: {sorted(unknown)}")
    missing = [c for c in SNAPSHOT_COLUMNS if c not in snapshot.columns]
    if missing:
        raise ValueError(f"snapshot lacks columns {missing}")
    inits = pd.to_datetime(snapshot["init_date"]).dt.date.unique()
    if len(inits) != 1:
        raise ValueError(f"snapshot must hold exactly one init_date, got {sorted(inits)}")
    init = inits[0]
    day = issue_date.date()
    if init > day:
        raise ValueError(f"init_date {init} is after the issue date {day}")
    in_hash = hash_inputs({"snapshot_sha256": snapshot_sha, "model_sha256": model_sha})
    inputs = [InputSource(name=OPERATIONAL_SOURCE, latency_hours=float((day - init).days * 24))]
    snap = snapshot.assign(valid=pd.to_datetime(snapshot["valid_date"]).dt.date, init=init)
    drafts: list[PredictionDraft] = []
    for region in rd.REGIONS:
        for lead in LEADS:
            sub = snap[(snap["region"] == region) & (snap["lead"] == lead)]
            if sub.empty:
                continue
            valid = sub["valid"].iloc[0]
            if valid != init + timedelta(days=lead - 1):
                raise ValueError(f"valid_date {valid} breaks init + lead - 1 for lead {lead}")
            if valid < day:
                continue  # already elapsed: the registry cannot issue it
            arr = sub["tp_mm"].to_numpy(dtype=float)
            if np.isnan(arr).all():
                continue
            p, lo, hi, cp, feats = predict(model, region, lead, {region: arr}, valid.month)
            cap = _entry(model, region, lead).get("prob_cap")
            if caps is not None:
                cap = caps["caps"].get(region, {}).get(str(lead), cap)
            n = int(_entry(model, region, lead)["clim_n"][valid.month - 1])
            common: dict[str, Any] = {
                "issue_date": issue_date,
                "variable": VAR_RISK,
                "region": region,
                "lead_days": (valid - day).days,
                "valid_date": valid,
                "kind": "probability",
                "interval_level": 0.9,
                "training_period": FIT_PERIOD_STR,
                "inputs": inputs,
                "inputs_sha256": in_hash,
            }
            details = {
                **feats,
                "clim_prob": cp,
                "prob_cap": cap,
                **({"prob_cap_rule": caps["rule"]} if caps is not None else {}),
                "estado": ESTADO,
                "gefs_init_date": init.isoformat(),
                "gefs_lead": lead,
            }
            if "logistica" in models:
                drafts.append(
                    PredictionDraft(
                        **common,
                        value=p,
                        interval_low=lo,
                        interval_high=hi,
                        model_name="logistica",
                        model_version=model_version(model_sha, "log"),
                        details=details,
                    )
                )
            if "climatologia" in models:
                clo, chi = wilson(cp * n, n)
                drafts.append(
                    PredictionDraft(
                        **common,
                        value=cp,
                        interval_low=min(clo, cp),
                        interval_high=max(chi, cp),
                        model_name="climatologia",
                        model_version=model_version(model_sha, "clim"),
                        details={**details, "n_samples": n},
                    )
                )
    return drafts


def emit(
    registry: PredictionRegistry,
    model: dict,
    model_sha: str,
    snapshot_path: Path,
    issue_date: datetime | date,
    models: tuple[str, ...] = MODELS,
    caps: dict | None = None,
) -> list[PredictionRecord]:
    """Build and append the risk-day predictions of one GEFS snapshot; returns the appended records.

    A plain ``date`` is stamped with the registry clock, which must be on that day; a ``datetime`` goes to the
    registry as given (a past one is rejected there).
    """
    if not isinstance(issue_date, datetime):
        now = registry.now()
        if now.date() != issue_date:
            raise ValueError(f"issue date {issue_date} is not the registry's today ({now.date()})")
        issue_date = now
    elif issue_date.tzinfo is None:
        issue_date = issue_date.replace(tzinfo=UTC)
    snap = pd.read_parquet(snapshot_path)
    drafts = build_drafts(
        model, model_sha, snap, _file_sha256(snapshot_path), issue_date, models, caps
    )
    return registry.append_many(drafts)

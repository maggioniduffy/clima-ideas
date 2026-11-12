"""Test-period scores of the streamflow LSTM against GR4J+CemaNeige and persistence (F2.5).

Usage (from ``backend/``, after ``flow lstm-train``)::

    uv run clima-nqn flow streamflow-eval --run-name sim-default

Per Neuquén station, on the target days of the test years (``lstm.SPLITS``): NSE and KGE of the LSTM
(ensemble median), of GR4J+CemaNeige and, in ``forecast`` mode, of persistence (the flow observed on the
issue day). ``sim`` mode has one overall entry (lead ``"0"``); ``forecast`` has leads 1-7. Each score
uses only the days where every compared model has a value (a common set per station and lead, ``n``).
The 90 % band coverage is the share of observed days inside the band built from the validation-period
residual quantiles (``lstm.band``).

GR4J+CemaNeige is calibrated per station on the training years (KGE, differential evolution, 3 seeds,
the best calibration KGE is kept; DE can land in a local optimum with a small x1 and a strongly negative
x2, hence the seeds), with up to one year of warm-up before the training period, then simulated over the
whole forcing period. Forcing days are UTC and flow days are local; the offset is not corrected. The
first 365 days of each series are not scored for any model (LSTM context window, GR4J spin-up).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.stages.flood import hydro_models as hm
from clima_nqn.stages.flood import lstm

GR4J_SEEDS = (0, 1, 2)
WARMUP_DAYS = 365
OP_NOTE = "pronóstico retrospectivo con meteorología observada (ERA5), no pronóstico operativo"
UTC_NOTE = "Los días de caudal son locales (UTC-3) y los de forzante UTC; el desfase no se corrige."
DEFAULT_REPORT_NAME = "metrics.json"


def band_coverage(obs, lo, hi) -> float:
    """Share of the observed days (NaN ignored) with ``lo <= obs <= hi``; NaN if none."""
    obs, lo, hi = (np.asarray(a, dtype=float) for a in (obs, lo, hi))
    ok = ~np.isnan(obs)
    if not ok.any():
        return float("nan")
    return float(np.mean((obs[ok] >= lo[ok]) & (obs[ok] <= hi[ok])))


def gr4j_baseline(
    basin: lstm.Basin,
    split: str,
    seeds: tuple = GR4J_SEEDS,
    maxiter: int = 50,
    popsize: int = 8,
) -> dict:
    """Calibrate GR4J+CemaNeige on the training years and simulate the whole period (mm/d)."""
    precip, temp, pet = basin.x[:, 0], basin.x[:, 1], basin.x[:, 4]
    if np.isnan(temp).any() or np.isnan(pet).any():
        raise ValueError(
            f"station {basin.id}: GR4J needs tmean_c and pet_mm without NaN (temperature missing in "
            "the forcing; rerun `clima-nqn flow forcing --t2m-dir ...`)"
        )
    n_filled = int(np.isnan(precip).sum())
    precip = np.nan_to_num(precip)  # a few missing precipitation days (end of the ERA5 record) -> 0
    train = np.flatnonzero(split_train(basin.dates, split))
    if not len(train):
        raise ValueError(f"station {basin.id}: no training years in split {split!r}")
    i0, i1 = int(train.min()), int(train.max())
    start = max(0, i0 - WARMUP_DAYS)
    sl = slice(start, i1 + 1)
    qobs = basin.q[sl].copy()
    qobs[: i0 - start] = np.nan  # warm-up days are not scored
    best = None
    for seed in seeds:
        cal = hm.calibrate(
            precip[sl], temp[sl], pet[sl], qobs, warmup=i0 - start, seed=seed,
            maxiter=maxiter, popsize=popsize,
        )  # fmt: skip
        if best is None or cal.kge > best[1].kge:
            best = (seed, cal)
    seed, cal = best
    q = hm.simulate(cal.params, precip, temp, pet).q
    return {
        "q": np.asarray(q, dtype=float),
        "seed": int(seed),
        "kge_cal": float(cal.kge),
        "params": dict(zip(hm.Params._fields, (float(v) for v in cal.params), strict=True)),
        "calibration_period": f"{basin.dates[i0]:%Y-%m-%d} to {basin.dates[i1]:%Y-%m-%d}",
        "warmup_days": int(i0 - start),
        "precip_nan_days_set_to_0": n_filled,
    }


def split_train(dates: pd.DatetimeIndex, split: str) -> np.ndarray:
    return lstm.split_labels(dates, split) == lstm.PART_NAMES.index("train")


EXCLUDED_HYDRO_YEAR = 2023  # sensitivity: the 2023-06 flood dominates squared-error scores
LOG_EPS_FRACTION = 0.01  # log-NSE offset: 0.01 x mean observed training flow of the station


def _scores(obs: np.ndarray, sim: np.ndarray, log_eps: float | None = None) -> dict:
    out = {"nse": hm.nse(obs, sim), "kge": hm.kge(obs, sim)}
    if log_eps is not None:
        out["nse_log"] = hm.nse(np.log(obs + log_eps), np.log(np.clip(sim, 0.0, None) + log_eps))
    return out


def score_frame(
    frame: pd.DataFrame,
    models: list[str],
    quantiles: dict | None = None,
    log_eps: dict | None = None,
) -> dict:
    """``{basin_id: {lead: cell}}`` on the days where obs and every model have a value.

    A cell has ``n``, ``models`` (``nse``, ``kge`` and, with ``log_eps[basin_id]``, ``nse_log`` = NSE of
    ``log(q + eps)``), ``coverage90`` and ``excl_2023`` (``n`` and ``models`` again without the target
    days of hydrological year 2023, 2023-04-01..2024-03-31).
    """
    out: dict = {}
    for (bid, lead), g in frame.groupby(["basin_id", "lead"], sort=True):
        ok = np.isfinite(g["obs"].to_numpy())
        for m in models:
            ok &= np.isfinite(g[m].to_numpy())
        eps = None if log_eps is None else log_eps.get(bid)
        obs = g["obs"].to_numpy()[ok]
        keep = lstm.hydro_year(pd.DatetimeIndex(g["date"]))[ok] != EXCLUDED_HYDRO_YEAR
        cell = {
            "n": int(ok.sum()),
            "models": {m: _scores(obs, g[m].to_numpy()[ok], eps) for m in models},
            "coverage90": None,
            "excl_2023": {
                "n": int(keep.sum()),
                "models": {m: _scores(obs[keep], g[m].to_numpy()[ok][keep], eps) for m in models},
            },
        }
        if "lstm" in models and quantiles and str(int(lead)) in quantiles:
            lo, hi = lstm.band(g["lstm"].to_numpy()[ok], quantiles[str(int(lead))])
            cell["coverage90"] = band_coverage(obs, lo, hi)
        out.setdefault(bid, {})[str(int(lead))] = cell
    return out


def _lookup(frame_dates: pd.Series, dates: pd.DatetimeIndex, values: np.ndarray) -> np.ndarray:
    return pd.Series(values, index=dates).reindex(pd.DatetimeIndex(frame_dates)).to_numpy()


def evaluate(
    basins: list[lstm.Basin],
    mode: str,
    split: str,
    hist: int = 365,
    lead: int = 7,
    run: lstm.Run | None = None,
    seeds: tuple = GR4J_SEEDS,
    maxiter: int = 50,
    popsize: int = 8,
    progress=lambda s: None,
) -> dict:
    """Metrics of GR4J, persistence (forecast) and, with ``run``, the LSTM on the test years."""
    norm = lstm.compute_norm(basins, split)
    ds = lstm.Dataset.from_basins(basins, split, norm)
    n_out = lead if mode == "forecast" else 1
    if run is not None:
        frame = lstm.predict_frame(run, ds, "test", groups=("neuquen",)).rename(
            columns={"pred": "lstm"}
        )
    else:
        ends = ds.sample_ends("test", mode, hist, n_out)
        frame = lstm.target_frame(ds, ends, mode, n_out)
    # the first WARMUP_DAYS of each series are not scored (GR4J spin-up, LSTM context)
    first = {b.id: b.dates[0] + pd.Timedelta(days=WARMUP_DAYS) for b in basins}
    frame = frame[frame["date"] >= frame["basin_id"].map(first)].reset_index(drop=True)
    gr4j, models = {}, []
    frame["gr4j"] = np.nan
    if mode == "forecast":
        frame["persistence"] = np.nan
    for b in basins:
        progress(f"GR4J+CemaNeige {b.id}")
        g = gr4j_baseline(b, split, seeds, maxiter, popsize)
        gr4j[b.id] = {k: v for k, v in g.items() if k != "q"}
        rows = frame["basin_id"] == b.id
        frame.loc[rows, "gr4j"] = _lookup(frame.loc[rows, "date"], b.dates, g["q"])
        if mode == "forecast":
            frame.loc[rows, "persistence"] = _lookup(frame.loc[rows, "issue_date"], b.dates, b.q)
    models = (
        (["lstm"] if run is not None else [])
        + ["gr4j"]
        + (["persistence"] if mode == "forecast" else [])
    )
    quantiles = run.quantiles if run is not None else None
    log_eps = {}
    for b in basins:
        train_q = b.q[split_train(b.dates, split)]
        log_eps[b.id] = LOG_EPS_FRACTION * float(np.nanmean(train_q))
    cells = score_frame(frame, models, quantiles, log_eps)
    stations = {}
    for bid, leads in cells.items():
        sub = frame[frame["basin_id"] == bid]
        stations[bid] = {
            "test_period": f"{sub['date'].min():%Y-%m-%d} to {sub['date'].max():%Y-%m-%d}",
            "leads": leads,
        }
    summary = {}
    for k in sorted({k for s in stations.values() for k in s["leads"]}, key=int):
        summary[k] = {
            m: {
                s: float(np.nanmedian([st["leads"][k]["models"][m][s] for st in stations.values()]))
                for s in ("nse", "kge")
            }
            for m in models
        }
    test_years = list(lstm.SPLITS[split]["test"])
    return {
        "mode": mode,
        "split": split,
        "test_years": test_years,
        "models": models,
        "sources": {
            "flow": "SNIH (SIPH) — Red Hidrológica Nacional, caudal medio diario",
            "forcing": "ERA5 (Copernicus Climate Change Service) por cuenca aproximada, sin verificar",
            "lstm_run": None if run is None else run.info.get("run_name"),
            "pretrain": None if run is None else run.info.get("pretrain", {}).get("source"),
        },
        "notes": [
            OP_NOTE,
            UTC_NOTE,
            f"Se excluyen los primeros {WARMUP_DAYS} días de cada serie (contexto del LSTM, arranque de GR4J).",
            (
                f"Sensibilidad: `excl_2023` excluye el año hidrológico {EXCLUDED_HYDRO_YEAR} "
                f"({EXCLUDED_HYDRO_YEAR}-04-01 a {EXCLUDED_HYDRO_YEAR + 1}-03-31); `nse_log` es el NSE de "
                f"log(q + {LOG_EPS_FRACTION} x caudal medio de entrenamiento), `log_eps_mm` por estación."
            ),
            "Cada puntaje usa solo los días en que todos los modelos comparados tienen valor (n).",
        ],
        "log_eps_mm": log_eps,
        "gr4j": gr4j,
        "stations": stations,
        "median_over_stations": summary,
    }


def _f(x, nd=2) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def metrics_table(metrics: dict) -> str:
    """Markdown table: one row per station and lead, NSE/KGE per model (and band coverage)."""
    models = metrics["models"]
    head = ["Estación", "Horizonte (días)", "n", *[f"{m} NSE" for m in models],
            *[f"{m} KGE" for m in models], "Cobertura banda 90 %"]  # fmt: skip
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for sid, st in metrics["stations"].items():
        for k, cell in st["leads"].items():
            row = [sid, k, str(cell["n"])]
            row += [_f(cell["models"][m]["nse"]) for m in models]
            row += [_f(cell["models"][m]["kge"]) for m in models]
            row.append(_f(cell["coverage90"]))
            lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def sensitivity_table(metrics: dict) -> str:
    """Markdown table of the sensitivity scores: NSE without hydrological year 2023 and log-NSE."""
    models = metrics["models"]
    head = ["Estación", "Horizonte (días)", *[f"{m} NSE sin 2023" for m in models],
            *[f"{m} NSE log" for m in models]]  # fmt: skip
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for sid, st in metrics["stations"].items():
        for k, cell in st["leads"].items():
            row = [sid, k]
            row += [_f(cell["excl_2023"]["models"][m]["nse"]) for m in models]
            row += [_f(cell["models"][m].get("nse_log")) for m in models]
            lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def write_metrics(metrics: dict, out_dir: Path | str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / DEFAULT_REPORT_NAME
    path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    (out / "metrics.md").write_text(
        metrics_table(metrics) + "\n\n" + sensitivity_table(metrics) + "\n"
    )
    return path

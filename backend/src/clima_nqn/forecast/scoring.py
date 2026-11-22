"""Prospective verification (F6.5).

Rule: verification uses ONLY records from the F6.4 registry (``score_registry`` verifies the hash chain first).
A record is scored once an observation exists for its ``valid_date``; otherwise it stays ``pending``.

Scores
------
* ``abs_error``: |median - observed| for ``caudal_diario``.
* ``crps``: CRPS approximated from the recorded quantile set as 2 * mean_tau pinball_tau(y - q_tau) over the
  levels present (0.05, 0.25, 0.5, 0.75, 0.95). Exact for a point forecast (= absolute error); the tails
  beyond the 5-95 % levels are ignored, so it slightly underestimates the CRPS of heavy-tailed forecasts.
* ``brier``: (p - o)^2 for ``p_caudal_alto`` (o = observed flow > the record's ``threshold_m3s``) and for
  ``p_dia_riesgo`` (o = observed regional daily rain >= the record's ``threshold_mm``). For ``p_dia_riesgo`` the
  registry ``region`` is a region id (not a station) and ``lead`` is the GEFS lead (``details["gefs_lead"]``;
  the registry ``lead_days`` is valid - issue day). The column is still called ``station``.

Skill and uncertainty
---------------------
Skill = 1 - S_model / S_climatologia on paired cases (same variable, station, lead, issue and valid date),
with S the mean CRPS (``caudal_diario``) or Brier (``p_caudal_alto``). The 95 % CI is a block bootstrap
(``n_boot`` draws, fixed seed) resampling blocks of valid dates falling in the same 7-day week, so days of
one system (consecutive valid days) stay together. Tables with fewer than 10 independent events (runs of
consecutive valid days above the threshold) are marked "insuficiente". POD and FAR use p > 0.5.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

import numpy as np
import pandas as pd

from clima_nqn.forecast.baselines import VAR_FLOW, VAR_PROB
from clima_nqn.forecast.registry import PredictionRecord, PredictionRegistry
from clima_nqn.forecast.riskday_model import VAR_RISK

MIN_EVENTS = 10
SEASON_MONTHS = (5, 9)  # wet season May-September
SEASON_END = (9, 30)
P_ALARM = 0.5
BASELINE = "climatologia"
SCORE_OF = {VAR_FLOW: "crps", VAR_PROB: "brier", VAR_RISK: "brier"}
PROB_VARS = (VAR_PROB, VAR_RISK)
# "station" = station id, or region id for p_dia_riesgo
GROUP = ["model", "variable", "station", "lead"]


def pinball(y: float, q: float, tau: float) -> float:
    return tau * (y - q) if y >= q else (1 - tau) * (q - y)


def crps_from_quantiles(y: float, quantiles: Mapping[str, float]) -> float:
    """CRPS ~ 2 * mean over the given levels of the pinball loss."""
    return 2.0 * float(np.mean([pinball(y, v, float(k)) for k, v in quantiles.items()]))


def brier(p: float, event: bool) -> float:
    return (p - float(event)) ** 2


def _lookup(observed: pd.Series | Mapping[date, float]) -> dict[date, float]:
    items = observed.items()
    out: dict[date, float] = {}
    for k, v in items:
        if v is None or pd.isna(v):
            continue
        out[pd.Timestamp(k).date()] = float(v)
    return out


def read_regional_observations(directory) -> dict[str, pd.Series]:
    """Observed regional daily rain (mm) per region from ``<date>.parquet`` snapshots (columns date, region,
    tp_mm, available_on). ERA5T is revised, so for each (date, region) the value from the newest
    ``available_on`` wins; NaN values are dropped."""
    from pathlib import Path

    frames = [pd.read_parquet(p) for p in sorted(Path(directory).glob("*.parquet"))]
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["tp_mm"]).sort_values("available_on", kind="stable")
    df = df.drop_duplicates(["date", "region"], keep="last")
    return {
        str(r): g.assign(date=pd.to_datetime(g["date"])).set_index("date")["tp_mm"].sort_index()
        for r, g in df.groupby("region")
    }


COLUMNS = [
    "seq", "model", "model_version", "variable", "station", "lead", "issue_date", "valid_date",
    "status", "observed", "threshold", "p", "clim_prob", "event", "abs_error", "crps", "brier",
]  # fmt: skip


def score(
    records: Iterable[PredictionRecord], observed: pd.Series | Mapping[date, float]
) -> pd.DataFrame:
    """One row per record; ``status`` is "scored" or "pending" (no observation yet / no threshold)."""
    obs = _lookup(observed)
    rows = []
    for r in records:
        y = obs.get(r.valid_date)
        risk = r.variable == VAR_RISK
        thr = r.details.get("threshold_mm" if risk else "threshold_m3s")
        row = {
            "seq": r.seq,
            "model": r.model_name,
            "model_version": r.model_version,
            "variable": r.variable,
            "station": r.region,
            "lead": r.details.get("gefs_lead", r.lead_days) if risk else r.lead_days,
            "issue_date": r.issued_at.date(),
            "valid_date": r.valid_date,
            "status": "pending",
            "observed": y,
            "threshold": thr,
            "p": r.value if r.kind == "probability" else np.nan,
            "clim_prob": r.details.get("clim_prob", np.nan),
            "event": np.nan,
            "abs_error": np.nan,
            "crps": np.nan,
            "brier": np.nan,
        }
        if y is not None and thr is not None:
            row["status"] = "scored"
            event = bool(y >= thr) if risk else bool(y > thr)
            row["event"] = float(event)
            if r.variable == VAR_FLOW:
                row["abs_error"] = abs(r.value - y)
                q = r.details.get("quantiles")
                if q:
                    row["crps"] = crps_from_quantiles(y, q)
            elif r.variable in PROB_VARS:
                row["brier"] = brier(r.value, event)
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)


def score_registry(
    registry: PredictionRegistry, observed: pd.Series | Mapping[date, float]
) -> pd.DataFrame:
    """Verify the registry chain, then score its records."""
    registry.verify()
    return score(registry.read(), observed)


def _independent_events(valid_dates: pd.Series) -> int:
    """Runs of consecutive valid days count as one event."""
    days = sorted({d.toordinal() for d in valid_dates})
    return sum(1 for i, d in enumerate(days) if i == 0 or d - days[i - 1] > 1)


def wet_season(valid_date: date) -> int | None:
    """Year Y of the wet season May-September containing ``valid_date`` (None outside it)."""
    return valid_date.year if SEASON_MONTHS[0] <= valid_date.month <= SEASON_MONTHS[1] else None


def pooled_events(scores: pd.DataFrame) -> dict[str, dict[str, dict[str, int]]]:
    """Independent events pooled over ALL regions/stations, per variable and lead: runs of consecutive valid
    days on which ANY region had an event count as one (same rule as ``riskday.event_blocks``). Never the sum
    of per-region counts. Keys: variable -> str(lead) -> "overall" | str(season year, May-Sept only)."""
    done = scores[(scores["status"] == "scored") & (scores["event"] == 1)]
    out: dict[str, dict[str, dict[str, int]]] = {}
    for (variable, lead), g in done.groupby(["variable", "lead"], sort=True):
        if variable not in PROB_VARS:
            continue
        cell = {"overall": _independent_events(g["valid_date"])}
        seasons = g["valid_date"].map(wet_season)
        for y in sorted({int(x) for x in seasons.dropna()}):
            cell[str(y)] = _independent_events(g.loc[seasons == y, "valid_date"])
        out.setdefault(variable, {})[str(int(lead))] = cell
    return out


def season_table(
    scores: pd.DataFrame, today: date, n_boot: int = 2000, seed: int = 0
) -> tuple[pd.DataFrame, dict[str, dict[str, dict[str, int]]]]:
    """Skill per model x variable x station x lead x wet season (valid dates May-Sept of year ``season``;
    other cases are excluded), same method as ``skill_table``, plus ``complete`` (season end 30 Sept <
    ``today``) and ``n_events_pooled`` (all-region independent events of that variable/lead/season)."""
    pooled = pooled_events(scores)
    done = scores[(scores["status"] == "scored") & scores["variable"].isin(PROB_VARS)].copy()
    done["season"] = done["valid_date"].map(wet_season)
    parts = []
    for y in sorted({int(x) for x in done["season"].dropna()}):
        t = skill_table(done[done["season"] == y], n_boot=n_boot, seed=seed)
        if t.empty:
            continue
        t["season"] = y
        t["complete"] = date(y, SEASON_END[0], SEASON_END[1]) < today
        t["n_events_pooled"] = [
            pooled.get(v, {}).get(str(int(le)), {}).get(str(y), 0)
            for v, le in zip(t["variable"], t["lead"], strict=True)
        ]
        parts.append(t)
    return (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()), pooled


def _bootstrap_skill(
    sm: np.ndarray, sc: np.ndarray, blocks: np.ndarray, n_boot: int, rng: np.random.Generator
) -> tuple[float, float]:
    ub, inv = np.unique(blocks, return_inverse=True)
    bm = np.bincount(inv, weights=sm, minlength=len(ub))
    bc = np.bincount(inv, weights=sc, minlength=len(ub))
    idx = rng.integers(0, len(ub), size=(n_boot, len(ub)))
    den = bc[idx].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        skill = 1.0 - bm[idx].sum(axis=1) / den
    skill = skill[np.isfinite(skill)]
    if len(skill) == 0:
        return float("nan"), float("nan")
    lo, hi = np.percentile(skill, [2.5, 97.5])
    return float(lo), float(hi)


def skill_table(scores: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> pd.DataFrame:
    """Per model x variable x station x lead: n, mean score, skill vs climatologia with bootstrap CI, POD, FAR."""
    done = scores[scores["status"] == "scored"].copy()
    rng = np.random.default_rng(seed)
    pair_key = ["variable", "station", "lead", "issue_date", "valid_date"]
    out = []
    for (variable, station, lead), g in done.groupby(["variable", "station", "lead"], sort=True):
        col = SCORE_OF.get(variable)
        if col is None:
            continue
        clim = g[g["model"] == BASELINE][pair_key + [col]].rename(columns={col: "s_clim"})
        for model, m in g.groupby("model", sort=True):
            row = {
                "model": model,
                "variable": variable,
                "station": station,
                "lead": int(lead),
                "score": col,
                "n": len(m),
                "mean_score": float(m[col].mean()),
                "n_events": _independent_events(m.loc[m["event"] == 1, "valid_date"]),
                "skill": np.nan,
                "skill_ci_low": np.nan,
                "skill_ci_high": np.nan,
                "n_paired": 0,
                "pod": np.nan,
                "far": np.nan,
            }
            if len(clim):
                pr = m[pair_key + [col]].merge(clim, on=pair_key)
                row["n_paired"] = len(pr)
                if len(pr) and pr["s_clim"].sum() > 0:
                    sm, sc = pr[col].to_numpy(), pr["s_clim"].to_numpy()
                    row["skill"] = float(1 - sm.sum() / sc.sum())
                    weeks = np.array([d.toordinal() // 7 for d in pr["valid_date"]])
                    row["skill_ci_low"], row["skill_ci_high"] = _bootstrap_skill(
                        sm, sc, weeks, n_boot, rng
                    )
                elif len(pr) and model == BASELINE:
                    row["skill"] = 0.0
            if variable in PROB_VARS:
                alarm, ev = m["p"] > P_ALARM, m["event"] == 1
                hits, misses, false = (
                    int((alarm & ev).sum()),
                    int((~alarm & ev).sum()),
                    int((alarm & ~ev).sum()),
                )
                if hits + misses:
                    row["pod"] = hits / (hits + misses)
                if hits + false:
                    row["far"] = false / (hits + false)
            row["status"] = "insuficiente" if row["n_events"] < MIN_EVENTS else "ok"
            out.append(row)
    return pd.DataFrame(out)


def _num(x: float, nd: int = 3) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:.{nd}f}".replace(".", ",")


def to_markdown(table: pd.DataFrame, pending: int = 0) -> str:
    """Spanish markdown of the skill table, with the mandatory caveats."""
    caveats = (
        "Solo predicciones del registro congelado (F6.4). Skill = 1 − S/S_climatología sobre casos pareados "
        "(CRPS aproximado por cuantiles para caudal; Brier para probabilidad de caudal alto); IC 95 % por "
        "bootstrap de bloques semanales. POD y FAR con p > 0,5. Umbral provisional: p95 del período de "
        "entrenamiento. Día de riesgo (p_dia_riesgo): lluvia regional diaria ERA5T ≥ umbral de la región. "
        f'Tablas con menos de {MIN_EVENTS} eventos independientes: "insuficiente". '
        f"Predicciones pendientes de observación: {pending}."
    )
    lines = [
        "# Verificación prospectiva (F6.5)",
        "",
        "No es una alerta oficial. Ante una diferencia, siga los avisos de SMN, AIC y Defensa Civil.",
        "",
        caveats,
        "",
    ]
    if table.empty:
        return "\n".join(lines + ["Sin predicciones puntuadas todavía.", ""])
    lines += [
        "| Modelo | Variable | Estación / región | Anticip. (d) | n | Eventos | Puntaje medio | Skill | IC 95 % | POD | FAR | Estado |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for r in table.itertuples():
        ci = (
            f"[{_num(r.skill_ci_low)}; {_num(r.skill_ci_high)}]"
            if not pd.isna(r.skill_ci_low)
            else "—"
        )
        lines.append(
            f"| {r.model} | {r.variable} | {r.station} | {r.lead} | {r.n} | {r.n_events} | "
            f"{_num(r.mean_score)} | {_num(r.skill)} | {ci} | {_num(r.pod, 2)} | {_num(r.far, 2)} | {r.status} |"
        )
    lines.append("")
    return "\n".join(lines)

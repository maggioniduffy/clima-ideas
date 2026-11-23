"""High-flow leave-one-flood-out test (plan/06, F6.7): does P(Q > threshold) rise before each large flood?

Usage (from ``backend/``, needs ``uv sync --group ml`` for the LSTM)::

    uv run clima-nqn flow highflow-fetch-ops          # operational GEFS for the 2020-2025 windows
    uv run clima-nqn flow highflow                    # folds, scores, reports/06/F6.7.{md,json}

Method, fixed before looking at any result (the gate is criteria 1-4 of "Compuerta de evidencia" in
``plan/06-forecast.md``; this is the criterion 4 test, retrospective, not an official alert):

* Floods. Per station (12004, 12010, 12012) annual maxima (``extremes.annual_maxima``, F2.2 rule) whose
  peak has forecasts for every issue day of peak-15..peak+15: the GEFSv12 reforecast (valid days
  2000-01-10..2019-12-31) or the operational 0.25 deg archive (``pgrb2sp25``, from 2020-09-23), with ERA5
  forcing to the valid days. "Large" = annual maximum >= the median of the station's annual maxima (full
  record; used only to select floods, never as a model input). Floods out of coverage are listed with the
  reason. June 2023 at 12004 is operational and must be included.
* Folds. One fold = the hydrological year (April-March, ``lstm.hydro_year``) of a flood; floods of several
  stations in one year share the fold. Everything fitted for a fold (GR4J parameters, LSTM weights,
  normalization, validation residuals, thresholds, climatologies, residual quantiles) uses only dates
  outside that hydrological year +- 30 days (``highflow_data.fold_train_mask``; checked with
  ``check_no_leak`` inside the pipeline).
* Models. GR4J+CemaNeige (single layer) recalibrated per fold and station on 1980-2025 minus the fold
  (KGE, differential evolution, best of 3 seeds, bounds of ``hydro_models.BOUNDS``: the F2.5 baseline), and
  the F2.5 LSTM in ``sim`` mode (64 units, NSE* loss, 5-seed ensemble median). The LSTM is pretrained ONCE
  on CAMELS-CL (Chilean basins only, no Neuquén data, hence no leak; its normalization comes from the
  CAMELS-CL training rows only, so it stays valid for every fold) and fine-tuned per fold on the three
  Neuquén basins. Fine-tuning labels: validation = a fixed set of 6 hydrological years (the first six of
  2007, 2008, ... that are not the fold year or its two neighbours; used only for early stopping and for
  the LSTM residuals), excluded = fold +- 30 days, training = everything else. A training/validation window
  never contains an excluded date (``lstm.Dataset.sample_ends``). Without CAMELS-CL the LSTM is trained
  from scratch with a per-fold normalization (stated in the report).
* No observed flow enters any model at any point (SNIH lag 236 days, F6.1): GR4J and the LSTM ``sim`` mode
  take forcing only; ``build_lstm_windows`` has no flow argument and the window has ``lstm.n_inputs("sim")``
  channels.
* Forecast run. Issue day t = 00 UTC run of day t. State from ERA5 forcing up to t-1 (7 years of warm-up
  for GR4J, 365-day window for the LSTM). Lead L = 1..10 forces valid day v = t + L - 1 with the member's
  24 h total over the station box; days after the lead are not used. Temperatures of the lead days are the
  training day-of-year climatology of ERA5 (+-7 day window; tmean, tmin, tmax; PET by Oudin) in the main
  run; the sensitivity "temperatura perfecta" uses the observed ERA5 temperature (optimistic). No
  precipitation bias correction in the main run.
* Issue days t in [peak-15, peak+15]; scored pairs (t, L) with v in that window.
* Threshold. Main: median of the annual maxima of the training years (proxy of the 2-year level), per
  station and fold. Sensitivity: provisional p95 of the training daily flow (rule of
  ``forecast.baselines``, ``p_caudal_alto``).
* Probability. Each member's simulated flow is dressed with the model's log residuals
  ``e = log((obs + eps) / (sim + eps))`` (``eps`` = 0.01 mm/d; GR4J: all training days after the first
  year; LSTM: the 6 validation years, because in-sample LSTM residuals are optimistic; lead independent)
  represented by 200 quantiles: P = mean over members and residuals of 1[(sim + eps) exp(e) - eps > thr];
  the 90 % interval is the 5-95 % range of that mixture. Climatology: P(Q > thr) over training days within
  +-7 days of the day of year (Feb 29 folded onto Feb 28).
* Scores. Per flood and lead L (issue = peak - L + 1): P of each model and of the climatology, "rises" =
  P_model > P_clim, peak inside the 90 % interval. Per lead, pooled over floods: share that rises,
  interval coverage with Wilson 95 % CI against 0.90, Brier over all scored pairs of that lead, BSS against
  climatology with a 95 % bootstrap CI that resamples floods (1000, seed ``SEED``), and BSS of the LSTM
  against GR4J. A lead passes if the BSS CI is above 0, the coverage CI contains 0.90 and all shorter leads
  pass (criterion 2). The LSTM is shown only if its BSS against GR4J has a CI above 0 (criterion 3). Peaks
  above the training maximum are flagged "fuera del rango entrenado". The scored days are selected around
  floods that did happen, so there are no calm periods: the BSS is conditional on a flood, a necessary
  but not sufficient test.
* ``p_condclim`` is a column hook for ``conditional_clim`` (needs AR-event features that a daily pair does
  not have); it stays null unless a provider is given to ``build_pairs``.

Units: flow is mm/d inside the models (``lstm.M3S_TO_MM_DAY`` / area) and m3/s in the tables.
Days: forcing and GEFS days are UTC, flow days local (UTC-3); the offset is not corrected (as in F2.5).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.forecast import baselines
from clima_nqn.io import flow, forcing
from clima_nqn.stages.flood import highflow_data as hd
from clima_nqn.stages.flood import hydro_models as hm
from clima_nqn.stages.flood import lstm

REPORT_DIR = Path(__file__).resolve().parents[5] / "reports" / "06"
WORK_DIR = Path(__file__).resolve().parents[4] / "data" / "forecast" / "f67-highflow"
SEED = 20261123
N_BOOT = 1000
EPS_MM = lstm.EPS_MM
N_RESID = 200
WARMUP_FORECAST_DAYS = (
    2555  # 7 years: the state differs by ~0.1 % from the run since 1980 (checked)
)
GR4J_WARMUP_SCORE = 365  # days of the series not scored in the calibration
VAL_BASE_YEARS = tuple(range(2007, 2026))
N_VAL_YEARS = 6
WINDOW = baselines.WINDOW_DAYS
# DEM mean elevations (m) of the station boxes: reports/02/F2.5-bands.md ("La media del DEM es ...");
# the published forcing.static.json of data/f25-forcing has null elevations. Sin verificar.
ELEV_DEM_FALLBACK = {12004: 1657.0, 12010: 1434.0, 12012: 2144.0}
# variant -> (temperature of the lead days, threshold kind)
VARIANTS = {
    "main": ("clim", "main"),
    "thr_p95": ("clim", "p95"),
    "t_perfect": ("perfect", "main"),
}
MODELS = ("gr4j", "lstm")
OUT_OF_RANGE = "fuera del rango entrenado"
V_RISES, V_NOT = "sube antes del pico", "no sube"
NOT_AN_ALERT = "No es una alerta oficial: prueba retrospectiva para usuarios técnicos."


# --- data -------------------------------------------------------------------------------------


@dataclass
class Station:
    sid: int
    basin: lstm.Basin
    area_km2: float
    lat: float  # centroid latitude used for Oudin PET
    flow: pd.DataFrame  # date, q_m3s (daily, local days)

    def mm(self, q_m3s):
        return np.asarray(q_m3s, float) * lstm.M3S_TO_MM_DAY / self.area_km2

    def m3s(self, q_mm):
        return np.asarray(q_mm, float) * self.area_km2 / lstm.M3S_TO_MM_DAY

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.basin.dates


def load_stations(
    forcing_path: Path | str, flow_dir: Path | str, work_dir: Path | str = WORK_DIR
) -> tuple[dict[int, Station], dict]:
    """Neuquén stations (ERA5 box forcing + SNIH flow). Fills null DEM elevations from F2.5-bands."""
    forcing_path, flow_dir, work_dir = Path(forcing_path), Path(flow_dir), Path(work_dir)
    static_path = forcing_path.with_suffix(forcing.STATIC_SUFFIX)
    static = json.loads(static_path.read_text())
    patched = []
    for sid, b in static["basins"].items():
        if b.get("elev_mean_m") is None:
            b["elev_mean_m"] = ELEV_DEM_FALLBACK[int(sid)]
            patched.append(int(sid))
    use_path = forcing_path
    if patched:
        d = work_dir / "inputs"
        d.mkdir(parents=True, exist_ok=True)
        use_path = d / forcing_path.name
        if not use_path.exists():
            use_path.write_bytes(forcing_path.read_bytes())
        use_path.with_suffix(forcing.STATIC_SUFFIX).write_text(json.dumps(static, indent=1))
    basins, info = lstm.neuquen_basins(use_path, flow_dir)
    out = {}
    for b in basins:
        sid = int(b.id)
        out[sid] = Station(
            sid=sid,
            basin=b,
            area_km2=float(np.exp(b.static[0])),
            lat=float(static["basins"][str(sid)]["centroid_lat"]),
            flow=flow.read_flow(Path(flow_dir) / f"{sid}.parquet")[["date", "q_m3s"]],
        )
    info["elevation_filled_from_F2.5-bands"] = patched
    return out, info


# --- pure fitted quantities (training dates only) ---------------------------------------------


def doy_climatology(dates, values, train, window: int = WINDOW) -> np.ndarray:
    """Mean of ``values`` over training days within +-``window`` days of each day of year (366,)."""
    doy = baselines.day_of_year(pd.DatetimeIndex(dates))
    v = np.asarray(values, float)
    ok = np.asarray(train, bool) & np.isfinite(v)
    d, vv = doy[ok], v[ok]
    out = np.full(366, np.nan)
    for day in range(1, 366):
        dist = np.abs(d - day)
        m = np.minimum(dist, 365 - dist) <= window
        if m.any():
            out[day] = vv[m].mean()
    return out


def exceedance_climatology(dates, q, train, thr: float, window: int = WINDOW) -> np.ndarray:
    """P(q > thr) over training days within +-``window`` days of each day of year (366,)."""
    q = np.asarray(q, float)
    ok = np.asarray(train, bool) & np.isfinite(q)
    return doy_climatology(
        np.asarray(pd.DatetimeIndex(dates))[ok],
        (q[ok] > thr).astype(float),
        np.ones(ok.sum(), bool),
        window,
    )


def annual_max_threshold(flow_df: pd.DataFrame, train) -> float:
    """Median of the annual maxima (F2.2 rule) of ``flow_df`` with the non-training days removed."""
    from clima_nqn.stages.flood import extremes

    df = flow_df[["date", "q_m3s"]].copy()
    df.loc[~np.asarray(train, bool), "q_m3s"] = np.nan
    maxima, _ = extremes.annual_maxima(df)
    if maxima.empty:
        raise ValueError("no complete hydrological year left in the training days")
    return float(np.median(maxima["q_m3s"]))


def p95_threshold(flow_df: pd.DataFrame, train) -> float:
    q = flow_df["q_m3s"].to_numpy(float)
    ok = np.asarray(train, bool) & np.isfinite(q)
    return float(np.quantile(q[ok], baselines.THRESHOLD_QUANTILE))


def log_residuals(obs, sim, mask, eps: float = EPS_MM) -> np.ndarray:
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    ok = np.asarray(mask, bool) & np.isfinite(obs) & np.isfinite(sim)
    return np.log((obs[ok] + eps) / (sim[ok] + eps))


def residual_grid(res: np.ndarray, n: int = N_RESID) -> np.ndarray:
    """``n`` equally spaced quantiles ((i + 0.5) / n) of the residuals."""
    res = np.asarray(res, float)
    if len(res) < 10:
        raise ValueError("fewer than 10 residuals")
    return np.quantile(res, (np.arange(n) + 0.5) / n)


def fold_quantities(
    flow_df: pd.DataFrame,
    fold_year: int,
    sim_dates,
    obs_mm,
    sim_mm,
    gap_days: int = hd.GAP_DAYS,
    skip_first: int = GR4J_WARMUP_SCORE,
) -> dict:
    """Thresholds, exceedance climatologies and the GR4J residual grid of a fold, training days only.

    ``flow_df`` is the daily flow (m3/s); ``sim_dates, obs_mm, sim_mm`` the aligned forcing-date series
    of the observed and simulated flow (mm/d). ``used`` lists the dates behind each quantity so that
    ``check_no_leak`` can verify them.
    """
    fdates = pd.DatetimeIndex(flow_df["date"])
    ftrain = hd.fold_train_mask(fdates, fold_year, gap_days)
    thr_main = annual_max_threshold(flow_df, ftrain)
    thr_p95 = p95_threshold(flow_df, ftrain)
    q = flow_df["q_m3s"].to_numpy(float)
    sdates = pd.DatetimeIndex(sim_dates)
    strain = hd.fold_train_mask(sdates, fold_year, gap_days)
    after_warm = np.arange(len(sdates)) >= skip_first
    res_mask = strain & after_warm
    res = log_residuals(obs_mm, sim_mm, res_mask)
    ok_q = ftrain & np.isfinite(q)
    return {
        "thr_main_m3s": thr_main,
        "thr_p95_m3s": thr_p95,
        "pclim_main": exceedance_climatology(fdates, q, ftrain, thr_main),
        "pclim_p95": exceedance_climatology(fdates, q, ftrain, thr_p95),
        "train_max_m3s": float(q[ok_q].max()),
        "resid_gr4j": residual_grid(res),
        "used": {
            "flow_days": fdates[ok_q],
            "residual_days": sdates[res_mask & np.isfinite(np.asarray(obs_mm, float))],
        },
    }


# --- probability and scores -------------------------------------------------------------------


def dress(sim_members, resid_grid, eps: float = EPS_MM) -> np.ndarray:
    """Dressed samples (members x residuals), same units as ``sim_members``: (sim+eps) exp(e) - eps."""
    s = np.asarray(sim_members, float).reshape(-1, 1)
    e = np.asarray(resid_grid, float).reshape(1, -1)
    return np.clip((s + eps) * np.exp(e) - eps, 0.0, None).ravel()


def exceed_probability(samples, thr: float) -> float:
    return float(np.mean(np.asarray(samples) > thr))


def interval90(samples) -> tuple[float, float]:
    lo, hi = np.quantile(np.asarray(samples, float), [0.05, 0.95])
    return float(lo), float(hi)


def brier(p, o) -> float:
    p, o = np.asarray(p, float), np.asarray(o, float)
    return float(np.mean((p - o) ** 2))


def wilson(k: float, n: float, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval (95 %) for k of n; (0, 1) if n == 0."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return float(max(0.0, c - h)), float(min(1.0, c + h))


def bss_bootstrap(
    bs_model: np.ndarray, bs_ref: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED
) -> dict:
    """BSS = 1 - sum(bs_model) / sum(bs_ref) from per-flood Brier sums; 95 % CI resampling floods."""
    bs_model, bs_ref = np.asarray(bs_model, float), np.asarray(bs_ref, float)
    n = len(bs_model)
    with np.errstate(divide="ignore", invalid="ignore"):
        point = 1.0 - bs_model.sum() / bs_ref.sum() if bs_ref.sum() > 0 else float("nan")
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, n, size=(n_boot, n)) if n else np.zeros((n_boot, 0), int)
        den = bs_ref[idx].sum(axis=1)
        boots = 1.0 - bs_model[idx].sum(axis=1) / den
    boots = boots[np.isfinite(boots)]
    lo, hi = np.quantile(boots, [0.025, 0.975]) if len(boots) else (np.nan, np.nan)
    return {"bss": float(point), "lo": float(lo), "hi": float(hi), "n_floods": int(n)}


# --- GR4J --------------------------------------------------------------------------------------


def _gr4j_inputs(basin: lstm.Basin):
    precip = np.nan_to_num(basin.x[:, 0])
    return precip, basin.x[:, 1], basin.x[:, 4]


def calibrate_gr4j(
    st: Station, fold_year: int, seeds=(0, 1, 2), maxiter: int = 50, popsize: int = 8
) -> dict:
    """GR4J+CemaNeige on the training days of the fold (KGE, best of ``seeds``); sim over all days."""
    b = st.basin
    train = hd.fold_train_mask(b.dates, fold_year)
    precip, temp, pet = _gr4j_inputs(b)
    qobs = b.q.copy()
    qobs[~train] = np.nan
    best = None
    for seed in seeds:
        cal = hm.calibrate(
            precip, temp, pet, qobs, warmup=GR4J_WARMUP_SCORE, seed=seed, maxiter=maxiter,
            popsize=popsize,
        )  # fmt: skip
        if best is None or cal.kge > best[1].kge:
            best = (seed, cal)
    seed, cal = best
    sim = hm.simulate(cal.params, precip, temp, pet).q
    return {
        "params": cal.params,
        "kge_cal": float(cal.kge),
        "seed": int(seed),
        "sim_mm": np.asarray(sim, float),
        "train": train,
    }


def forcing_for_leads(
    st: Station, issue: pd.Timestamp, n_leads: int, clim: dict | None
) -> np.ndarray:
    """Dynamic inputs ``(n_leads, 5)`` (``lstm.DYNAMIC`` order) of the lead days, WITHOUT precipitation.

    ``clim`` = None: observed ERA5 temperature and PET ("temperatura perfecta"). Else day-of-year
    climatology arrays ``tmean, tmin, tmax`` (366,) with PET by Oudin from the climatological tmean.
    The precipitation column is NaN: the caller fills it with the member totals.
    """
    days = pd.date_range(issue, periods=n_leads)
    out = np.full((n_leads, 5), np.nan)
    if clim is None:
        pos = st.basin.dates.get_indexer(days)
        if (pos < 0).any():
            raise ValueError(f"station {st.sid}: forcing does not cover {days[0]}..{days[-1]}")
        out[:, 1:] = st.basin.x[pos, 1:]
    else:
        doy = baselines.day_of_year(days)
        tmean, tmin, tmax = clim["tmean"][doy], clim["tmin"][doy], clim["tmax"][doy]
        out[:, 1], out[:, 2], out[:, 3] = tmean, tmin, tmax
        out[:, 4] = forcing.oudin_pet(tmean, st.lat, days.day_of_year.to_numpy())
    return out


def forecast_gr4j(
    st: Station, params, issue: pd.Timestamp, precip_members: np.ndarray, lead_forcing: np.ndarray
) -> np.ndarray:
    """Simulated flow (mm/d) ``(members, leads)`` for the days issue..issue+leads-1.

    History: ERA5 forcing up to ``issue - 1`` (``WARMUP_FORECAST_DAYS`` before it); lead days: member
    precipitation and ``lead_forcing`` temperatures. No flow is read.
    """
    b = st.basin
    pos = int(b.dates.get_loc(pd.Timestamp(issue)))
    start = max(0, pos - WARMUP_FORECAST_DAYS)
    precip, temp, pet = _gr4j_inputs(b)
    n_leads = precip_members.shape[1]
    out = np.zeros(precip_members.shape)
    for m in range(precip_members.shape[0]):
        p = np.concatenate([precip[start:pos], precip_members[m]])
        t = np.concatenate([temp[start:pos], lead_forcing[:, 1]])
        e = np.concatenate([pet[start:pos], lead_forcing[:, 4]])
        out[m] = hm.simulate(params, p, t, e).q[-n_leads:]
    return out


# --- LSTM --------------------------------------------------------------------------------------


def build_lstm_windows(
    dyn: np.ndarray,
    static: np.ndarray,
    pos: int,
    fc_dyn: np.ndarray,
    norm: lstm.Norm,
    seq_len: int = 365,
) -> np.ndarray:
    """``sim``-mode input windows for the leads of one issue day: ``(members, leads, seq_len, C)``.

    ``dyn`` (T, 5) is the observed forcing history; only ``dyn[:pos]`` is read (days before the issue
    day). ``fc_dyn`` (members, leads, 5) holds the forcing of the days issue..issue+leads-1. The window
    of lead L ends on valid day issue+L-1: ``seq_len - L`` history days followed by the first L forecast
    days. C = ``lstm.n_inputs("sim")``: five dynamic + three static channels; there is NO flow channel.
    """
    dyn = np.asarray(dyn, float)
    fc_dyn = np.asarray(fc_dyn, float)
    members, leads = fc_dyn.shape[:2]
    if pos < seq_len:
        raise ValueError("not enough history for the window")
    hist = dyn[:pos]
    st = ((np.asarray(static, float) - norm.static_mean) / norm.static_std).astype(np.float32)
    out = np.zeros((members, leads, seq_len, lstm.n_inputs("sim")), dtype=np.float32)
    for lead in range(1, leads + 1):
        h = hist[pos - (seq_len - lead) :]
        for m in range(members):
            x = np.concatenate([h, fc_dyn[m, :lead]])
            out[m, lead - 1, :, : len(lstm.DYNAMIC)] = np.nan_to_num(
                (x - norm.dyn_mean) / norm.dyn_std
            )
            out[m, lead - 1, :, len(lstm.DYNAMIC) :] = st
    return out


def predict_windows(models: list, norm: lstm.Norm, x: np.ndarray) -> np.ndarray:
    """Per-seed predictions (mm/d), shape ``(seeds, N)``, clipped at 0, for windows ``(N, L, C)``."""
    torch = lstm.import_torch()
    out = np.zeros((len(models), len(x)))
    with torch.no_grad():
        for i in range(0, len(x), 512):
            xt = torch.from_numpy(np.ascontiguousarray(x[i : i + 512]))
            for s, model in enumerate(models):
                model.eval()
                out[s, i : i + 512] = model(xt, 1).numpy()[:, 0]
    return np.clip(out * norm.q_std + norm.q_mean, 0.0, None)


def forecast_lstm(
    models: list,
    norm: lstm.Norm,
    st: Station,
    issue: pd.Timestamp,
    precip_members: np.ndarray,
    lead_forcing: np.ndarray,
) -> np.ndarray:
    """Seed-median LSTM flow (mm/d) ``(members, leads)`` for the days issue..issue+leads-1."""
    members, leads = precip_members.shape
    pos = int(st.basin.dates.get_loc(pd.Timestamp(issue)))
    fc = np.repeat(lead_forcing[None], members, axis=0).copy()
    fc[:, :, 0] = precip_members
    x = build_lstm_windows(st.basin.x, st.basin.static, pos, fc, norm)
    pred = predict_windows(models, norm, x.reshape(members * leads, *x.shape[2:]))
    return np.median(pred, axis=0).reshape(members, leads)


@dataclass
class RunConfig:
    seeds: int = 5
    epochs: int = 30
    pretrain_epochs: int = 10
    samples_per_epoch: int = 20000
    gr4j_seeds: tuple = (0, 1, 2)
    maxiter: int = 50
    popsize: int = 8
    use_lstm: bool = True

    def train_config(self, pretrain: bool) -> lstm.TrainConfig:
        return lstm.TrainConfig(
            mode="sim", split="default", pretrain=pretrain, seeds=tuple(range(self.seeds)),
            epochs=self.epochs, pretrain_epochs=self.pretrain_epochs,
            samples_per_epoch=self.samples_per_epoch,
        )  # fmt: skip


def val_years(fold_year: int, n: int = N_VAL_YEARS) -> list[int]:
    """The first ``n`` of 2007, 2008, ... that are not the fold year or one of its two neighbours."""
    return [y for y in VAL_BASE_YEARS if abs(y - fold_year) >= 2][:n]


def fold_labels(dates, fold_year: int) -> np.ndarray:
    """``lstm.PART_NAMES`` labels: 1 train, 2 validation years, 3 excluded (fold +- gap), 0 none."""
    d = pd.DatetimeIndex(dates)
    lab = np.ones(len(d), dtype=np.int8)
    lab[np.isin(lstm.hydro_year(d), val_years(fold_year))] = 2
    lab[~hd.fold_train_mask(d, fold_year)] = 3
    return lab


def fold_dataset(basins: list[lstm.Basin], norm: lstm.Norm, fold_year: int) -> lstm.Dataset:
    ds = lstm.Dataset(basins, "default", norm)
    ds.labels = np.concatenate([fold_labels(b.dates, fold_year) for b in basins])
    train = ds.labels == lstm.PART_NAMES.index("train")
    ds.sigma_b = np.ones(len(basins), dtype=np.float32)
    for i in range(len(basins)):
        qi = ds.Q[train & (ds.basin_of == i)]
        qi = qi[np.isfinite(qi)]
        if len(qi) > 1 and qi.std() > 1e-6:
            ds.sigma_b[i] = qi.std()
    ds._cum = {}
    return ds


def fold_norm(basins: list[lstm.Basin], fold_year: int) -> lstm.Norm:
    """Normalization from the training rows of the fold (used only without CAMELS-CL pretraining)."""
    xs, qs = [], []
    for b in basins:
        tr = fold_labels(b.dates, fold_year) == 1
        xs.append(b.x[tr])
        qs.append(b.q[tr])
    x, q = np.concatenate(xs), np.concatenate(qs)
    st = np.stack([b.static for b in basins])
    return lstm.Norm(
        np.nan_to_num(np.nanmean(x, axis=0)), np.asarray(lstm._std(x, axis=0)),
        st.mean(axis=0), np.asarray(lstm._std(st, axis=0)),
        float(np.nan_to_num(np.nanmean(q))), float(lstm._std(q)),
    )  # fmt: skip


@dataclass
class Pretrained:
    norm: lstm.Norm
    cfg: lstm.TrainConfig
    dir: Path

    def state(self, seed: int):
        torch = lstm.import_torch()
        return torch.load(self.dir / f"model_seed{seed}.pt", weights_only=True)


_PRE_KEYS = (
    "hidden",
    "dropout",
    "seq_len",
    "loss_steps",
    "pretrain_epochs",
    "lr",
    "samples_per_epoch",
    "batch_size",
    "split",
)


def pretrain_once(
    camels: list[lstm.Basin],
    rc: RunConfig,
    out_dir: Path | str,
    progress=print,
    seed_list: tuple[int, ...] | list[int] | None = None,
) -> Pretrained:
    """Pretrain on CAMELS-CL once per seed (cached; no Neuquén data touched).

    ``seed_list`` restricts the seeds trained in this call (sharding over machines); ``norm.json`` and
    ``pretrain.json`` are deterministic, so shards write identical copies.
    """
    torch = lstm.import_torch()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = rc.train_config(True)
    key = {k: getattr(cfg, k) for k in _PRE_KEYS}
    cfg_path = out / "pretrain.json"
    if cfg_path.is_file() and json.loads(cfg_path.read_text()) != key:
        raise ValueError(f"{cfg_path} was made with another configuration; use another --work-dir")
    cfg_path.write_text(json.dumps(key, indent=1))
    norm = lstm.compute_norm(camels, cfg.split)  # CAMELS-CL training rows only
    (out / "norm.json").write_text(json.dumps(norm.to_dict(), indent=1))
    ds = None
    for seed in cfg.seeds:
        path = out / f"model_seed{seed}.pt"
        if path.is_file() or (seed_list is not None and seed not in seed_list):
            continue
        if ds is None:
            ds = lstm.Dataset.from_basins(camels, cfg.split, norm)
        progress(f"pretraining seed {seed} on {len(camels)} CAMELS-CL basins")
        model, hist = lstm.fit_model(
            ds, cfg, seed, cfg.pretrain_epochs, cfg.lr, ("camels",), progress=progress
        )
        torch.save(model.state_dict(), path)
        (out / f"history_seed{seed}.json").write_text(json.dumps(hist))
    return Pretrained(norm, cfg, out)


def load_pretrained(rc: RunConfig, pre_dir: Path | str) -> Pretrained:
    """The saved pretraining (``norm.json``, ``pretrain.json``, weights) without CAMELS-CL data."""
    pre_dir = Path(pre_dir)
    cfg = rc.train_config(True)
    key = {k: getattr(cfg, k) for k in _PRE_KEYS}
    cfg_path = pre_dir / "pretrain.json"
    if not cfg_path.is_file() or not (pre_dir / "norm.json").is_file():
        raise FileNotFoundError(f"no pretraining in {pre_dir} (run --pretrain-only first)")
    if json.loads(cfg_path.read_text()) != key:
        raise ValueError(f"{cfg_path} was made with another configuration; use another --work-dir")
    norm = lstm.Norm.from_dict(json.loads((pre_dir / "norm.json").read_text()))
    return Pretrained(norm, cfg, pre_dir)


_FOLD_KEYS = (*_PRE_KEYS, "finetune_lr", "epochs")


def _fold_key(cfg: lstm.TrainConfig, pre: Pretrained | None) -> dict:
    return {"pretrained": pre is not None, **{k: getattr(cfg, k) for k in _FOLD_KEYS}}


def train_lstm_fold(
    stations: dict[int, Station],
    fold_year: int,
    rc: RunConfig,
    pre: Pretrained | None,
    progress,
    out_dir: Path | str | None = None,
    seed_list: tuple[int, ...] | list[int] | None = None,
    train_only: bool = False,
    allow_train: bool = True,
) -> tuple[lstm.Run, dict[int, np.ndarray], dict] | None:
    """Fine-tune (or train) the LSTM ensemble without the fold; returns run, residual grids, info.

    With ``out_dir`` (the fold directory) each seed's weights and history are saved there
    (``lstm_seed{k}.pt``, ``lstm_history_seed{k}.json``) and reused when present, so seeds can be trained
    on different machines (``seed_list``, ``train_only``) and assembled later. A saved configuration
    (``lstm_config.json``) that differs from the current one is refused. Without ``allow_train`` a
    missing seed is an error instead of being trained.
    """
    torch = lstm.import_torch()
    basins = [stations[s].basin for s in sorted(stations)]
    cfg = rc.train_config(pre is not None)
    norm = pre.norm if pre else fold_norm(basins, fold_year)
    ds = fold_dataset(basins, norm, fold_year)
    out = Path(out_dir) if out_dir is not None else None
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        key = _fold_key(cfg, pre)
        kp = out / "lstm_config.json"
        if kp.is_file() and json.loads(kp.read_text()) != key:
            raise ValueError(f"{kp} was made with another configuration; use another --work-dir")
        kp.write_text(json.dumps(key, indent=1))
    models, history = [], []
    for seed in cfg.seeds:
        if seed_list is not None and seed not in seed_list:
            continue
        wp = out / f"lstm_seed{seed}.pt" if out else None
        hp = out / f"lstm_history_seed{seed}.json" if out else None
        if wp is not None and wp.is_file() and hp.is_file():
            model = lstm.new_model(cfg)
            model.load_state_dict(torch.load(wp, weights_only=True, map_location="cpu"))
            model.eval()
            h = json.loads(hp.read_text())
            progress(f"fold {fold_year}: seed {seed} loaded from {wp}")
        else:
            if not allow_train:
                raise FileNotFoundError(
                    f"fold {fold_year}: no saved weights for seed {seed} ({wp})"
                )
            model = None
            if pre:
                model = lstm.new_model(cfg)
                model.load_state_dict(pre.state(seed))
            progress(f"fine-tuning seed {seed} (fold {fold_year})")
            model, h = lstm.fit_model(
                ds, cfg, seed, cfg.epochs, cfg.finetune_lr if pre else cfg.lr, ("neuquen",), model,
                progress,
            )  # fmt: skip
            h = {"seed": seed, **h}
            if wp is not None:
                torch.save(model.state_dict(), wp)
                hp.write_text(json.dumps(h))
        models.append(model)
        history.append(h)
    if train_only:
        return None
    run = lstm.Run(config=cfg, norm=norm, models=models, history=history)
    val = lstm.predict_frame(run, ds, "val", groups=("neuquen",))
    grids = {}
    for sid in stations:
        g = val[val["basin_id"] == str(sid)]
        grids[sid] = residual_grid(log_residuals(g["obs"], g["pred"], np.ones(len(g), bool)))
        hd.check_no_leak(g["date"], fold_year, what=f"LSTM validation residuals {sid}")
    info = {
        "pretrained": pre is not None,
        "val_years": val_years(fold_year),
        "n_train_windows": history[0].get("n_train_windows"),
        "best_epochs": [h.get("best_epoch") for h in history],
        "epoch_seconds": float(np.mean([np.mean(h["epoch_seconds"]) for h in history])),
        "labels_train_days": int((ds.labels == 1).sum()),
        "labels_excluded_days": int((ds.labels == 3).sum()),
    }
    return run, grids, info


# --- fold run ---------------------------------------------------------------------------------


def run_fold(
    fold_year: int,
    floods: pd.DataFrame,
    stations: dict[int, Station],
    tables: dict[str, hd.ForecastTable],
    out_dir: Path | str,
    rc: RunConfig,
    pre: Pretrained | None,
    progress: Callable[[str], None] = print,
    allow_train: bool = True,
) -> Path:
    """Fit everything without the fold, forecast every issue day of its floods, save sims + meta."""
    out = Path(out_dir) / f"fold-{fold_year}"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    meta: dict = {"fold_year": int(fold_year), "stations": {}, "leak_checks": []}
    start, end = hd.fold_excluded_range(fold_year)
    meta["excluded_range"] = [f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}"]
    fits: dict[int, dict] = {}
    for sid in sorted(floods["station_id"].unique()):
        st = stations[int(sid)]
        progress(f"GR4J calibration {sid} (fold {fold_year})")
        cal = calibrate_gr4j(st, fold_year, rc.gr4j_seeds, rc.maxiter, rc.popsize)
        q = fold_quantities(st.flow, fold_year, st.dates, st.basin.q, cal["sim_mm"])
        for name, used in q["used"].items():
            hd.check_no_leak(used, fold_year, what=f"{name} {sid}")
            meta["leak_checks"].append(f"{sid}:{name}:ok")
        tr = cal["train"]
        clim = {
            "tmean": doy_climatology(st.dates, st.basin.x[:, 1], tr),
            "tmin": doy_climatology(st.dates, st.basin.x[:, 2], tr),
            "tmax": doy_climatology(st.dates, st.basin.x[:, 3], tr),
        }
        fits[int(sid)] = {"cal": cal, "q": q, "clim": clim}
    run = None
    lstm_grids: dict[int, np.ndarray] = {}
    if rc.use_lstm:
        run, lstm_grids, info = train_lstm_fold(
            stations, fold_year, rc, pre, progress, out_dir=out, allow_train=allow_train
        )
        meta["lstm"] = info
    rows, inputs = [], []
    for fl in floods.itertuples():
        sid, peak = int(fl.station_id), pd.Timestamp(fl.peak_date)
        st, fit = stations[sid], fits[sid]
        table = tables[fl.source]
        pairs = hd.needed_pairs(peak)
        by_issue: dict[pd.Timestamp, list[int]] = {}
        for t, lead in pairs:
            by_issue.setdefault(t, []).append(lead)
        for t, leads in by_issue.items():
            members = table.inputs_for_issue(sid, t)
            n = max(leads)
            if any(lead not in members for lead in range(1, n + 1)):
                raise RuntimeError(
                    f"flood {sid} {peak:%Y-%m-%d}: forecast of {t:%Y-%m-%d} incomplete"
                )
            pm = np.stack([members[lead] for lead in range(1, n + 1)], axis=1)  # (members, leads)
            for lead in range(1, n + 1):
                inputs.append(
                    {"station_id": sid, "issue": t, "lead": lead, "valid": t + pd.Timedelta(days=lead - 1),
                     **{f"p_{m}": float(v) for m, v in zip(hd.MEMBERS, members[lead], strict=True)}}
                )  # fmt: skip
            for tvar in ("clim", "perfect"):
                lf = forcing_for_leads(st, t, n, fit["clim"] if tvar == "clim" else None)
                sims = {"gr4j": forecast_gr4j(st, fit["cal"]["params"], t, pm, lf)}
                if run is not None:
                    sims["lstm"] = forecast_lstm(run.models, run.norm, st, t, pm, lf)
                for model, arr in sims.items():
                    for lead in leads:
                        for mi, mem in enumerate(hd.MEMBERS):
                            rows.append(
                                (sid, int(fl.hydro_year), t, lead, t + pd.Timedelta(days=lead - 1),
                                 mem, model, tvar, float(arr[mi, lead - 1]))
                            )  # fmt: skip
        progress(f"flood {sid} {peak:%Y-%m-%d}: forecasts done ({time.time() - t0:.0f} s)")
    sims_df = pd.DataFrame(
        rows,
        columns=[
            "station_id",
            "hydro_year",
            "issue",
            "lead",
            "valid",
            "member",
            "model",
            "tvar",
            "sim_mm",
        ],
    )
    sims_df.to_parquet(out / "sims.parquet", index=False)
    pd.DataFrame(inputs).to_parquet(out / "inputs.parquet", index=False)
    for sid, fit in fits.items():
        st = stations[sid]
        q = fit["q"]
        fl_rows = floods[floods["station_id"] == sid]
        entry = {
            "area_km2": st.area_km2,
            "thr_main_m3s": q["thr_main_m3s"],
            "thr_p95_m3s": q["thr_p95_m3s"],
            "train_max_m3s": q["train_max_m3s"],
            "pclim_main": [None if not np.isfinite(v) else float(v) for v in q["pclim_main"]],
            "pclim_p95": [None if not np.isfinite(v) else float(v) for v in q["pclim_p95"]],
            "resid": {"gr4j": q["resid_gr4j"].tolist()},
            "gr4j": {"params": dict(zip(hm.Params._fields, map(float, fit["cal"]["params"]), strict=True)),
                     "kge_cal": fit["cal"]["kge_cal"], "seed": fit["cal"]["seed"]},
            "floods": [],
        }  # fmt: skip
        if sid in lstm_grids:
            entry["resid"]["lstm"] = lstm_grids[sid].tolist()
        fdf = st.flow.set_index("date")["q_m3s"]
        for fl in fl_rows.itertuples():
            peak = pd.Timestamp(fl.peak_date)
            days = hd.window_days(peak)
            obs = fdf.reindex(days)
            entry["floods"].append(
                {
                    "hydro_year": int(fl.hydro_year),
                    "peak_date": f"{peak:%Y-%m-%d}",
                    "q_peak_m3s": float(fl.q_peak_m3s),
                    "source": fl.source,
                    "obs_m3s": {f"{d:%Y-%m-%d}": (None if not np.isfinite(v) else float(v)) for d, v in obs.items()},
                }
            )  # fmt: skip
        meta["stations"][str(sid)] = entry
    meta["seconds"] = round(time.time() - t0, 1)
    meta["run_config"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in vars(rc).items()}
    (out / "fold.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    return out


# --- planning ---------------------------------------------------------------------------------


def plan_floods(
    stations: dict[int, Station],
    reforecast_zarr: Path | str,
    ops_dir: Path | str = hd.OPS_DIR,
) -> tuple[pd.DataFrame, dict[str, hd.ForecastTable]]:
    """All annual maxima with ``large``, coverage and ``included``; plus the forecast tables."""
    inits = hd.ops_inits_available(ops_dir)
    frames = []
    for sid, st in stations.items():
        frames.append(hd.station_floods(st.flow, sid, st.dates[-1], inits))
    fl = pd.concat(frames, ignore_index=True)
    fl["included"] = False
    tables: dict[str, hd.ForecastTable] = {}
    cand = fl[fl["large"] & fl["source"].notna()]
    ref = cand[cand["source"] == "reforecast"]
    if len(ref):
        needs = {
            int(sid): [d for p in g["peak_date"] for d in hd.window_days(p)]
            for sid, g in ref.groupby("station_id")
        }
        tables["reforecast"] = hd.ForecastTable(hd.load_reforecast(reforecast_zarr, needs))
    ops = cand[cand["source"] == "operational"]
    if len(ops):
        days = [d for p in ops["peak_date"] for d in hd.window_days(p)]
        tables["operational"] = hd.ForecastTable(hd.read_ops_table(ops_dir, days))
    for i, r in cand.iterrows():
        tab = tables[r["source"]]
        if tab.has_all(int(r["station_id"]), r["peak_date"]):
            fl.loc[i, "included"] = True
        else:
            fl.loc[i, "source"] = None
            fl.loc[i, "reason"] = (
                "pronóstico incompleto (miembros o plazos faltantes en el archivo)"
            )
    return fl.sort_values(["peak_date", "station_id"]).reset_index(drop=True), tables


# --- aggregation ------------------------------------------------------------------------------


def load_fold(path: Path | str) -> tuple[dict, pd.DataFrame]:
    p = Path(path)
    return json.loads((p / "fold.json").read_text()), pd.read_parquet(p / "sims.parquet")


def build_pairs(
    folds: list[tuple[dict, pd.DataFrame]],
    condclim: Callable[[dict, pd.DataFrame], np.ndarray | None] | None = None,
) -> pd.DataFrame:
    """One row per scored pair x model x variant with P, interval, climatology and the outcome."""
    out = []
    for meta, sims in folds:
        for sid_s, ent in meta["stations"].items():
            sid = int(sid_s)
            area = ent["area_km2"]
            to_mm = lstm.M3S_TO_MM_DAY / area
            pclim = {
                k: np.array([np.nan if v is None else v for v in ent[f"pclim_{k}"]])
                for k in ("main", "p95")
            }
            thr = {"main": ent["thr_main_m3s"], "p95": ent["thr_p95_m3s"]}
            obs = {}
            peaks = {}
            for f in ent["floods"]:
                obs[f["hydro_year"]] = {pd.Timestamp(k): v for k, v in f["obs_m3s"].items()}
                peaks[f["hydro_year"]] = (pd.Timestamp(f["peak_date"]), f["q_peak_m3s"])
            s = sims[sims["station_id"] == sid]
            for (hy, issue, lead, model, tvar), g in s.groupby(
                ["hydro_year", "issue", "lead", "model", "tvar"], sort=False
            ):
                resid = np.asarray(ent["resid"][model])
                samples = dress(g.sort_values("member")["sim_mm"].to_numpy(), resid)
                valid = pd.Timestamp(issue) + pd.Timedelta(days=int(lead) - 1)
                o = obs[hy].get(valid)
                peak, qpeak = peaks[hy]
                doy = int(baselines.day_of_year(pd.DatetimeIndex([valid]))[0])
                for variant, (tv, kind) in VARIANTS.items():
                    if tv != tvar:
                        continue
                    t = thr[kind]
                    lo, hi = (v / to_mm for v in interval90(samples))
                    out.append(
                        {
                            "fold": meta["fold_year"], "station_id": sid, "hydro_year": hy,
                            "peak_date": peak, "q_peak_m3s": qpeak,
                            "out_of_range": bool(qpeak > ent["train_max_m3s"]),
                            "issue": pd.Timestamp(issue), "lead": int(lead), "valid": valid,
                            "model": model, "variant": variant, "thr_m3s": t,
                            "p": exceed_probability(samples, t * to_mm),
                            "lo_m3s": lo, "hi_m3s": hi,
                            "p_clim": float(pclim[kind][doy]),
                            "obs_m3s": np.nan if o is None else float(o),
                            "is_peak": valid == peak,
                        }
                    )  # fmt: skip
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["outcome"] = np.where(
        df["obs_m3s"].notna(), (df["obs_m3s"] > df["thr_m3s"]).astype(float), np.nan
    )
    df["p_condclim"] = np.nan
    if condclim is not None:
        for meta, _ in folds:
            m = df["fold"] == meta["fold_year"]
            vals = condclim(meta, df[m])
            if vals is not None:
                df.loc[m, "p_condclim"] = vals
    return df


def lead_metrics(pairs: pd.DataFrame, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Per variant, model and lead: rises, coverage, Brier, BSS vs climatology and vs GR4J, verdicts."""
    res: dict = {}
    for variant in pairs["variant"].unique():
        pv = pairs[(pairs["variant"] == variant) & pairs["outcome"].notna()]
        floods = sorted(pv[["station_id", "hydro_year"]].drop_duplicates().itertuples(index=False))
        fkey = {tuple(f): i for i, f in enumerate(floods)}
        res[variant] = {}
        for model in MODELS:
            pm = pv[pv["model"] == model]
            if pm.empty:
                continue
            leads = {}
            prev_pass = True
            for lead in sorted(pm["lead"].unique()):
                g = pm[pm["lead"] == lead]
                idx = np.array(
                    [fkey[(a, b)] for a, b in zip(g["station_id"], g["hydro_year"], strict=True)]
                )
                nf = len(floods)
                bs_m = np.bincount(idx, weights=(g["p"] - g["outcome"]) ** 2, minlength=nf)
                bs_c = np.bincount(idx, weights=(g["p_clim"] - g["outcome"]) ** 2, minlength=nf)
                bss = bss_bootstrap(bs_m, bs_c, n_boot, seed)
                pk = g[g["is_peak"]]
                n_pk = len(pk)
                rises = int((pk["p"] > pk["p_clim"]).sum())
                inside = int(
                    ((pk["obs_m3s"] >= pk["lo_m3s"]) & (pk["obs_m3s"] <= pk["hi_m3s"])).sum()
                )
                cov_lo, cov_hi = wilson(inside, n_pk)
                entry = {
                    "n_floods": int(n_pk), "n_pairs": len(g),
                    "rises": rises, "rises_frac": rises / n_pk if n_pk else float("nan"),
                    "rises_ci": wilson(rises, n_pk),
                    "inside": inside, "coverage": inside / n_pk if n_pk else float("nan"),
                    "coverage_ci": (cov_lo, cov_hi),
                    "brier": brier(g["p"], g["outcome"]), "brier_clim": brier(g["p_clim"], g["outcome"]),
                    "bss_clim": bss,
                }  # fmt: skip
                ok = bool(
                    np.isfinite(bss["lo"])
                    and bss["lo"] > 0
                    and cov_lo <= 0.90 <= cov_hi
                    and n_pk > 0
                )
                prev_pass = prev_pass and ok
                entry["passes_alone"] = ok
                entry["passes"] = bool(prev_pass)
                leads[int(lead)] = entry
            res[variant][model] = leads
        if "gr4j" in res[variant] and "lstm" in res[variant]:
            for lead, ent in res[variant]["lstm"].items():
                a = pv[(pv["model"] == "lstm") & (pv["lead"] == lead)].sort_values(
                    ["station_id", "hydro_year", "issue"]
                )
                b = pv[(pv["model"] == "gr4j") & (pv["lead"] == lead)].sort_values(
                    ["station_id", "hydro_year", "issue"]
                )
                idx = np.array(
                    [fkey[(x, y)] for x, y in zip(a["station_id"], a["hydro_year"], strict=True)]
                )
                nf = len(floods)
                bs_l = np.bincount(
                    idx, weights=((a["p"] - a["outcome"]) ** 2).to_numpy(), minlength=nf
                )
                bs_g = np.bincount(
                    idx, weights=((b["p"] - b["outcome"]) ** 2).to_numpy(), minlength=nf
                )
                ent["bss_vs_gr4j"] = bss_bootstrap(bs_l, bs_g, n_boot, seed)
        # model shown per lead (criterion 3): the simplest that passes; LSTM only if it beats GR4J
        shown = {}
        for lead in res[variant].get("gr4j", {}):
            g_ok = res[variant]["gr4j"][lead]["passes"]
            l_ent = res[variant].get("lstm", {}).get(lead)
            l_ok = bool(
                l_ent and l_ent["passes"] and l_ent.get("bss_vs_gr4j", {}).get("lo", -1) > 0
            )
            shown[lead] = "GR4J" if g_ok else ("LSTM" if l_ok else "Experimental")
        res[variant]["shown"] = shown
    return res


def flood_lead_table(pairs: pd.DataFrame, variant: str = "main") -> pd.DataFrame:
    """Per flood x lead (valid day = peak): P of each model, climatology, rises, interval, verdicts."""
    pk = pairs[(pairs["variant"] == variant) & pairs["is_peak"]]
    rows = []
    for (sid, hy, lead), g in pk.groupby(["station_id", "hydro_year", "lead"]):
        r = {
            "station_id": int(sid), "hydro_year": int(hy), "lead": int(lead),
            "peak_date": g["peak_date"].iloc[0], "q_peak_m3s": g["q_peak_m3s"].iloc[0],
            "thr_m3s": g["thr_m3s"].iloc[0], "p_clim": g["p_clim"].iloc[0],
            "out_of_range": bool(g["out_of_range"].iloc[0]),
        }  # fmt: skip
        for m in MODELS:
            gm = g[g["model"] == m]
            if gm.empty:
                continue
            x = gm.iloc[0]
            r[f"p_{m}"] = x["p"]
            r[f"lo_{m}"], r[f"hi_{m}"] = x["lo_m3s"], x["hi_m3s"]
            r[f"rises_{m}"] = bool(x["p"] > x["p_clim"])
            r[f"inside_{m}"] = bool(x["lo_m3s"] <= x["obs_m3s"] <= x["hi_m3s"])
            r[f"verdict_{m}"] = V_RISES if r[f"rises_{m}"] else V_NOT
        rows.append(r)
    return pd.DataFrame(rows)


# --- report -----------------------------------------------------------------------------------


def _f(x, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def _ci(d: dict, nd: int = 2) -> str:
    return f"{_f(d['bss'], nd)} [{_f(d['lo'], nd)}; {_f(d['hi'], nd)}]"


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, pd.Timestamp):
        return f"{o:%Y-%m-%d}"
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating | float):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def aggregate(
    floods: pd.DataFrame,
    fold_dirs: list[Path],
    context: dict | None = None,
    n_boot: int = N_BOOT,
    condclim=None,
) -> dict:
    """Pairs, per-lead metrics and per flood x lead table from the saved folds."""
    folds = [load_fold(d) for d in fold_dirs]
    pairs = build_pairs(folds, condclim)
    out = {
        "floods": floods,
        "pairs": pairs,
        "context": context or {},
        "folds": [m["fold_year"] for m, _ in folds],
        "fold_info": {
            m["fold_year"]: {
                k: m.get(k) for k in ("lstm", "seconds", "excluded_range", "run_config")
            }
            for m, _ in folds
        },
    }
    if len(pairs):
        out["metrics"] = lead_metrics(pairs, n_boot)
        out["flood_lead"] = {v: flood_lead_table(pairs, v) for v in VARIANTS}
    return out


def render_report(res: dict) -> str:
    fl: pd.DataFrame = res["floods"]
    pairs: pd.DataFrame = res["pairs"]
    ctx = res["context"]
    inc = fl[fl["included"]]
    done = set(res["folds"])
    scored = inc[inc["hydro_year"].isin(done)]
    out_cov = fl[fl["large"] & ~fl["included"]]
    lines = [
        "# F6.7 — Prueba de caudal alto dejando afuera cada crecida",
        "",
        (
            f"**{NOT_AN_ALERT}** Retrospectivo; los pronósticos de lluvia son reforecast u operativos de GEFS sin "
            "corrección de sesgo. No es el sistema de alerta de nadie: usar los avisos oficiales (SMN, AIC, Defensa Civil)."
        ),
        "",
        "## Lectura",
        "",
        "(pendiente de revisión)",
        "",
    ]
    if "metrics" not in res:
        lines += ["Sin resultados: no hay folds completos.", ""]
        return "\n".join(lines)
    m = res["metrics"]["main"]
    n_fl = len(scored)
    n_years = scored["hydro_year"].nunique()
    shown = res["metrics"]["main"].get("shown", {})
    lines += [
        "## Resultado",
        "",
        (
            f"- Crecidas puntuadas: {n_fl} en {n_years} año(s) hidrológico(s) (criterio 1 pide al menos 20 eventos "
            f"independientes{'; no se alcanzan' if n_years < 20 else ''})."
        ),
        "- Anticipaciones que pasan (BSS contra climatología con IC 95 % por encima de 0, cobertura del "
        "intervalo 90 % compatible con 0,90 y todas las más cortas pasan): "
        + "; ".join(
            f"{name} {sorted(k for k, v in m[key].items() if isinstance(k, int) and v['passes'])}"
            for key, name in (("gr4j", "GR4J"), ("lstm", "LSTM"))
            if key in m
        )
        + ".",
        "- Modelo mostrado por anticipación (criterio 3): "
        + ", ".join(f"{k} d: {v}" for k, v in sorted(shown.items()))
        + ".",
        "",
        "## Datos y fuentes",
        "",
        (
            "- **Caudal:** SNIH (SIPH), Red Hidrológica Nacional, caudal medio diario (consulta del 2026-11-09, F2.1), "
            f"estaciones {', '.join(str(s) for s in sorted(fl['station_id'].unique()))}. El caudal solo se usa para "
            "calibrar, seleccionar crecidas y puntuar: ningún modelo lo recibe como entrada."
        ),
        (
            f"- **Forzante:** ERA5 (Copernicus C3S, CC-BY 4.0) vía ARCO-ERA5, promedio sobre los rectángulos de "
            f"`io/snow.UPSTREAM_BOXES` (cuencas aproximadas, sin verificar), {ctx.get('forcing_period', '1980–2025')}."
        ),
        (
            "- **Lluvia pronosticada, 2000-01-10 a 2019-12-31:** reforecast GEFS v12 de NOAA (`noaa-gefs-retrospective`, "
            "00 UTC, 0,25°, miembros c00 y p01–p04; F5.3). Plazo L = horas (24(L−1), 24L] de la corrida; día válido = emisión + L − 1."
        ),
        (
            "- **Lluvia pronosticada, desde 2020-09-23:** archivo operativo GEFS 0,25° `pgrb2sp25` de `noaa-gefs-pds` "
            "(mismos miembros; 5 pasos de 6 h por día). Primer día disponible comprobado en el listado S3: 2020-09-23. "
            "La versión del modelo del reforecast y la operativa difieren (sin verificar el efecto)."
        ),
        f"- **Preentrenamiento del LSTM:** {ctx.get('pretrain', 'sin información')}",
        "",
        "## Método",
        "",
        (
            "- **Crecidas:** máximos anuales por estación (regla de año completo de F2.2) con pronóstico para todos los "
            "días de emisión entre pico−15 y pico+15; «grande» = máximo anual ≥ mediana de los máximos anuales de la "
            "estación (registro completo; solo selecciona, no entra a ningún modelo)."
        ),
        (
            "- **Partición:** un fold por año hidrológico (abril–marzo) de una crecida; todo lo que se ajusta (parámetros de "
            "GR4J, pesos y normalización del LSTM, cuantiles de residuos, umbrales y climatologías) usa solo fechas fuera "
            "de ese año hidrológico ± 30 días; `check_no_leak` lo verifica en cada fold."
        ),
        (
            "- **Modelos:** GR4J+CemaNeige (una capa) recalibrado por fold (KGE, mejor de 3 semillas) y el LSTM de F2.5 en "
            "modo simulación (64 unidades, 5 semillas, mediana), ajustado sin el fold. Años de validación: los seis primeros "
            "de 2007, 2008, … que no son el fold ni sus vecinos."
        ),
        (
            "- **Pronóstico:** emisión t = corrida 00 UTC del día t; estado con ERA5 hasta t−1; plazo L = 1..10 fuerza el día "
            "t+L−1 con la lluvia de cada miembro (promedio ponderado por coseno de la latitud sobre el rectángulo). "
            "Temperatura de los días de pronóstico: climatología ERA5 por día del año de las fechas de entrenamiento (±7 días). "
            "Sin caudal observado en ningún punto (el SNIH tiene 236 días de rezago, F6.1) y sin corrección de sesgo de lluvia."
        ),
        (
            "- **Umbral:** mediana de los máximos anuales de los años de entrenamiento (proxy del nivel de 2 años), por "
            "estación y fold. Sensibilidad: p95 provisional del caudal diario de entrenamiento."
        ),
        (
            f"- **Probabilidad:** cada miembro simulado se viste con {N_RESID} cuantiles de log((obs+ε)/(sim+ε)) (ε = 0,01 mm/d; "
            "GR4J: días de entrenamiento; LSTM: años de validación); P = fracción de las combinaciones miembro×residuo que "
            "superan el umbral; intervalo 90 % = cuantiles 5–95 % de esa mezcla. Climatología: P(Q > umbral) de los días de "
            "entrenamiento dentro de ±7 días del día del año."
        ),
        (
            f"- **Puntajes:** por anticipación y sobre todas las parejas (emisión, plazo) de la ventana de cada crecida: Brier, "
            f"BSS contra la climatología con IC 95 % por bootstrap de crecidas ({n_boot_label(res)} remuestras, semilla {SEED}); "
            "cobertura con IC de Wilson 95 % contra 0,90."
        ),
        "",
        "## Crecidas",
        "",
        "| Estación | Año hid. | Pico | Caudal pico (m³/s) | Fuente de pronóstico | Umbral (m³/s) | Umbral p95 (m³/s) | Nota |",
        "|---|---|---|---|---|---|---|---|",
    ]
    thr = (
        pairs[pairs["model"] == "gr4j"]
        .groupby(["station_id", "hydro_year", "variant"])["thr_m3s"]
        .first()
    )
    for r in scored.itertuples():
        tm = thr.get((r.station_id, r.hydro_year, "main"), np.nan)
        tp = thr.get((r.station_id, r.hydro_year, "thr_p95"), np.nan)
        oor = bool(
            pairs[(pairs["station_id"] == r.station_id) & (pairs["hydro_year"] == r.hydro_year)][
                "out_of_range"
            ].iloc[0]
        )
        lines.append(
            f"| {r.station_id} | {r.hydro_year} | {r.peak_date:%Y-%m-%d} | {_f(r.q_peak_m3s, 0)} | "
            f"{'reforecast' if r.source == 'reforecast' else 'operativo'} | {_f(tm, 0)} | {_f(tp, 0)} | "
            f"{OUT_OF_RANGE if oor else ''} |"
        )
    lines += ["", "### Crecidas grandes fuera de cobertura", ""]
    if out_cov.empty:
        lines.append("Ninguna.")
    else:
        lines += [
            "| Estación | Año hid. | Pico | Caudal pico (m³/s) | Motivo |",
            "|---|---|---|---|---|",
        ]
        for r in out_cov.itertuples():
            lines.append(
                f"| {r.station_id} | {r.hydro_year} | {r.peak_date:%Y-%m-%d} | {_f(r.q_peak_m3s, 0)} | {r.reason or 'fold sin correr'} |"
            )
    lines += ["", "## Resultado por crecida y anticipación (corrida principal)", ""]
    fl_main = res["flood_lead"]["main"]
    has_l = "p_lstm" in fl_main.columns
    head = "| Estación | Pico | L | P clim | P GR4J | Veredicto GR4J | Pico en IC90 GR4J |"
    sep = "|---|---|---|---|---|---|---|"
    if has_l:
        head += " P LSTM | Veredicto LSTM | Pico en IC90 LSTM |"
        sep += "---|---|---|"
    lines += [head, sep]
    yn = lambda b: "sí" if b else "no"
    for r in fl_main.sort_values(["peak_date", "station_id", "lead"]).itertuples():
        row = (
            f"| {r.station_id} | {r.peak_date:%Y-%m-%d} | {r.lead} | {_f(r.p_clim, 3)} | {_f(r.p_gr4j, 3)} | "
            f"{r.verdict_gr4j} | {yn(r.inside_gr4j)} |"
        )
        if has_l:
            row += f" {_f(r.p_lstm, 3)} | {r.verdict_lstm} | {yn(r.inside_lstm)} |"
        lines.append(row)
    for variant, title in (
        ("main", "Corrida principal"),
        ("thr_p95", "Sensibilidad: umbral p95"),
        ("t_perfect", "Sensibilidad: temperatura perfecta (optimista)"),
    ):
        mv = res["metrics"].get(variant)
        if not mv:
            continue
        lines += ["", f"## Resumen por anticipación — {title}", ""]
        for key, name in (("gr4j", "GR4J"), ("lstm", "LSTM")):
            if key not in mv:
                continue
            lines += [
                f"**{name}**",
                "",
                "| L | Crecidas | Sube | Cobertura IC90 [Wilson 95 %] | Brier | Brier clim | BSS vs clim [IC 95 %] | "
                + ("BSS vs GR4J [IC 95 %] | " if key == "lstm" else "")
                + "Pasa |",
                "|---|---|---|---|---|---|---|" + ("---|" if key == "lstm" else "") + "---|",
            ]
            for lead, e in sorted(mv[key].items()):
                row = (
                    f"| {lead} | {e['n_floods']} | {e['rises']}/{e['n_floods']} | {_f(e['coverage'])} "
                    f"[{_f(e['coverage_ci'][0])}; {_f(e['coverage_ci'][1])}] | {_f(e['brier'], 3)} | "
                    f"{_f(e['brier_clim'], 3)} | {_ci(e['bss_clim'])} | "
                )
                if key == "lstm":
                    row += (_ci(e["bss_vs_gr4j"]) if "bss_vs_gr4j" in e else "—") + " | "
                row += ("pasa" if e["passes"] else "no pasa") + " |"
                lines.append(row)
            lines.append("")
        if "shown" in mv:
            lines.append(
                "Modelo mostrado: "
                + ", ".join(f"{k} d: {v}" for k, v in sorted(mv["shown"].items()))
                + "."
            )
    lines += [
        "",
        "## Cautelas",
        "",
        f"- {NOT_AN_ALERT}",
        "- Retrospectivo: el estado del modelo usa ERA5, que no está disponible en tiempo real (ERA5T tiene unos 5 días de rezago).",
        (
            "- El reforecast (2000–2019) y el pronóstico operativo (desde 2020-09) son versiones distintas de GEFS: la mezcla "
            "de períodos no está calibrada (sin verificar el efecto)."
        ),
        "- Cobertura: sin pronóstico entre 2020-01 y 2020-09-22 (el reforecast termina en 2019-12-31 y `pgrb2sp25` empieza el 2020-09-23).",
        (
            "- Las ventanas se eligen alrededor de crecidas que ocurrieron: no hay períodos tranquilos, así que el BSS es "
            "condicional a una crecida y aprobar es necesario pero no suficiente. Los falsos positivos fuera de esas ventanas no se miden."
        ),
        "- La persistencia no se evalúa: no hay caudal en tiempo real (SNIH, rezago de 236 días).",
        "- Cuencas aproximadas por rectángulos (sin verificar); días de forzante UTC y de caudal locales, sin corregir el desfase.",
        (
            "- Elevación media del LSTM: la `forcing.static.json` publicada no la trae; se tomó la media del DEM de "
            "`reports/02/F2.5-bands.md` (sin verificar)."
        ),
        (
            "- Normalización del LSTM: con preentrenamiento se calcula con las filas de entrenamiento de CAMELS-CL solamente "
            "(para que valga en todos los folds), no con las de Neuquén como en F2.5."
        ),
        (
            "- Solo se muestran probabilidades de superar un umbral, nunca la magnitud del pico; las crecidas por encima del "
            f"máximo de entrenamiento se marcan «{OUT_OF_RANGE}»."
        ),
        (
            "- `p_condclim` (climatología condicional de F6.9) queda vacío: necesita rasgos de eventos de río atmosférico que "
            "una pareja diaria no tiene."
        ),
        "",
    ]
    return "\n".join(lines)


def n_boot_label(res: dict) -> str:
    return str(res.get("context", {}).get("n_boot", N_BOOT))


def write_report(res: dict, out_dir: Path | str = REPORT_DIR) -> tuple[Path, Path]:
    """Write ``F6.7.md`` and ``F6.7.json`` (the ``## Lectura`` section keeps its placeholder)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = out / "F6.7.md"
    md.write_text(render_report(res))
    js = out / "F6.7.json"
    payload = {
        "context": res["context"],
        "folds": res["folds"],
        "fold_info": res["fold_info"],
        "floods": res["floods"].to_dict("records"),
        "metrics": res.get("metrics"),
        "flood_lead": {v: t.to_dict("records") for v, t in res.get("flood_lead", {}).items()},
        "note": NOT_AN_ALERT,
    }
    js.write_text(json.dumps(_jsonable(payload), indent=1, ensure_ascii=False))
    return md, js

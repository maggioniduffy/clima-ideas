"""Daily-streamflow LSTM, pretrained on CAMELS-CL and fine-tuned on the Neuquén stations (F2.5).

Usage (from ``backend/``, needs ``uv sync --group ml``)::

    uv run clima-nqn flow lstm-train --mode sim --run-name sim-default
    uv run clima-nqn flow lstm-train --mode forecast --run-name fc-default

Everything up to the model (basins, splits, normalization, sample windows, uncertainty quantiles) is
plain numpy/pandas and needs no torch; torch is imported lazily by the training and prediction code.

Design choices (assumptions S7-S9 of ``odd/tasks/streamflow-lstm.md``):

* Inputs. Dynamic: ``precip_mm, tmean_c, tmin_c, tmax_c, pet_mm`` (``deg0l`` is not in CAMELS-CL, so it
  is left out); static: ``log(area_km2), elev_mean_m, latitude`` repeated at every step. Neuquén ERA5 and
  CAMELS-CL CR2MET forcing are different products ("forzante distinto"); they share one normalization.
* Target. Flow in mm/d (Neuquén: m3/s x 86.4 / area_km2 with the SNIH area), normalized with the global
  mean and std of the training rows. Output is un-normalized and clipped at 0.
* Loss. Basin-averaged NSE* (Kratzert et al. 2019, HESS 23, 5089): ``(y - yhat)^2 / (sigma_b + 0.1)^2``
  on the normalized target, with ``sigma_b`` the std of the basin's normalized training flow, so a
  small basin counts as much as a large one. Averaged over the valid target steps.
* Mode ``sim``: a window of ``seq_len`` (365) days of forcing; the loss is on the last ``loss_steps`` (30)
  steps, each with at least ``seq_len - loss_steps`` days of context. Evaluation reads the last step of
  the window ending on each day.
* Mode ``forecast``: issue day t, leads 1..7. The window runs from t - seq_len + 1 to t + 7 with the
  forcing of every step (observed ERA5 of the future days: "meteorología observada", not a forecast), a
  flow channel (normalized observed flow up to t, 0 after) and a mask channel (1 where flow is given;
  gaps in the history are 0 with mask 0). The outputs at steps t+1..t+7 are the leads.
* Splits (hydrological years starting in April, ``SPLITS``). Parts are assigned to *target* dates. The
  inputs of a train or validation window never include a test date; test windows may read earlier
  years (train/validation) as context. Nothing is tuned on the test part.
* Normalization (mean/std per dynamic feature, per static feature, flow) comes from the training rows
  of the basins used, never from validation or test rows. It is stored with the model.
* Uncertainty. From the validation period (Neuquén basins), per lead (``sim``: one overall entry
  ``"0"``): the 5 % and 95 % empirical quantiles of ``log((obs + EPS_MM) / (pred + EPS_MM))``; the 90 %
  band is ``(pred + EPS_MM) * exp(q) - EPS_MM``, clipped at 0 (for ``pred >> EPS_MM`` it is
  ``pred * exp(q)``). ``EPS_MM`` = 0.01 mm/d is about 1 % of the typical Neuquén flow.
* Training. Adam, gradient clipping, early stopping on the validation loss, fixed seeds and
  deterministic CPU kernels. An epoch is a capped number of sampled windows (``samples_per_epoch``) so
  pretraining on hundreds of basins takes minutes. Ensemble: one model per seed (each with its own
  pretraining when ``pretrain``); the prediction is the ensemble median.
* Days. Flow days are local (UTC-3) and forcing days are UTC; the offset is not corrected (as in F2.3).
"""

from __future__ import annotations

import copy
import dataclasses
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.io import flow, forcing

DYNAMIC = ["precip_mm", "tmean_c", "tmin_c", "tmax_c", "pet_mm"]
STATIC = ["log_area_km2", "elev_mean_m", "lat"]
FORECAST_CHANNELS = ["flow_norm", "flow_mask"]
HYDRO_YEAR_START_MONTH = 4
EPS_MM = 0.01  # mm/d, floor of the log residual ratio and of the band
SIGMA_EPS = 0.1  # NSE* epsilon (Kratzert et al. 2019)
M3S_TO_MM_DAY = 86.4  # m3/s -> mm/d is x 86.4 / area_km2
PART_NAMES = ["none", "train", "val", "test"]
SPLITS = {
    "default": {"train": (1980, 2006), "val": (2007, 2013), "test": (2014, 2025)},
    "alt": {"test": (1980, 1991), "val": (1992, 1998), "train": (1999, 2025)},
}
DAY_NOTE = "Flow days are local (UTC-3); forcing days are UTC. The offset is not corrected."
TORCH_MISSING = (
    "torch is not installed. The streamflow LSTM needs the optional dependency group: "
    "run `uv sync --group ml` in backend/ (CPU-only wheels)."
)
DEFAULT_RUNS_DIR = flow.OUT_DIR / "lstm"
NEUQUEN_AREA_RATIO = (0.5, 2.0)  # SNIH area vs. forcing box area outside this -> "sin verificar"


class TorchMissing(RuntimeError):
    pass


def import_torch():
    try:
        import torch
    except ImportError as e:
        raise TorchMissing(TORCH_MISSING) from e
    return torch


# --- splits ------------------------------------------------------------------------------------


def hydro_year(dates: pd.DatetimeIndex) -> np.ndarray:
    """Hydrological year (April-March) labelled by the calendar year it starts in."""
    d = pd.DatetimeIndex(dates)
    return np.where(d.month >= HYDRO_YEAR_START_MONTH, d.year, d.year - 1)


def split_labels(dates: pd.DatetimeIndex, split: str) -> np.ndarray:
    """Part of each date (index into ``PART_NAMES``): 0 none, 1 train, 2 val, 3 test."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; valid: {sorted(SPLITS)}")
    hy = hydro_year(dates)
    out = np.zeros(len(hy), dtype=np.int8)
    for part, (a, b) in SPLITS[split].items():
        out[(hy >= a) & (hy <= b)] = PART_NAMES.index(part)
    return out


# --- basins and normalization ------------------------------------------------------------------


@dataclass
class Basin:
    id: str
    dates: pd.DatetimeIndex  # contiguous daily dates
    x: np.ndarray  # (T, 5) dynamic inputs in ``DYNAMIC`` order, raw units
    q: np.ndarray  # (T,) flow in mm/d, NaN where missing
    static: np.ndarray  # (3,) in ``STATIC`` order, raw units
    group: str  # "neuquen" or "camels"


@dataclass
class Norm:
    dyn_mean: np.ndarray
    dyn_std: np.ndarray
    static_mean: np.ndarray
    static_std: np.ndarray
    q_mean: float
    q_std: float

    def to_dict(self) -> dict:
        return {
            "dyn_mean": self.dyn_mean.tolist(),
            "dyn_std": self.dyn_std.tolist(),
            "static_mean": self.static_mean.tolist(),
            "static_std": self.static_std.tolist(),
            "q_mean": float(self.q_mean),
            "q_std": float(self.q_std),
            "dynamic": DYNAMIC,
            "static": STATIC,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Norm:
        return cls(
            np.array(d["dyn_mean"]),
            np.array(d["dyn_std"]),
            np.array(d["static_mean"]),
            np.array(d["static_std"]),
            float(d["q_mean"]),
            float(d["q_std"]),
        )


def _std(a: np.ndarray, axis=None):
    s = np.nanstd(a, axis=axis)
    return np.where(~np.isfinite(s) | (s < 1e-9), 1.0, s)


def compute_norm(basins: list[Basin], split: str) -> Norm:
    """Mean/std of the dynamic inputs and flow over the *training* rows of the basins only."""
    xs, qs = [], []
    for b in basins:
        train = split_labels(b.dates, split) == PART_NAMES.index("train")
        xs.append(b.x[train])
        qs.append(b.q[train])
    x, q = np.concatenate(xs), np.concatenate(qs)
    if not len(x):
        raise ValueError(f"no training rows in split {split!r}")
    st = np.stack([b.static for b in basins])
    return Norm(
        np.nan_to_num(np.nanmean(x, axis=0)),
        np.asarray(_std(x, axis=0)),
        st.mean(axis=0),
        np.asarray(_std(st, axis=0)),
        float(np.nan_to_num(np.nanmean(q))),
        float(_std(q)),
    )


def n_inputs(mode: str) -> int:
    return len(DYNAMIC) + len(STATIC) + (len(FORECAST_CHANNELS) if mode == "forecast" else 0)


def window_len(mode: str, hist: int, n_out: int) -> int:
    """Window length: ``sim`` is ``hist`` steps; ``forecast`` is ``hist`` history days + ``n_out`` leads."""
    return hist + n_out if mode == "forecast" else hist


class Dataset:
    """All basins concatenated; windows are addressed by the global index of their last step."""

    def __init__(self, basins: list[Basin], split: str, norm: Norm):
        self.split, self.norm = split, norm
        self.ids = [b.id for b in basins]
        self.groups = np.array([b.group for b in basins])
        lengths = np.array([len(b.dates) for b in basins])
        self.offsets = np.r_[0, np.cumsum(lengths)[:-1]].astype(np.int64)
        self.basin_of = np.repeat(np.arange(len(basins)), lengths)
        self.dates = np.concatenate([b.dates.to_numpy() for b in basins])
        self.labels = np.concatenate([split_labels(b.dates, split) for b in basins])
        x = np.concatenate([b.x for b in basins])
        self.bad = np.isnan(x).any(axis=1)
        self.X = np.nan_to_num((x - norm.dyn_mean) / norm.dyn_std).astype(np.float32)
        self.qraw = np.concatenate([b.q for b in basins]).astype(np.float64)
        self.Q = ((self.qraw - norm.q_mean) / norm.q_std).astype(np.float32)
        self.S = (
            (np.stack([b.static for b in basins]) - norm.static_mean) / norm.static_std
        ).astype(np.float32)
        train = self.labels == PART_NAMES.index("train")
        self.sigma_b = np.ones(len(basins), dtype=np.float32)
        for i in range(len(basins)):
            qi = self.Q[train & (self.basin_of == i)]
            qi = qi[np.isfinite(qi)]
            if len(qi) > 1 and qi.std() > 1e-6:
                self.sigma_b[i] = qi.std()
        self._cum = {}

    @classmethod
    def from_basins(cls, basins: list[Basin], split: str, norm: Norm) -> Dataset:
        return cls(basins, split, norm)

    def _cumsum(self, name: str, values: np.ndarray) -> np.ndarray:
        if name not in self._cum:
            self._cum[name] = np.r_[0, np.cumsum(values, dtype=np.int64)]
        return self._cum[name]

    def sample_ends(
        self, part: str, mode: str, hist: int, n_out: int, groups: tuple[str, ...] | None = None
    ) -> np.ndarray:
        """Global indices of the last step of every valid window whose targets are all in ``part``.

        Valid: the window starts inside the basin, has complete forcing, the ``n_out`` targets (the last
        steps) are all dated in ``part`` with at least one observed flow, and (train/val) no step of the
        window is a test date.
        """
        length = window_len(mode, hist, n_out)
        e = np.arange(len(self.dates))
        ok = e - length + 1 >= self.offsets[self.basin_of]
        ok &= e >= length - 1
        lo = np.clip(e - length + 1, 0, None)
        tlo = np.clip(e - n_out + 1, 0, None)

        def count(name, values, a):
            c = self._cumsum(name, values)
            return c[e + 1] - c[a]

        ok &= count("bad", self.bad, lo) == 0
        ok &= count(f"is_{part}", self.labels == PART_NAMES.index(part), tlo) == n_out
        ok &= count("q", np.isfinite(self.Q), tlo) >= 1
        if part != "test":
            ok &= count("test", self.labels == PART_NAMES.index("test"), lo) == 0
        if groups is not None:
            ok &= np.isin(self.groups[self.basin_of], list(groups))
        return e[ok]

    def batch(self, ends: np.ndarray, mode: str, hist: int, n_out: int):
        """``(x, y, w)``: inputs (B, L, C), normalized targets (B, n_out) with NaN, NSE* weights (B,)."""
        ends = np.asarray(ends)
        length = window_len(mode, hist, n_out)
        idx = ends[:, None] + np.arange(-length + 1, 1)[None, :]
        basin = self.basin_of[ends]
        parts = [self.X[idx], np.repeat(self.S[basin][:, None, :], length, axis=1)]
        if mode == "forecast":
            q = self.Q[idx]
            q[:, hist:] = np.nan  # the future days: no flow is given
            parts.append(np.nan_to_num(q)[:, :, None])
            parts.append(np.isfinite(q).astype(np.float32)[:, :, None])
        x = np.concatenate(parts, axis=2).astype(np.float32)
        y = self.Q[ends[:, None] + np.arange(-n_out + 1, 1)[None, :]]
        w = 1.0 / (self.sigma_b[basin] + SIGMA_EPS) ** 2
        return x, y, w.astype(np.float32)


def target_frame(ds: Dataset, ends: np.ndarray, mode: str, n_out: int) -> pd.DataFrame:
    """Long table of the targets of the windows: ``basin_id, issue_date, date, lead, obs`` (mm/d).

    ``sim`` has one row per window (``lead`` 0, ``issue_date`` NaT); ``forecast`` has ``n_out`` rows per
    issue day (``lead`` 1..n_out, ``date`` = issue day + lead).
    """
    ends = np.asarray(ends)
    if mode == "sim":
        tgt = ends[:, None]
        lead = np.zeros_like(tgt)
        issue = np.full(len(ends), np.datetime64("NaT", "ns"))
    else:
        tgt = ends[:, None] - n_out + np.arange(1, n_out + 1)[None, :]
        lead = np.tile(np.arange(1, n_out + 1), (len(ends), 1))
        issue = ds.dates[ends - n_out]
    k = tgt.shape[1]
    return pd.DataFrame(
        {
            "basin_id": np.repeat(np.array(ds.ids)[ds.basin_of[ends]], k),
            "issue_date": np.repeat(issue, k),
            "date": ds.dates[tgt.ravel()],
            "lead": lead.ravel(),
            "obs": ds.qraw[tgt.ravel()],
        }
    )


# --- data builders -----------------------------------------------------------------------------


def neuquen_basins(
    forcing_path: Path | str, flow_dir: Path | str, stations: list[int] | None = None
) -> tuple[list[Basin], dict]:
    """Neuquén basins from the F2.5 forcing Parquet and the F2.1 flow files (flow in mm/d).

    Returns ``(basins, info)``; ``info`` has, per station, the area used, the forcing box area and the
    flags. Raises ``ValueError`` if the forcing has no temperature (the t2m run was not merged yet).
    """
    forcing_path, flow_dir = Path(forcing_path), Path(flow_dir)
    f = forcing.read_forcing(forcing_path)
    static = json.loads(forcing_path.with_suffix(forcing.STATIC_SUFFIX).read_text())["basins"]
    meta = {s["id"]: s for s in json.loads((flow_dir / "stations.json").read_text())["stations"]}
    chosen = sorted(stations) if stations else sorted(f["station_id"].unique().tolist())
    basins, info = [], {}
    for sid in chosen:
        g = f[f["station_id"] == sid].sort_values("date")
        if g.empty:
            raise ValueError(f"station {sid}: not in the forcing file {forcing_path}")
        if g["tmean_c"].isna().all() or g["pet_mm"].isna().all():
            raise ValueError(
                f"station {sid}: the forcing has no temperature or PET (NaN); rerun "
                "`clima-nqn flow forcing --t2m-dir ...` once the t2m stores exist"
            )
        while g["precip_mm"].isna().iloc[-1]:  # trailing days without a precipitation value
            g = g.iloc[:-1]
        dates = pd.DatetimeIndex(g["date"])
        s_static = static[str(sid)]
        m = meta.get(sid, {})
        box_area = float(s_static["area_km2"])
        area = flow.area_or_none(m.get("area_km2"))
        notes = []
        if area is None:
            area = box_area
            notes.append("area from the forcing box (sin verificar)")
        elif not NEUQUEN_AREA_RATIO[0] <= area / box_area <= NEUQUEN_AREA_RATIO[1]:
            notes.append("SNIH area differs from the forcing box area (sin verificar)")
        notes.append("elevation is the mean of the approximate upstream box (sin verificar)")
        qdf = flow.read_flow(flow_dir / f"{sid}.parquet").set_index("date")
        q_m3s = qdf["q_m3s"].reindex(dates).to_numpy(dtype=float)
        lat = float(m.get("lat", s_static["centroid_lat"]))
        basins.append(
            Basin(
                id=str(sid),
                dates=dates,
                x=g[DYNAMIC].to_numpy(dtype=float),
                q=q_m3s * M3S_TO_MM_DAY / area,
                static=np.array([np.log(area), float(s_static["elev_mean_m"]), lat]),
                group="neuquen",
            )
        )
        info[str(sid)] = {
            "area_km2": area,
            "box_area_km2": box_area,
            "elev_mean_m": float(s_static["elev_mean_m"]),
            "lat": lat,
            "flow_period": f"{qdf.index.min():%Y-%m-%d} to {qdf.index.max():%Y-%m-%d}",
            "forcing_period": f"{dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}",
            "notes": notes,
        }
    return basins, info


def camels_basins(df: pd.DataFrame, attrs: pd.DataFrame, ids: list[str]) -> list[Basin]:
    """CAMELS-CL basins (tidy table of ``io.camels_cl``) on a contiguous daily axis."""
    out = []
    grouped = df[df["gauge_id"].isin(ids)].groupby("gauge_id")
    for gid in ids:
        g = grouped.get_group(gid).sort_values("date")
        full = pd.date_range(g["date"].min(), g["date"].max(), freq="D")
        g = g.set_index("date").reindex(full)
        a = attrs.loc[gid]
        out.append(
            Basin(
                id=str(gid),
                dates=full,
                x=g[DYNAMIC].to_numpy(dtype=float),
                q=g["q_mm"].to_numpy(dtype=float),
                static=np.array(
                    [np.log(float(a["area_km2"])), float(a["elev_mean_m"]), float(a["lat"])]
                ),
                group="camels",
            )
        )
    return out


# --- uncertainty -------------------------------------------------------------------------------


def fit_quantiles(frame: pd.DataFrame) -> dict:
    """5 % / 95 % quantiles of ``log((obs + EPS) / (pred + EPS))`` per lead (key = lead as string)."""
    out = {}
    for lead, g in frame.groupby("lead"):
        ok = np.isfinite(g["obs"]) & np.isfinite(g["pred"])
        res = np.log((g["obs"][ok] + EPS_MM) / (g["pred"][ok] + EPS_MM))
        if len(res) < 2:
            continue
        out[str(int(lead))] = {
            "q05": float(np.quantile(res, 0.05)),
            "q95": float(np.quantile(res, 0.95)),
            "n": len(res),
        }
    return out


def band(pred: np.ndarray, q: dict) -> tuple[np.ndarray, np.ndarray]:
    """90 % band ``(pred + EPS) * exp(q) - EPS`` for the lead's quantiles, never below 0."""
    pred = np.asarray(pred, dtype=float)
    lo = (pred + EPS_MM) * np.exp(q["q05"]) - EPS_MM
    hi = (pred + EPS_MM) * np.exp(q["q95"]) - EPS_MM
    return np.clip(lo, 0.0, None), np.clip(hi, 0.0, None)


# --- training ----------------------------------------------------------------------------------


@dataclass
class TrainConfig:
    mode: str = "sim"  # "sim" | "forecast"
    split: str = "default"  # "default" | "alt"
    hidden: int = 64
    dropout: float = 0.4
    seq_len: int = 365  # sim: window length; forecast: history days before the 7 leads
    loss_steps: int = 30  # sim: last steps with loss
    lead: int = 7  # forecast: leads 1..lead
    batch_size: int = 256
    samples_per_epoch: int = 20000
    val_samples: int = 4000
    epochs: int = 30  # main stage: fine-tuning (pretrain) or the whole training (no pretrain)
    pretrain_epochs: int = 10
    lr: float = 1e-3  # pretraining, or the whole training without pretrain
    finetune_lr: float = 3e-4
    patience: int = 4
    clip: float = 1.0
    seeds: tuple = (0, 1, 2, 3, 4)
    pretrain: bool = True

    @property
    def n_out(self) -> int:
        return self.lead if self.mode == "forecast" else self.loss_steps

    @property
    def eval_n_out(self) -> int:
        return self.lead if self.mode == "forecast" else 1


@dataclass
class Run:
    config: TrainConfig
    norm: Norm
    models: list = field(default_factory=list)
    quantiles: dict = field(default_factory=dict)
    info: dict = field(default_factory=dict)
    history: list = field(default_factory=list)


@lru_cache(maxsize=1)
def _model_class():
    torch = import_torch()
    nn = torch.nn

    class StreamLSTM(nn.Module):
        def __init__(self, n_in: int, hidden: int, dropout: float):
            super().__init__()
            self.lstm = nn.LSTM(n_in, hidden, batch_first=True)
            self.drop = nn.Dropout(dropout)
            self.head = nn.Linear(hidden, 1)
            with (
                torch.no_grad()
            ):  # forget-gate bias 3: long memory from the start (Kratzert et al.)
                self.lstm.bias_hh_l0[hidden : 2 * hidden] = 3.0

        def forward(self, x, n_out: int):
            h, _ = self.lstm(x)
            return self.head(self.drop(h[:, -n_out:])).squeeze(-1)

    return StreamLSTM


def new_model(cfg: TrainConfig):
    return _model_class()(n_inputs(cfg.mode), cfg.hidden, cfg.dropout)


def _seed_all(seed: int) -> None:
    torch = import_torch()
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


def _loss(torch, pred, y, w):
    ok = ~torch.isnan(y)
    err = torch.where(ok, (pred - torch.nan_to_num(y)) ** 2, torch.zeros_like(pred))
    return (err * w[:, None]).sum() / ok.sum().clamp(min=1)


def _eval_loss(model, ds: Dataset, cfg: TrainConfig, ends: np.ndarray) -> float:
    torch = import_torch()
    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for i in range(0, len(ends), 512):
            x, y, w = ds.batch(ends[i : i + 512], cfg.mode, cfg.seq_len, cfg.n_out)
            y_t = torch.from_numpy(y)
            p = model(torch.from_numpy(x), cfg.n_out)
            n = int((~torch.isnan(y_t)).sum())
            total += float(_loss(torch, p, y_t, torch.from_numpy(w))) * n
            count += n
    return total / max(count, 1)


def fit_model(
    ds: Dataset,
    cfg: TrainConfig,
    seed: int,
    epochs: int,
    lr: float,
    groups: tuple[str, ...] | None = None,
    model=None,
    progress: Callable[[str], None] | None = None,
):
    """Train (or continue training) one LSTM; returns ``(model, history)``.

    ``history`` has ``train_loss``, ``val_loss`` (empty without validation windows),
    ``epoch_seconds``, ``best_epoch`` and the window counts. The best-validation weights are restored.
    """
    torch = import_torch()
    _seed_all(seed)
    rng = np.random.default_rng(seed)
    if model is None:
        model = new_model(cfg)
    train_ends = ds.sample_ends("train", cfg.mode, cfg.seq_len, cfg.n_out, groups)
    if not len(train_ends):
        raise ValueError("no training windows (check the split, the data period and the groups)")
    val_ends = ds.sample_ends("val", cfg.mode, cfg.seq_len, cfg.n_out, groups)
    if len(val_ends) > cfg.val_samples:
        val_ends = val_ends[np.linspace(0, len(val_ends) - 1, cfg.val_samples).astype(int)]
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    hist = {
        "train_loss": [],
        "val_loss": [],
        "epoch_seconds": [],
        "n_train_windows": len(train_ends),
        "n_val_windows": len(val_ends),
    }
    best, best_state, bad = np.inf, None, 0
    for epoch in range(epochs):
        t0 = time.perf_counter()
        model.train()
        n = min(cfg.samples_per_epoch, len(train_ends))
        order = rng.choice(train_ends, size=n, replace=False)
        losses = []
        for i in range(0, n, cfg.batch_size):
            x, y, w = ds.batch(order[i : i + cfg.batch_size], cfg.mode, cfg.seq_len, cfg.n_out)
            loss = _loss(
                torch,
                model(torch.from_numpy(x), cfg.n_out),
                torch.from_numpy(y),
                torch.from_numpy(w),
            )
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.clip)
            opt.step()
            losses.append(float(loss.detach()))
        hist["train_loss"].append(float(np.mean(losses)))
        score = hist["train_loss"][-1]
        if len(val_ends):
            hist["val_loss"].append(_eval_loss(model, ds, cfg, val_ends))
            score = hist["val_loss"][-1]
        hist["epoch_seconds"].append(time.perf_counter() - t0)
        if score < best:
            best, bad, hist["best_epoch"] = score, 0, epoch
            best_state = copy.deepcopy(model.state_dict())
        else:
            bad += 1
        if progress:
            val = f" val {hist['val_loss'][-1]:.4f}" if hist["val_loss"] else ""
            progress(
                f"  epoch {epoch + 1}/{epochs}: train {hist['train_loss'][-1]:.4f}{val} "
                f"({hist['epoch_seconds'][-1]:.1f} s)"
            )
        if len(val_ends) and bad >= cfg.patience:
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model, hist


def predict(run: Run, ds: Dataset, ends: np.ndarray, n_out: int | None = None) -> np.ndarray:
    """Per-seed predictions in mm/d, shape ``(seeds, windows, n_out)``, clipped at 0."""
    torch = import_torch()
    cfg = run.config
    n_out = cfg.eval_n_out if n_out is None else n_out
    ends = np.asarray(ends)
    out = np.zeros((len(run.models), len(ends), n_out), dtype=np.float64)
    with torch.no_grad():
        for i in range(0, len(ends), 512):
            x, _, _ = ds.batch(ends[i : i + 512], cfg.mode, cfg.seq_len, n_out)
            xt = torch.from_numpy(x)
            for s, model in enumerate(run.models):
                model.eval()
                out[s, i : i + 512] = model(xt, n_out).numpy()
    return np.clip(out * run.norm.q_std + run.norm.q_mean, 0.0, None)


def ensemble_median(preds: np.ndarray) -> np.ndarray:
    """Median over the seed axis."""
    return np.median(preds, axis=0)


def predict_frame(
    run: Run,
    ds: Dataset,
    part: str,
    groups: tuple[str, ...] | None = None,
    max_samples: int | None = None,
) -> pd.DataFrame:
    """Target table of a part (see :func:`target_frame`) plus ``pred`` (ensemble median, mm/d)."""
    cfg = run.config
    n_out = cfg.eval_n_out
    ends = ds.sample_ends(part, cfg.mode, cfg.seq_len, n_out, groups)
    if max_samples is not None and len(ends) > max_samples:
        ends = ends[np.linspace(0, len(ends) - 1, max_samples).astype(int)]
    frame = target_frame(ds, ends, cfg.mode, n_out)
    frame["pred"] = ensemble_median(predict(run, ds, ends, n_out)).ravel() if len(ends) else []
    return frame


def train_run(
    neuquen: list[Basin],
    camels: list[Basin] | None,
    cfg: TrainConfig,
    info: dict | None = None,
    progress: Callable[[str], None] = lambda s: None,
) -> Run:
    """Train the ensemble (pretraining on ``camels`` when ``cfg.pretrain``), then fit the quantiles."""
    import_torch()
    if cfg.mode not in ("sim", "forecast"):
        raise ValueError(f"unknown mode {cfg.mode!r}; valid: sim, forecast")
    use_pre = bool(cfg.pretrain and camels)
    if cfg.pretrain and not camels:
        raise ValueError("pretrain requested but there are no CAMELS-CL basins")
    basins = (camels if use_pre else []) + neuquen
    norm = compute_norm(basins, cfg.split)
    ds = Dataset.from_basins(basins, cfg.split, norm)
    run = Run(config=cfg, norm=norm, info=dict(info or {}))
    run.info["pretrain"] = {
        "used": use_pre,
        "n_basins": len(camels) if use_pre else 0,
        "source": "CAMELS-CL (PANGAEA, DOI 10.1594/PANGAEA.894885, CC-BY-4.0)" if use_pre else None,
        "basin_ids": [b.id for b in camels] if use_pre else [],
    }
    run.info["neuquen_basins"] = [b.id for b in neuquen]
    for seed in cfg.seeds:
        progress(f"seed {seed}")
        h = {"seed": seed}
        model = None
        if use_pre:
            progress(f" pretraining on {len(camels)} CAMELS-CL basins")
            model, h["pretrain"] = fit_model(
                ds, cfg, seed, cfg.pretrain_epochs, cfg.lr, ("camels",), progress=progress
            )
            progress(" fine-tuning on Neuquén")
            model, h["finetune"] = fit_model(
                ds, cfg, seed, cfg.epochs, cfg.finetune_lr, ("neuquen",), model, progress
            )
        else:
            model, h["train"] = fit_model(
                ds, cfg, seed, cfg.epochs, cfg.lr, ("neuquen",), progress=progress
            )
        run.models.append(model)
        run.history.append(h)
    val = predict_frame(run, ds, "val", groups=("neuquen",))
    run.quantiles = fit_quantiles(val) if len(val) else {}
    return run


# --- persistence -------------------------------------------------------------------------------


def config_json(run: Run) -> dict:
    cfg = dataclasses.asdict(run.config)
    cfg["seeds"] = list(run.config.seeds)
    return {
        **cfg,
        "inputs": {
            "dynamic": DYNAMIC,
            "static": STATIC,
            "forecast_channels": FORECAST_CHANNELS if run.config.mode == "forecast" else [],
            "target": "flow in mm/d, normalized with the training-row mean and std",
        },
        "splits": {k: {p: list(v) for p, v in s.items()} for k, s in SPLITS.items()},
        "hydro_year_start_month": HYDRO_YEAR_START_MONTH,
        "eps_mm": EPS_MM,
        "day_note": DAY_NOTE,
        "info": run.info,
    }


def save_run(run: Run, out_dir: Path | str) -> Path:
    """Write weights per seed, normalization, quantiles, history and config (small files only)."""
    torch = import_torch()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for seed, model in zip(run.config.seeds, run.models, strict=True):
        torch.save(model.state_dict(), out / f"model_seed{seed}.pt")
    (out / "norm.json").write_text(json.dumps(run.norm.to_dict(), indent=2))
    (out / "quantiles.json").write_text(json.dumps(run.quantiles, indent=2))
    (out / "history.json").write_text(json.dumps(run.history, indent=2))
    (out / "config.json").write_text(json.dumps(config_json(run), indent=2, ensure_ascii=False))
    return out


def load_run(run_dir: Path | str) -> Run:
    torch = import_torch()
    d = Path(run_dir)
    if not (d / "config.json").is_file():
        raise FileNotFoundError(f"no config.json in {d} (is it a run directory?)")
    raw = json.loads((d / "config.json").read_text())
    fields = {f.name for f in dataclasses.fields(TrainConfig)}
    cfg = TrainConfig(**{k: v for k, v in raw.items() if k in fields})
    cfg.seeds = tuple(cfg.seeds)
    run = Run(
        config=cfg,
        norm=Norm.from_dict(json.loads((d / "norm.json").read_text())),
        quantiles=json.loads((d / "quantiles.json").read_text()),
        info=raw.get("info", {}),
    )
    if (d / "history.json").is_file():
        run.history = json.loads((d / "history.json").read_text())
    for seed in cfg.seeds:
        model = new_model(cfg)
        model.load_state_dict(torch.load(d / f"model_seed{seed}.pt", weights_only=True))
        model.eval()
        run.models.append(model)
    return run

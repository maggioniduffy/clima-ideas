"""Targets and features at issue for the seasonal model (F6.2).

Inputs (``data/seasonal/inputs/``, copied from the data branches, see ``report.py`` for sources):
``forcing.parquet`` (F2.5: daily ERA5 box precipitation), ``events.parquet`` (F1.3 AR catalog, period
1980-01-01/2025-12-31), ``flow<station>.parquet`` (F2.5 daily SNIH flow), ``oni.parquet`` (NOAA CPC ONI,
revised series) and ``../state.parquet`` (``fetch.py``).

Every feature carries ``available_on``; ``assert_available`` rejects any feature available after the
issue date. Rules, all relative to the issue date I (the 1st of a month, 00 UTC):

- state (sd, swvl1-3 box means): sampled at 00 UTC of I-5 d (ERA5T latency), ``available_on`` = that hour.
- rain30 / rain90: box precipitation over the 30 / 90 days ending with day I-6 (the daily total of day D
  ends at D+1 00:00, so the last day fully available at I-5 d 00 UTC is I-6); ``available_on`` = I-5 d.
- target-month sin/cos and lead: known at issue.
- last monthly flow (sensitivity only): mean of month M-1 (valid if >= 25 days), ``available_on`` = I.
  Operationally SNIH has a ~236-day lag (F6.1), so this feature is NOT usable at issue.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.stages.seasonal import folds
from clima_nqn.stages.seasonal.fetch import DATA_DIR, LATENCY_DAYS

INPUT_DIR = DATA_DIR / "inputs"
BOXES = (12004, 12010, 12012)
STATE_VARS = ("sd", "swvl1", "swvl2", "swvl3")
LEADS = (1, 2, 3, 4, 5, 6)
FIRST_ISSUE = pd.Timestamp("1980-05-01")  # first issue with a full 90-day rain window
LAST_ISSUE = pd.Timestamp("2025-12-01")  # last month of the AR and rain inputs
AR_FIRST, AR_LAST = pd.Timestamp("1980-01-01"), pd.Timestamp("2025-12-01")  # catalog full months
MIN_FLOW_DAYS = 25
ONI_LAG_MONTHS = 3  # ONI used at issue I (month M): the season centred on M-3 (ending M-2)

# target -> (kind, station/box used for rain features and flow)
TARGETS: dict[str, dict] = {
    "rain": {"kind": "rain", "box": 12004},
    "ar": {"kind": "ar", "box": 12004},
    "flow12004": {"kind": "flow", "box": 12004, "station": 12004},
    "flow12010": {"kind": "flow", "box": 12010, "station": 12010},
    "rain12010": {"kind": "rain", "box": 12010},  # sensitivity: other rain box
}
MAIN_TARGETS = ("rain", "ar", "flow12004", "flow12010")
SENSITIVITY_TARGETS = ("rain12010",)

STATE_COLS = [f"{v}_{b}" for b in BOXES for v in STATE_VARS]
ANOM_COLS = [*STATE_COLS, "rain30", "rain90", "flow_last"]  # standardized per issue month
RAW_COLS = ["lead", "tm_sin", "tm_cos"]
FEATURE_SETS = {
    "S": [*STATE_COLS, "lead"],
    "SR": [*STATE_COLS, "rain30", "rain90", "lead"],
    "SRM": [*STATE_COLS, "rain30", "rain90", "lead", "tm_sin", "tm_cos"],
    "SRMF": [*STATE_COLS, "rain30", "rain90", "lead", "tm_sin", "tm_cos", "flow_last"],
}
SELECTABLE_SETS = ("S", "SR", "SRM")  # SRMF only as the sensitivity with recent flow


@dataclass
class Inputs:
    rain_daily: dict[int, pd.Series]
    ar_month: pd.Series
    flow_month: dict[int, pd.Series]
    oni: pd.DataFrame  # date (centre month), oni, phase
    state: pd.DataFrame
    hashes: dict[str, str] = field(default_factory=dict)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def monthly_from_daily(daily: pd.Series, how: str = "sum", min_days: int | None = None) -> pd.Series:
    """Monthly sum/mean; a month needs ``min_days`` valid days (default: all days of the month)."""
    g = daily.groupby(daily.index.to_period("M"))
    agg = getattr(g, how)()
    n = g.count()
    dim = pd.Series(agg.index.days_in_month, index=agg.index)
    need = dim if min_days is None else min_days
    agg = agg.where(n >= need)
    agg.index = agg.index.to_timestamp()
    return agg


def ar_monthly(events: pd.DataFrame, first=AR_FIRST, last=AR_LAST) -> pd.Series:
    """AR events per calendar month of ``start`` (UTC), zeros included, only the months covered."""
    months = pd.date_range(first, last, freq="MS")
    cnt = events["start"].dt.to_period("M").dt.to_timestamp().value_counts()
    return cnt.reindex(months, fill_value=0).astype(float)


def load_inputs(input_dir: Path = INPUT_DIR, state_path: Path | None = None) -> Inputs:
    input_dir = Path(input_dir)
    state_path = state_path or (input_dir.parent / "state.parquet")
    forcing = pd.read_parquet(input_dir / "forcing.parquet")
    rain = {
        b: forcing[forcing.station_id == b].set_index("date")["precip_mm"].sort_index()
        for b in (12004, 12010)
    }
    events = pd.read_parquet(input_dir / "events.parquet")
    flow = {}
    for s in (12004, 12010):
        q = pd.read_parquet(input_dir / f"flow{s}.parquet").set_index("date")["q_m3s"].sort_index()
        flow[s] = monthly_from_daily(q, "mean", MIN_FLOW_DAYS)
    oni = pd.read_parquet(input_dir / "oni.parquet")
    state = pd.read_parquet(state_path)
    hashes = {
        p.name: _sha(p)
        for p in [*(input_dir / n for n in ("forcing.parquet", "events.parquet", "oni.parquet")),
                  *input_dir.glob("flow*.parquet"), state_path]
    }  # fmt: skip
    return Inputs(rain, ar_monthly(events), flow, oni, state, hashes)


def target_series(inp: Inputs, target: str) -> pd.Series:
    """Monthly value of the target (index = month start)."""
    spec = TARGETS[target]
    if spec["kind"] == "rain":
        return monthly_from_daily(inp.rain_daily[spec["box"]], "sum")
    if spec["kind"] == "ar":
        return inp.ar_month
    return inp.flow_month[spec["station"]]


def persistence_months(kind: str) -> int:
    """Months back from the issue month of the most recent fully available month.

    Rain and AR derive from ERA5T with a ~5-day latency, so month M-1 is incomplete at issue (its last 5
    days are missing): the last full month is M-2. Flow: M-1 (retrospective; operationally SNIH lags ~236 d).
    """
    return 1 if kind == "flow" else 2


def oni_at_issue(oni: pd.DataFrame, issue: pd.Timestamp) -> tuple[float, str]:
    """ONI (revised series) of the season centred ``ONI_LAG_MONTHS`` months before the issue month."""
    d = (issue.to_period("M") - ONI_LAG_MONTHS).to_timestamp()
    row = oni[oni["date"] == d]
    if row.empty:
        return np.nan, ""
    return float(row["oni"].iloc[0]), str(row["phase"].iloc[0])


def hydro_phase(oni: pd.DataFrame, year: int) -> str:
    """ENSO phase of hydrological year ``year`` (Apr year - Mar year+1) from ONI DJF (centre January)."""
    row = oni[oni["date"] == pd.Timestamp(year + 1, 1, 1)]
    return str(row["phase"].iloc[0]) if len(row) else ""


def assert_available(avail: pd.DataFrame, issue) -> None:
    """Reject any feature with ``available_on`` after the issue date of its row."""
    issue = pd.DatetimeIndex(issue)
    late = avail.apply(lambda c: pd.DatetimeIndex(c).values > issue.values)
    if bool(np.asarray(late).any()):
        cols = [c for c in avail.columns if bool(np.asarray(late[c]).any())]
        raise AssertionError(f"features available after the issue date: {cols}")


@dataclass
class Samples:
    target: str
    meta: pd.DataFrame  # issue, lead, target_month, y, persist_val, persist_month, oni, phase, hy
    X: pd.DataFrame
    avail: pd.DataFrame
    series: pd.Series  # monthly target series
    kind: str

    def __len__(self) -> int:
        return len(self.meta)


def _window_sum(daily: pd.Series, issue: pd.Timestamp, days: int) -> float:
    last = issue - pd.Timedelta(days=LATENCY_DAYS + 1)  # day I-6: its total ends at I-5 d 00 UTC
    w = daily.reindex(pd.date_range(last - pd.Timedelta(days=days - 1), last))
    return float(w.sum()) if w.notna().all() else np.nan


def build_samples(inp: Inputs, target: str, leads=LEADS) -> Samples:
    spec = TARGETS[target]
    series = target_series(inp, target)
    box = spec["box"]
    flow_station = spec.get("station", 12004)
    st = inp.state.pivot(index="issue_date", columns="box", values=list(STATE_VARS))
    st.columns = [f"{v}_{b}" for v, b in st.columns]
    st_av = inp.state.drop_duplicates("issue_date").set_index("issue_date")["available_on"]
    issues = [d for d in pd.date_range(FIRST_ISSUE, LAST_ISSUE, freq="MS") if d in st.index]
    pm = persistence_months(spec["kind"])
    rows, feats, avs = [], [], []
    for d in issues:
        av_state = st_av[d]
        r30 = _window_sum(inp.rain_daily[box], d, 30)
        r90 = _window_sum(inp.rain_daily[box], d, 90)
        pmonth = (d.to_period("M") - pm).to_timestamp()
        pval = series.get(pmonth, np.nan)
        fl = inp.flow_month[flow_station].get((d.to_period("M") - 1).to_timestamp(), np.nan)
        oni_v, phase = oni_at_issue(inp.oni, d)
        for k in leads:
            tm = (d.to_period("M") + k - 1).to_timestamp()
            y = series.get(tm, np.nan)
            rows.append(
                {"issue": d, "lead": k, "target_month": tm, "y": y, "persist_val": pval,
                 "persist_month": pmonth, "oni": oni_v, "phase": phase}
            )  # fmt: skip
            f = {c: st.loc[d, c] for c in STATE_COLS}
            f.update(rain30=r30, rain90=r90, flow_last=fl, lead=float(k),
                     tm_sin=np.sin(2 * np.pi * tm.month / 12), tm_cos=np.cos(2 * np.pi * tm.month / 12))  # fmt: skip
            a = {c: av_state for c in STATE_COLS}
            a.update(rain30=av_state, rain90=av_state, flow_last=d, lead=d, tm_sin=d, tm_cos=d)
            feats.append(f)
            avs.append(a)
    meta = pd.DataFrame(rows)
    X = pd.DataFrame(feats)[[*STATE_COLS, "rain30", "rain90", "flow_last", *RAW_COLS]]
    avail = pd.DataFrame(avs)[X.columns]
    ok = meta["y"].notna() & X[[*STATE_COLS, "rain30", "rain90"]].notna().all(axis=1)
    meta, X, avail = (t[ok.values].reset_index(drop=True) for t in (meta, X, avail))
    assert_available(avail, meta["issue"])
    meta["hy"] = folds.hydro_year(meta["issue"])
    return Samples(target, meta, X, avail, series, spec["kind"])

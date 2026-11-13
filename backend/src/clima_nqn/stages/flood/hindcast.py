"""Retrospective flood-card forecasts of the forecast-mode LSTM for past events (F2.6).

Usage (from ``backend/``, needs ``uv sync --group ml``, after ``flow lstm-train --mode forecast``)::

    uv run clima-nqn flow lstm-hindcast --run-name fc-default

Per station, the events are the annual-maximum floods (``extremes.annual_maxima``, the F2.2 rule) whose
peak falls in the test years of the run's split; the ``TOP_EVENTS`` largest by peak flow, plus the forced
events of ``FORCED_EVENTS`` when they are among those floods. For each event the model is issued on the
``ISSUES`` days from ``peak - 7`` to the peak, each with leads 1-7: ensemble median and the 90 % band of
the run's stored validation quantiles (``lstm.band``), in m3/s. The observed series covers
``peak - 14 .. peak + 7`` and persistence is the flow observed on the issue day, held for every lead.

The forcing of the lead days is ERA5 *observed* meteorology: this is a retrospective hindcast, not an
operational forecast, and the file says so (``meta.caveat``). Output: ``events/<station_id>.json`` of the
``flood-stations`` layer (strict JSON, ``null`` for gaps), registered in the manifest and flagged with
``has_events`` in the station detail (``layers.flood_stations.attach_events``).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.io import flow
from clima_nqn.layers import flood_stations
from clima_nqn.stages.flood import extremes, lstm

TOP_EVENTS = 3
ISSUES = 8  # issue days peak-7 .. peak
LEADS = 7
OBS_BEFORE, OBS_AFTER = 14, 7  # observed series: peak - 14 .. peak + 7
FORCED_EVENTS = {"12004": "2023-06-26"}  # always shown when it is a test-year annual maximum
FORCING_NOTE = "ERA5 observada, no pronóstico"
CAVEAT = (
    "Pronóstico retrospectivo con meteorología observada (ERA5), no pronóstico operativo. "
    "Experimental, no es una alerta."
)
PRETRAIN_NOTE = "CAMELS-CL (PANGAEA), forzante CR2MET"
AREA_NOTES = {"12012": "área SNIH igual a la de Chos Malal, sin verificar"}
EVENTS_DIR = flood_stations.EVENTS_DIR


def _num(x, nd: int = 1):
    """Rounded float, ``None`` for NaN/inf/None (strict JSON)."""
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if math.isfinite(x) else None


def select_events(
    df: pd.DataFrame,
    test_years: tuple[int, int],
    sid: str | int,
    start_month: int = 4,
    top: int = TOP_EVENTS,
) -> pd.DataFrame:
    """Annual maxima of the test years: the ``top`` largest by peak, plus the forced event when present.

    Returns ``hydro_year, date, q_m3s`` sorted by peak date. A forced event that is not an annual maximum
    of a test year is not invented: it is simply absent.
    """
    maxima, _ = extremes.annual_maxima(df, start_month)
    a, b = test_years
    maxima = maxima[(maxima["hydro_year"] >= a) & (maxima["hydro_year"] <= b)]
    chosen = maxima.sort_values("q_m3s", ascending=False).head(top)
    forced = FORCED_EVENTS.get(str(sid))
    if forced is not None:
        hit = maxima[maxima["date"] == pd.Timestamp(forced)]
        if len(hit) and hit.index[0] not in chosen.index:
            chosen = pd.concat([chosen.iloc[: max(top - 1, 0)], hit])
    return chosen.sort_values("date")[["hydro_year", "date", "q_m3s"]].reset_index(drop=True)


def issue_ends(
    ds: lstm.Dataset, basin_index: int, issue_dates: pd.DatetimeIndex, cfg
) -> np.ndarray:
    """Global window end (issue day + ``lead``) of each issue day; -1 when the window is not usable.

    Usable: it lies inside the basin series, with complete forcing over the whole window.
    """
    basin_dates = pd.DatetimeIndex(ds.dates[ds.basin_of == basin_index])
    length = lstm.window_len(cfg.mode, cfg.seq_len, cfg.lead)
    cum = ds._cumsum("bad", ds.bad)
    out = np.full(len(issue_dates), -1, dtype=np.int64)
    for k, day in enumerate(issue_dates):
        pos = basin_dates.get_indexer([day])[0]
        if pos < 0:
            continue
        end = pos + cfg.lead
        if end >= len(basin_dates) or end - length + 1 < 0:
            continue
        g_end = int(ds.offsets[basin_index]) + end
        if cum[g_end + 1] - cum[g_end - length + 1] == 0:
            out[k] = g_end
    return out


def _obs_window(df: pd.DataFrame, peak: pd.Timestamp) -> dict:
    days = pd.date_range(peak - pd.Timedelta(days=OBS_BEFORE), peak + pd.Timedelta(days=OBS_AFTER))
    q = df.set_index("date")["q_m3s"].reindex(days)
    return {"start": days[0].date().isoformat(), "q": [_num(v) for v in q.to_numpy(dtype=float)]}


def station_events(
    run: lstm.Run, basin: lstm.Basin, basin_index: int, ds: lstm.Dataset, df: pd.DataFrame,
    area_km2: float, events: pd.DataFrame,
) -> list[dict]:  # fmt: skip
    """The hindcast of every selected event of one station (flows in m3/s)."""
    cfg = run.config
    to_m3s = area_km2 / lstm.M3S_TO_MM_DAY
    flow_by_day = df.set_index("date")["q_m3s"]
    out = []
    for ev in events.itertuples():
        peak = pd.Timestamp(ev.date)
        days = pd.DatetimeIndex([peak - pd.Timedelta(days=ISSUES - 1 - k) for k in range(ISSUES)])
        ends = issue_ends(ds, basin_index, days, cfg)
        ok = ends >= 0
        median = lo = hi = np.zeros((0, cfg.lead))
        if ok.any():
            pred = lstm.ensemble_median(
                lstm.predict(run, ds, ends[ok], cfg.lead)
            )  # (n, leads) mm/d
            lo, hi = np.empty_like(pred), np.empty_like(pred)
            for j in range(cfg.lead):
                q = run.quantiles.get(str(j + 1))
                lo[:, j], hi[:, j] = lstm.band(pred[:, j], q) if q else (np.nan, np.nan)
            # the band is an interval around the median: keep the ordering p5 <= median <= p95
            median = pred
            lo, hi = np.minimum(lo, median), np.maximum(hi, median)
        issues = []
        for row, k in enumerate(np.flatnonzero(ok)):
            day = days[k]
            persist = flow_by_day.get(day, np.nan)
            issues.append(
                {
                    "issue_date": day.date().isoformat(),
                    "days_before_peak": int((peak - day).days),
                    "persistence": _num(persist),
                    "median": [_num(v * to_m3s) for v in median[row]],
                    "lo": [_num(v * to_m3s) for v in lo[row]],
                    "hi": [_num(v * to_m3s) for v in hi[row]],
                }
            )
        out.append(
            {
                "peak_date": peak.date().isoformat(),
                "peak_q": _num(ev.q_m3s),
                "hydro_year": int(ev.hydro_year),
                "obs": _obs_window(df, peak),
                "issues": issues,
            }
        )
    return out


def event_meta(run: lstm.Run, sid: str, area_km2: float, period: str) -> dict:
    cfg = run.config
    pre = run.info.get("pretrain") or {}
    return {
        "run_name": run.info.get("run_name"),
        "mode": cfg.mode,
        "split": cfg.split,
        "seeds": list(cfg.seeds),
        "test_years": list(lstm.SPLITS[cfg.split]["test"]),
        "leads": cfg.lead,
        "issues": ISSUES,
        "band": "90 % (cuantiles 5 y 95 % de los residuos de validación)",
        "forcing": FORCING_NOTE,
        "caveat": CAVEAT,
        "pretrain": PRETRAIN_NOTE if pre.get("used") else None,
        "unit": "m³/s",
        "area_km2": _num(area_km2, 1),
        "area_note": AREA_NOTES.get(str(sid)),
        "source": flow.SOURCE,
        "period": period,
    }


def build_events(
    run: lstm.Run,
    basins: list[lstm.Basin],
    flow_dir: Path | str,
    stations: list[str] | None = None,
    progress: Callable[[str], None] = lambda s: None,
) -> dict[str, dict]:
    """Event payloads by station id for the stations of ``basins`` (stations without test floods are left out)."""
    cfg = run.config
    if cfg.mode != "forecast":
        raise ValueError(f"the flood card needs a forecast-mode run, this one is {cfg.mode!r}")
    flow_dir = Path(flow_dir)
    meta = {
        str(s["id"]): s
        for s in json.loads((flow_dir / "stations.json").read_text(encoding="utf-8"))["stations"]
    }
    ds = lstm.Dataset.from_basins(basins, cfg.split, run.norm)
    test_years = tuple(lstm.SPLITS[cfg.split]["test"])
    info = run.info.get("neuquen", {})
    out = {}
    for i, b in enumerate(basins):
        if stations is not None and b.id not in stations:
            continue
        df = flow.read_flow(flow_dir / f"{b.id}.parquet")
        start_month = (meta.get(b.id) or {}).get(
            "hydro_year_start_month"
        ) or lstm.HYDRO_YEAR_START_MONTH
        events = select_events(df, test_years, b.id, start_month)
        if events.empty:
            progress(f"station {b.id}: no annual maximum in the test years")
            continue
        area = float((info.get(b.id) or {}).get("area_km2") or float(np.exp(b.static[0])))
        first, last = df["date"].min().date().isoformat(), df["date"].max().date().isoformat()
        payload = {
            "station_id": b.id,
            "meta": event_meta(run, b.id, area, f"{first}/{last}"),
            "events": station_events(run, b, i, ds, df, area, events),
        }
        out[b.id] = payload
        progress(f"station {b.id}: {len(events)} events")
    return out


def write_events(payloads: dict[str, dict], out_dir: Path | str) -> list[Path]:
    """Write ``events/<id>.json`` (strict JSON: a stray NaN raises) and register them in the layer."""
    out_dir = Path(out_dir)
    paths = []
    for sid, payload in payloads.items():
        path = out_dir / EVENTS_DIR / f"{sid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        paths.append(path)
    flood_stations.attach_events(out_dir)
    return paths

"""Idempotent operational ingest of current inputs for the forecast phase (F6.1b).

One adapter per source; each takes an injectable ``fetcher`` (the default one hits the network) and
returns a tidy DataFrame. ``run_ingest`` stores it as ``<root>/<source>/<run_date>.parquet`` and
keeps ``<root>/manifest.json``.

Conventions
-----------
* ``run_date`` is the ingest date (``--date``) and names the snapshot file. Every row carries
  ``available_on`` (first date the value was seen = ``run_date`` of the snapshot, a conservative
  upper bound of its publication date) and ``fetched_at`` (UTC wall clock). Parquet schema
  metadata holds source, license, units and notes.
* Daily values are UTC days with the ERA5 convention of ``io/forcing.py``: day D accumulates
  hours D 01:00 .. D+1 00:00. Station-box means use ``forcing.field_mean`` (cos(lat) weights over
  the cells whose centre is inside ``snow.UPSTREAM_BOXES``, approximate rectangles, sin verificar).
* Forecasts (``ecmwf``, ``gefs``): the 00 UTC run of ``init_date`` (``--date`` or the newest
  available before it). Lead ``d`` (1..10) is the accumulation over (24(d-1) h, 24 d h] after
  the init, i.e. UTC day ``init_date + d - 1`` in the ERA5 convention (``valid_date``).
* Leakage rule: observations are stored only for value dates <= ``run_date - 1`` (ONI: nominal
  publication date <= ``run_date``); forecasts only from runs with ``init_date <= run_date``.
  Future *valid* dates of a forecast are the forecast itself, not leakage.
* Idempotency: an existing snapshot is not refetched unless ``force``; writes go to a temporary
  file renamed atomically.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr

from clima_nqn.io import enso, era5, flow, forcing, snow
from clima_nqn.io.grib import grib_fields
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import riskday

DEFAULT_ROOT = Path("data/raw/operational")
MANIFEST = "manifest.json"
FLOW_DAYS = 60
ERA5T_DAYS = 14
LEADS = range(1, 11)
BOX_MARGIN = 0.5  # degrees added around the union of the boxes when cropping a grid
GEFS_BASE = "https://noaa-gefs-pds.s3.amazonaws.com"
GEFS_MEMBERS = ("geavg", "gec00")  # ensemble mean + control; members gepNN can be added
GEFS25_MEMBERS = fc.GEFS_MEMBERS  # c00, p01..p04: the members the frozen F5.3 model was trained on
GEFS25_STEP = (
    6  # h; operational pgrb2s files carry 6 h APCP buckets at steps that are multiples of 6
)
RUN_FALLBACK_DAYS = 3  # newest run searched: run_date, run_date-1, ...


class NotAvailable(Exception):
    """The requested forecast run (or file) is not published (yet)."""


@dataclass(frozen=True)
class SourceInfo:
    source: str
    license: str
    units: str
    value_col: str  # column holding the value date (for the manifest)
    notes: str = ""


INFO = {
    "flow": SourceInfo(
        flow.SOURCE,
        "sin verificar (SNIH is not an alert network; terms not checked)",
        "q_m3s: m3/s (daily mean, QMD)",
        "date",
        "SNIH days are local (UTC-3); validated flag kept per row.",
    ),
    "oni": SourceInfo(
        enso.SOURCE,
        "NOAA public data (sin verificar)",
        "oni: degC anomaly (3-month running mean Nino-3.4)",
        "date",
        "date = central month; nominal publication = first day of the month two months later (sin verificar).",
    ),
    "era5t": SourceInfo(
        era5.SOURCE,
        era5.LICENSE,
        "precip_mm: mm/day (UTC day, hours D 01:00..D+1 00:00), box mean",
        "date",
        f"Preliminary ERA5T where past the final-data stop. {snow.BOX_NOTE}.",
    ),
    "ecmwf": SourceInfo(
        "ECMWF IFS open data, 0.25 deg, 00 UTC run, total precipitation (tp)",
        "CC-BY-4.0",
        "precip_mm: mm per 24 h lead window, box mean",
        "valid_date",
        f"{snow.BOX_NOTE}. valid_date = UTC day init_date + lead_day - 1.",
    ),
    "gefs": SourceInfo(
        "NOAA GEFS 0.5 deg pgrb2a, 00 UTC run, APCP (noaa-gefs-pds)",
        "NOAA open data (sin verificar)",
        "precip_mm: mm per 24 h lead window (sum of 6 h APCP), box mean",
        "valid_date",
        f"{snow.BOX_NOTE}. member geavg = ensemble mean, gec00 = control.",
    ),
    "gefs_regions": SourceInfo(
        "NOAA GEFS operational 0.25 deg pgrb2sp25, 00 UTC run, members c00,p01..p04, APCP (noaa-gefs-pds)",
        fc.LICENSE_GEFS,
        "tp_mm: mm per 24 h lead window (sum of four 6 h APCP buckets), cos(lat)-weighted region mean",
        "valid_date",
        f"{fc.LEAD_CONVENTION}. Cropped to the wide grid ({fc.WIDE_GRID.description}); regions "
        "from riskday.regions. A member/lead with any missing 6 h step is dropped, not zero-filled.",
    ),
    "era5t_regions": SourceInfo(
        era5.SOURCE,
        era5.LICENSE,
        "tp_mm: mm/day (UTC day, hours D 01:00..D+1 00:00), cos(lat)-weighted region mean",
        "date",
        "Same daily window and wide grid as the hindcast observations (observe.py); preliminary ERA5T "
        "where past the final-data stop. Days with no data (all-NaN) are dropped.",
    ),
}
SOURCES = tuple(INFO)

Box = snow.Box
Boxes = dict[int, Box]


# --- pure helpers ---------------------------------------------------------------------------


def _day(value: date | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def union_area(boxes: Boxes, margin: float = BOX_MARGIN) -> tuple[float, float, float, float]:
    """(N, W, S, E) of the union of the station boxes plus a margin (``era5.crop_to_area`` order)."""
    arr = np.array(list(boxes.values()), dtype=float)  # south, north, west, east
    return (
        float(arr[:, 1].max() + margin),
        float(arr[:, 2].min() - margin),
        float(arr[:, 0].min() - margin),
        float(arr[:, 3].max() + margin),
    )


def box_means(field: xr.DataArray, boxes: Boxes) -> dict[int, float]:
    """Mean of a 2-D (lat, lon) field over every station box (cos(lat) weights)."""
    return {sid: forcing.field_mean(field, box) for sid, box in boxes.items()}


def daily_from_cumulative(cum: dict[int, float], steps: list[int]) -> dict[int, float]:
    """Daily (24 h) accumulations from cumulative-since-init values at ``steps`` (hours).

    ``steps`` must be 24, 48, ...; lead ``d`` = ``cum[24 d] - cum[24 (d - 1)]`` (``cum[0] = 0``).
    A negative difference (numerical noise) is clipped to 0.
    """
    out, previous = {}, 0.0
    for d, step in enumerate(sorted(steps), start=1):
        if step != 24 * d:
            raise ValueError(f"steps must be 24, 48, ...: got {sorted(steps)}")
        out[d] = max(cum[step] - previous, 0.0)
        previous = cum[step]
    return out


def daily_from_buckets(buckets: dict[int, float], lead: int, width: int = 6) -> float:
    """Sum of the ``width``-hour buckets (keyed by their end step) that make up lead day ``lead``."""
    ends = range(24 * (lead - 1) + width, 24 * lead + 1, width)
    missing = [e for e in ends if e not in buckets]
    if missing:
        raise ValueError(f"missing {width} h buckets ending at steps {missing}")
    return float(sum(buckets[e] for e in ends))


def _stamp(df: pd.DataFrame, run_date: pd.Timestamp, now: datetime) -> pd.DataFrame:
    df = df.copy()
    df["available_on"] = pd.Timestamp(run_date)
    df["fetched_at"] = (
        pd.Timestamp(now).tz_convert("UTC") if now.tzinfo else pd.Timestamp(now, tz="UTC")
    )
    return df


# --- default fetchers (network) -------------------------------------------------------------


def fetch_flow_rows(station_id: int, start: date, stop: date) -> list[dict]:
    """SNIH QMD raw measurements of one station (``flow.fetch_window``, validated series)."""
    with httpx.Client(timeout=60.0) as client:
        return flow.fetch_window(client, station_id, start, stop)


def fetch_oni_text() -> str:
    return enso.fetch_oni()


def fetch_era5t_tp(
    start: pd.Timestamp, stop: pd.Timestamp, area, opener=era5.open_arco
) -> xr.DataArray:
    """Hourly ARCO ``tp`` (m) cropped to ``area`` for ``start..stop`` inclusive (hourly stamps)."""
    ds = era5.crop_to_area(opener(), area, {"total_precipitation": "tp"})
    times = pd.date_range(start, stop, freq="h")
    avail = pd.DatetimeIndex(ds["time"].values)
    present = times[times.isin(avail)]
    if len(present) == 0:
        raise NotAvailable(f"ARCO store ends at {avail.max()}, before {start}")

    def one(t: pd.Timestamp) -> xr.DataArray:
        return ds["tp"].sel(time=t).load()

    with ThreadPoolExecutor(max_workers=16) as pool:
        fields = list(pool.map(one, present))
    return xr.concat(fields, dim="time").assign_coords(time=present)


def fetch_ecmwf_tp(init_date: date, steps: list[int], area) -> dict[int, xr.DataArray]:
    """Cumulative ``tp`` (m) of the 00 UTC IFS run at ``steps`` from the ECMWF open-data AWS mirror."""
    from ecmwf.opendata import Client

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "tp.grib2"
        try:
            Client(source="aws").retrieve(
                date=init_date.strftime("%Y%m%d"), time=0, type="fc", stream="oper",
                param="tp", step=steps, target=str(target),
            )  # fmt: skip
        except Exception as exc:  # network / 404 / not published
            raise NotAvailable(f"IFS {init_date} 00z: {exc}") from exc
        fields = grib_fields(target.read_bytes(), area)
    out = {k["step"]: da for k, da in fields if k["shortName"] == "tp"}
    if set(steps) - set(out):
        raise NotAvailable(f"IFS {init_date} 00z: steps {sorted(set(steps) - set(out))} missing")
    return out


def gefs_url(init_date: date, member: str, step: int) -> str:
    d = init_date.strftime("%Y%m%d")
    return f"{GEFS_BASE}/gefs.{d}/00/atmos/pgrb2ap5/{member}.t00z.pgrb2a.0p50.f{step:03d}"


def gefs25_url(init_date: date, member: str, step: int) -> str:
    """Operational 0.25 deg surface file of member ``c00``/``p01``..: ``.../pgrb2sp25/gep01.t00z.pgrb2s.0p25.f024``."""
    d = init_date.strftime("%Y%m%d")
    return f"{GEFS_BASE}/gefs.{d}/00/atmos/pgrb2sp25/ge{member}.t00z.pgrb2s.0p25.f{step:03d}"


def parse_gefs_idx(text: str, span: tuple[int, int] | None = None) -> tuple[int, int | None] | None:
    """Byte range ``(start, end)`` of the surface APCP message in a GEFS .idx (``end`` None = to EOF).

    With ``span = (start_h, end_h)`` only the message accumulated over exactly that window matches
    (``"6-12 hour acc fcst"``); without it the first surface APCP does.
    """
    lines = [ln.split(":") for ln in text.splitlines() if ln.strip()]
    for i, parts in enumerate(lines):
        if len(parts) > 5 and parts[3] == "APCP" and parts[4] == "surface":
            if span is not None:
                m = fc._ACC.match(parts[5])
                if not m or (int(m[1]), int(m[2])) != tuple(span):
                    continue
            start = int(parts[1])
            end = int(lines[i + 1][1]) - 1 if i + 1 < len(lines) else None
            return start, end
    return None


def fetch_gefs_apcp(init_date: date, member: str, step: int, area) -> xr.DataArray:
    """6 h ``APCP`` (kg/m2 = mm) valid at ``step`` for one member, via .idx byte range (anonymous)."""
    url = gefs_url(init_date, member, step)
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        idx = client.get(url + ".idx")
        if idx.status_code == 404:
            raise NotAvailable(f"GEFS {init_date} 00z {member} f{step:03d} not published")
        idx.raise_for_status()
        rng = parse_gefs_idx(idx.text)
        if rng is None:
            raise RuntimeError(f"no surface APCP in {url}.idx")
        start, end = rng
        header = {"Range": f"bytes={start}-{'' if end is None else end}"}
        resp = client.get(url, headers=header)
        resp.raise_for_status()
    fields = grib_fields(resp.content, area)
    if len(fields) != 1:
        raise RuntimeError(f"expected one APCP message in {url}, got {len(fields)}")
    return fields[0][1]


def _get_retry(
    client: httpx.Client, url: str, headers: dict | None = None, tries: int = 5
) -> httpx.Response:
    """GET with exponential backoff on transport errors and 429/5xx (S3 ``503 Slow Down``)."""
    for attempt in range(tries):
        try:
            resp = client.get(url, headers=headers)
        except httpx.TransportError:
            if attempt == tries - 1:
                raise
        else:
            if resp.status_code != 429 and resp.status_code < 500:
                return resp
            if attempt == tries - 1:
                return resp
        time.sleep(min(2.0**attempt, 16.0))
    raise AssertionError("unreachable")


def fetch_gefs25_apcp(init_date: date, member: str, step: int, area) -> xr.DataArray:
    """6 h ``APCP`` (kg/m2 = mm) over forecast hours (step-6, step] of one operational 0.25 deg member.

    The .idx must carry the surface APCP accumulated exactly over ``(step-6)-step hour acc``
    (verified 2026-11-22: f006 is ``0-6``, f012 ``6-12`` ... f240 ``234-240``); otherwise the
    accumulation scheme changed and the call fails instead of returning a wrong window.
    """
    url = gefs25_url(init_date, member, step)
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        idx = _get_retry(client, url + ".idx")
        if idx.status_code == 404:
            raise NotAvailable(f"GEFS 0.25 {init_date} 00z {member} f{step:03d} not published")
        idx.raise_for_status()
        rng = parse_gefs_idx(idx.text, span=(step - GEFS25_STEP, step))
        if rng is None:
            raise RuntimeError(f"no surface APCP {step - GEFS25_STEP}-{step} hour acc in {url}.idx")
        start, end = rng
        header = {"Range": f"bytes={start}-{'' if end is None else end}"}
        resp = _get_retry(client, url, headers=header)
        resp.raise_for_status()
    fields = grib_fields(resp.content, area)
    if len(fields) != 1:
        raise RuntimeError(f"expected one APCP message in {url}, got {len(fields)}")
    return fields[0][1]


# --- adapters -------------------------------------------------------------------------------


def ingest_flow(
    run_date: pd.Timestamp,
    fetcher: Callable[[int, date, date], list[dict]] = fetch_flow_rows,
    now: datetime | None = None,
    **_,
) -> pd.DataFrame:
    """SNIH QMD of every station for ``run_date - 60`` .. ``run_date - 1``."""
    now = now or datetime.now(UTC)
    start, stop = (
        (run_date - timedelta(days=FLOW_DAYS)).date(),
        (run_date - timedelta(days=1)).date(),
    )
    frames = []
    for station in flow.STATIONS:
        raw = fetcher(station["id"], start, stop)
        if not raw:
            continue
        df = flow.build_flow(raw, station, now.date())
        df = df[df["q_m3s"].notna() & (df["date"] >= _day(start)) & (df["date"] <= _day(stop))]
        df.insert(0, "station_id", station["id"])
        frames.append(df[["station_id", "date", "q_m3s", "qualifier", "validated"]])
    cols = ["station_id", "date", "q_m3s", "qualifier", "validated"]
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
    out["date"] = pd.to_datetime(out["date"])
    return _stamp(out, run_date, now)


def oni_nominal_publication(center: pd.Series) -> pd.Series:
    """First day of the month two months after the central month (sin verificar)."""
    return center.dt.to_period("M").dt.to_timestamp() + pd.DateOffset(months=2)


def ingest_oni(
    run_date: pd.Timestamp,
    fetcher: Callable[[], str] = fetch_oni_text,
    now: datetime | None = None,
    **_,
) -> pd.DataFrame:
    """ONI months whose nominal publication date is on or before ``run_date``."""
    now = now or datetime.now(UTC)
    df = enso.build_enso(fetcher())
    df = df[oni_nominal_publication(df["date"]) <= run_date].reset_index(drop=True)
    df = df.assign(nominal_publication=oni_nominal_publication(df["date"]))
    return _stamp(df, run_date, now)


def ingest_era5t(
    run_date: pd.Timestamp,
    fetcher: Callable[..., xr.DataArray] = fetch_era5t_tp,
    boxes: Boxes = snow.UPSTREAM_BOXES,
    now: datetime | None = None,
    **_,
) -> pd.DataFrame:
    """Daily box-mean precipitation (mm) for UTC days ``run_date - 14`` .. ``run_date - 1``.

    Day D needs hours D 01:00 .. D+1 00:00, so the hourly range is ``first 01:00 .. run_date 00:00``.
    Days with fewer than 24 hours are dropped (not yet in the store).
    """
    now = now or datetime.now(UTC)
    first = run_date - timedelta(days=ERA5T_DAYS)
    tp = fetcher(first + pd.Timedelta(hours=1), run_date, union_area(boxes))
    times = pd.DatetimeIndex(tp["time"].values)
    frames = []
    for sid, box in boxes.items():
        hourly = forcing.box_mean(tp, box) * 1000.0  # m -> mm
        daily = forcing._daily(hourly, times, "sum", shift_hours=1).dropna()
        frames.append(
            pd.DataFrame({"station_id": sid, "date": daily.index, "precip_mm": daily.values})
        )
    out = pd.concat(frames, ignore_index=True)
    out = out[(out["date"] >= first) & (out["date"] <= run_date - pd.Timedelta(days=1))]
    return _stamp(out.reset_index(drop=True), run_date, now)


def _candidate_runs(run_date: pd.Timestamp) -> list[pd.Timestamp]:
    return [run_date - pd.Timedelta(days=i) for i in range(RUN_FALLBACK_DAYS)]


def _forecast_rows(
    init: pd.Timestamp, per_lead: dict[int, dict[int, float]], **extra
) -> pd.DataFrame:
    rows = [
        {
            "station_id": sid, "init_date": init, "lead_day": d,
            "valid_date": init + pd.Timedelta(days=d - 1), **extra, "precip_mm": mm,
        }
        for d, by_station in per_lead.items()
        for sid, mm in by_station.items()
    ]  # fmt: skip
    return pd.DataFrame(rows)


def ingest_ecmwf(
    run_date: pd.Timestamp,
    fetcher: Callable[[date, list[int], tuple], dict[int, xr.DataArray]] = fetch_ecmwf_tp,
    boxes: Boxes = snow.UPSTREAM_BOXES,
    now: datetime | None = None,
    **_,
) -> pd.DataFrame:
    """Daily precipitation for leads 1..10 from the newest 00 UTC IFS run on or before ``run_date``."""
    now = now or datetime.now(UTC)
    steps = [24 * d for d in LEADS]
    area = union_area(boxes)
    last: Exception | None = None
    for init in _candidate_runs(run_date):
        try:
            fields = fetcher(init.date(), steps, area)
        except NotAvailable as exc:
            last = exc
            continue
        cum = {s: box_means(fields[s] * 1000.0, boxes) for s in steps}  # m -> mm
        per_station = {
            sid: daily_from_cumulative({s: cum[s][sid] for s in steps}, steps) for sid in boxes
        }
        per_lead = {d: {sid: per_station[sid][d] for sid in boxes} for d in LEADS}
        return _stamp(_forecast_rows(init, per_lead), run_date, now)
    raise NotAvailable(f"no IFS run found in the last {RUN_FALLBACK_DAYS} days: {last}")


def ingest_gefs(
    run_date: pd.Timestamp,
    fetcher: Callable[[date, str, int, tuple], xr.DataArray] = fetch_gefs_apcp,
    boxes: Boxes = snow.UPSTREAM_BOXES,
    members: tuple[str, ...] = GEFS_MEMBERS,
    now: datetime | None = None,
    **_,
) -> pd.DataFrame:
    """Daily precipitation (sum of 6 h APCP) for leads 1..10, per member, newest run <= ``run_date``."""
    now = now or datetime.now(UTC)
    area = union_area(boxes)
    ends = list(range(6, 24 * max(LEADS) + 1, 6))
    last: Exception | None = None
    for init in _candidate_runs(run_date):
        jobs = [(m, s) for m in members for s in ends]

        def one(job, init=init):
            member, step = job
            return job, box_means(fetcher(init.date(), member, step, area), boxes)

        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                got = dict(pool.map(one, jobs))
        except NotAvailable as exc:
            last = exc
            continue
        frames = []
        for member in members:
            per_lead = {}
            for d in LEADS:
                per_lead[d] = {
                    sid: daily_from_buckets({s: got[(member, s)][sid] for s in ends}, d)
                    for sid in boxes
                }
            frames.append(_forecast_rows(init, per_lead, member=member))
        return _stamp(pd.concat(frames, ignore_index=True), run_date, now)
    raise NotAvailable(f"no GEFS run found in the last {RUN_FALLBACK_DAYS} days: {last}")


def wide_region_means(field: xr.DataArray, masks: dict[str, np.ndarray]) -> dict[str, float]:
    """Region means of a field regridded onto ``WIDE_GRID`` (exact selection at 0.25 deg).

    Uses ``riskday.region_means`` (cos(lat) weights, NaN ignored); all-NaN regions give NaN.
    """
    grid = fc.WIDE_GRID
    on_grid = xr.DataArray(
        fc.to_target_grid(field, grid).astype("float64"),
        dims=("lat", "lon"),
        coords={"lat": grid.lat, "lon": grid.lon},
    )
    return {k: float(v) for k, v in riskday.region_means(on_grid, masks).items()}


def ingest_gefs_regions(
    run_date: pd.Timestamp,
    fetcher: Callable[[date, str, int, tuple], xr.DataArray] = fetch_gefs25_apcp,
    members: tuple[str, ...] = GEFS25_MEMBERS,
    now: datetime | None = None,
    **_,
) -> pd.DataFrame:
    """Regional daily GEFS precipitation (mm) for leads 1..10, per member, newest run <= ``run_date``.

    Lead ``L`` = sum of the four 6 h buckets ending at 24(L-1)+6 .. 24 L. A member/lead with any
    missing step is dropped. A run is accepted when at least one member has all 10 leads, so a run
    still being published falls back to the previous one. ``df.attrs["manifest"]`` lists the
    missing members/steps.
    """
    now = now or datetime.now(UTC)
    grid = fc.WIDE_GRID
    area = fc._margin_area(grid.area)
    masks = riskday.regions(grid.lat, grid.lon)
    ends = list(range(GEFS25_STEP, 24 * max(LEADS) + 1, GEFS25_STEP))
    last: Exception | None = None
    for init in _candidate_runs(run_date):
        jobs = [(m, s) for m in members for s in ends]

        def one(job, init=init):
            member, step = job
            try:
                return job, wide_region_means(fetcher(init.date(), member, step, area), masks)
            except NotAvailable as exc:
                return job, exc

        with ThreadPoolExecutor(max_workers=8) as pool:
            got = dict(pool.map(one, jobs))
        rows, missing = [], {}
        full = 0
        for member in members:
            lost = [s for s in ends if isinstance(got[(member, s)], NotAvailable)]
            if lost:
                missing[member] = lost
            complete = 0
            for d in LEADS:
                steps = [e for e in ends if 24 * (d - 1) < e <= 24 * d]
                if any(isinstance(got[(member, e)], NotAvailable) for e in steps):
                    continue
                complete += 1
                for region in masks:
                    buckets = {e: got[(member, e)][region] for e in steps}
                    tp = daily_from_buckets(buckets, d)
                    if np.isnan(tp):
                        continue
                    rows.append(
                        {
                            "init_date": init, "lead": d, "valid_date": init + pd.Timedelta(days=d - 1),
                            "member": member, "region": region, "tp_mm": tp,
                        }
                    )  # fmt: skip
            full += complete == len(LEADS)
        if full == 0:
            last = NotAvailable(
                f"GEFS 0.25 {init:%Y-%m-%d} 00z: no member has all {len(LEADS)} leads"
            )
            continue
        df = _stamp(pd.DataFrame(rows), run_date, now)
        df["lead"] = df["lead"].astype(int)
        df.attrs["manifest"] = {
            "init_date": f"{init:%Y-%m-%d}",
            "members_present": [
                m for m in members if m not in missing or len(missing[m]) < len(ends)
            ],
            "missing_steps": missing,
        }
        return df
    raise NotAvailable(f"no GEFS 0.25 run found in the last {RUN_FALLBACK_DAYS} days: {last}")


def ingest_era5t_regions(
    run_date: pd.Timestamp,
    fetcher: Callable[..., xr.DataArray] = fetch_era5t_tp,
    now: datetime | None = None,
    **_,
) -> pd.DataFrame:
    """Daily regional ERA5T ``tp`` (mm) for UTC days ``run_date - 14`` .. ``run_date - 1``.

    Same window as ``observe.py`` (F5.3 obs): day D = hourly steps D 01:00 .. D+1 00:00 summed on
    the wide grid (m -> mm), then ``riskday.region_means``. Days missing any of the 24 hours, or
    all-NaN (ERA5T gaps), are dropped.
    """
    now = now or datetime.now(UTC)
    grid = fc.WIDE_GRID
    masks = riskday.regions(grid.lat, grid.lon)
    first = run_date - timedelta(days=ERA5T_DAYS)
    tp = fetcher(first + pd.Timedelta(hours=1), run_date, grid.area)
    times = pd.DatetimeIndex(tp["time"].values)
    rows = []
    for day in pd.date_range(first, run_date - pd.Timedelta(days=1)):
        stamps = [day + pd.Timedelta(hours=h) for h in range(1, 25)]
        if times.isin(stamps).sum() != 24:
            continue
        hours = tp.sel(time=stamps)
        daily = hours.sum("time", skipna=False) * 1000.0  # m -> mm; any NaN hour -> NaN cell
        for region, mm in wide_region_means(daily, masks).items():
            if not np.isnan(mm):
                rows.append({"date": day, "region": region, "tp_mm": mm})
    cols = ["date", "region", "tp_mm"]
    out = pd.DataFrame(rows, columns=cols)
    out["date"] = pd.to_datetime(out["date"])
    return _stamp(out, run_date, now)


ADAPTERS: dict[str, Callable[..., pd.DataFrame]] = {
    "flow": ingest_flow,
    "oni": ingest_oni,
    "era5t": ingest_era5t,
    "ecmwf": ingest_ecmwf,
    "gefs": ingest_gefs,
    "gefs_regions": ingest_gefs_regions,
    "era5t_regions": ingest_era5t_regions,
}

# --- storage --------------------------------------------------------------------------------


def snapshot_path(root: Path, source: str, run_date: pd.Timestamp) -> Path:
    return Path(root) / source / f"{run_date:%Y-%m-%d}.parquet"


def check_no_leak(df: pd.DataFrame, source: str, run_date: pd.Timestamp) -> None:
    """Raise if any row has a value/publish/init date after ``run_date`` (see module docstring)."""
    if len(df) == 0:
        return
    if (df["available_on"] > run_date).any():
        raise ValueError(f"{source}: available_on after {run_date:%Y-%m-%d}")
    if source in ("flow", "era5t", "era5t_regions") and (df["date"] >= run_date).any():
        raise ValueError(f"{source}: value date not before {run_date:%Y-%m-%d}")
    if source == "oni" and (df["nominal_publication"] > run_date).any():
        raise ValueError(f"oni: nominal publication after {run_date:%Y-%m-%d}")
    if source in ("ecmwf", "gefs", "gefs_regions") and (df["init_date"] > run_date).any():
        raise ValueError(f"{source}: init_date after {run_date:%Y-%m-%d}")


def write_parquet_atomic(df: pd.DataFrame, path: Path, metadata: dict[str, str]) -> Path:
    """Write ``df`` with schema metadata to a temp file, then rename it onto ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **{
        k.encode(): v.encode() for k, v in metadata.items()
    }})  # fmt: skip
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        pq.write_table(table, tmp)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    return path


def snapshot_metadata(source: str, run_date: pd.Timestamp, now: datetime) -> dict[str, str]:
    info = INFO[source]
    return {
        "source": info.source,
        "license": info.license,
        "units": info.units,
        "notes": info.notes,
        "run_date": f"{run_date:%Y-%m-%d}",
        "fetched_at": now.isoformat(),
        "available_on": "date this snapshot first saw the value (conservative upper bound of publication)",
    }


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, ensure_ascii=False)
    os.replace(tmp_name, path)


def read_manifest(root: Path) -> dict:
    path = Path(root) / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def newest_value_date(path: Path, source: str) -> pd.Timestamp | None:
    col = INFO[source].value_col
    s = pd.read_parquet(path, columns=[col])[col]
    return None if s.empty else pd.Timestamp(s.max())


# --- runner ---------------------------------------------------------------------------------


def run_ingest(
    run_date: date | pd.Timestamp,
    root: Path | str = DEFAULT_ROOT,
    sources: list[str] | None = None,
    force: bool = False,
    fetchers: dict[str, Callable] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, dict]:
    """Ingest ``sources`` for ``run_date``; one failing source does not stop the others.

    ``fetchers`` overrides the default network fetcher per source (tests). Returns the manifest
    entries of this run (``status`` ok / skipped / failed) and updates ``<root>/manifest.json``.
    """
    root = Path(root)
    run = _day(run_date)
    names = list(sources) if sources else list(SOURCES)
    unknown = sorted(set(names) - set(ADAPTERS))
    if unknown:
        raise ValueError(f"unknown sources {unknown}; choose from {list(SOURCES)}")
    fetchers = fetchers or {}
    manifest = read_manifest(root)
    results: dict[str, dict] = {}
    for name in names:
        prev = manifest.get(name, {})
        target = snapshot_path(root, name, run)
        stamp = now()
        entry = {
            "status": "failed", "error": None, "attempted_run_date": f"{run:%Y-%m-%d}",
            "last_run_date": prev.get("last_run_date"),
            "newest_value_date": prev.get("newest_value_date"), "lag_days": prev.get("lag_days"),
            "rows": prev.get("rows"), "file": prev.get("file"), "updated_at": stamp.isoformat(),
            "detail": prev.get("detail"),
        }  # fmt: skip
        try:
            if target.exists() and not force:
                status, df_path = "skipped", target
                rows = pq.ParquetFile(target).metadata.num_rows
            else:
                kwargs = {"fetcher": fetchers[name]} if name in fetchers else {}
                df = ADAPTERS[name](run, now=stamp, **kwargs)
                extra = df.attrs.get("manifest")
                check_no_leak(df, name, run)
                if df.empty:
                    raise RuntimeError("source returned no rows")
                write_parquet_atomic(df, target, snapshot_metadata(name, run, stamp))
                status, df_path, rows = "ok", target, len(df)
            newest = newest_value_date(df_path, name)
            entry.update(
                status=status, error=None, last_run_date=f"{run:%Y-%m-%d}", rows=rows,
                newest_value_date=None if newest is None else f"{newest:%Y-%m-%d}",
                lag_days=None if newest is None else (run - newest).days,
                file=str(target.relative_to(root)),
            )  # fmt: skip
            if status == "ok":
                entry["detail"] = extra
        except Exception as exc:  # noqa: BLE001 - a failing source must not stop the others
            entry["error"] = f"{type(exc).__name__}: {exc}"
        results[name] = entry
        manifest[name] = entry
        _write_json_atomic(root / MANIFEST, manifest)
    return results

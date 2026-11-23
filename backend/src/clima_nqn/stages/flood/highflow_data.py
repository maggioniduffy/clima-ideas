"""Data side of the high-flow leave-one-flood-out test (F6.7): folds, floods, coverage and forecasts.

See ``highflow.py`` for the method. This module has no torch dependency.

* Folds. A fold is one hydrological year (April-March, ``lstm.hydro_year``). ``fold_train_mask`` is the
  single place that decides which dates may be used to fit anything for that fold: everything outside the
  hydrological year plus ``gap_days`` on each side. ``check_no_leak`` raises if a set of dates used to fit
  something touches the excluded range.
* Floods. Annual maxima (``extremes.annual_maxima``, F2.2 rule: hydrological years with >= 330 valid days)
  per station; "large" = annual maximum >= median of the station's annual maxima (full record, used only to
  select the floods, never as a model input). A flood is *covered* when forecasts exist for every issue
  day of the window peak-15..peak+15: the GEFSv12 reforecast (valid days 2000-01-10..2019-12-31) or the
  operational GEFS 0.25 deg archive (``pgrb2sp25``, from 2020-09-23, verified on the S3 bucket for every
  day to 2025-12-31 with the member ``gep04`` f240 index), with ERA5 forcing up to the day before issue.
* Forecast convention. Lead L = hours (24(L-1), 24L] of the 00 UTC run of the issue day t; the valid
  (UTC) day is v = t + L - 1. The daily total of a station is the cos(lat)-weighted mean over the cells
  inside ``snow.UPSTREAM_BOXES`` of the member's 24 h total.
* Operational archive. ``fetch_init`` downloads the 6 h APCP buckets (``ops.ingest.fetch_gefs25_apcp``,
  steps 6..240) of the 5 members (c00, p01..p04) of one init and writes
  ``<out_dir>/<YYYYMMDD>.parquet`` (``init_date, lead, valid_date, member, station_id, precip_mm``) plus a
  ``<YYYYMMDD>.json`` sidecar that lists the missing files. Missing files are recorded, never fatal; a lead
  with a missing bucket is dropped.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.io import forcing, snow
from clima_nqn.stages.flood import extremes, lstm

GAP_DAYS = 30
HALF_WINDOW = 15  # issue days peak-15 .. peak+15
LEADS = tuple(range(1, 11))
MEMBERS = ("c00", "p01", "p02", "p03", "p04")
STEPS = tuple(range(6, 241, 6))
REFORECAST_FIRST_VALID = pd.Timestamp("2000-01-10")
REFORECAST_LAST_VALID = pd.Timestamp("2019-12-31")
OPS_FIRST_INIT = pd.Timestamp("2020-09-23")  # first day with pgrb2sp25 (S3 listing, 2026-11-23)
STATIONS = (12004, 12010, 12012)
OPS_DIR = Path(__file__).resolve().parents[4] / "data" / "forecast" / "f67-gefs-ops"
BOXES = snow.UPSTREAM_BOXES


class LeakError(AssertionError):
    pass


# --- folds ------------------------------------------------------------------------------------


def fold_excluded_range(
    fold_year: int, gap_days: int = GAP_DAYS
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last excluded day: the hydrological year ``fold_year`` plus ``gap_days`` each side."""
    start = pd.Timestamp(fold_year, lstm.HYDRO_YEAR_START_MONTH, 1) - pd.Timedelta(days=gap_days)
    end = (
        pd.Timestamp(fold_year + 1, lstm.HYDRO_YEAR_START_MONTH, 1)
        - pd.Timedelta(days=1)
        + pd.Timedelta(days=gap_days)
    )
    return start, end


def fold_train_mask(dates, fold_year: int, gap_days: int = GAP_DAYS) -> np.ndarray:
    """True for the dates that may be used to fit anything in the fold of ``fold_year``."""
    d = pd.DatetimeIndex(dates).normalize()
    start, end = fold_excluded_range(fold_year, gap_days)
    return np.asarray(~((d >= start) & (d <= end)))


def check_no_leak(used_dates, fold_year: int, gap_days: int = GAP_DAYS, what: str = "") -> None:
    """Raise ``LeakError`` if any of ``used_dates`` is inside the excluded range of the fold."""
    d = pd.DatetimeIndex(pd.Series(used_dates).dropna()).normalize()
    if not len(d):
        return
    bad = ~fold_train_mask(d, fold_year, gap_days)
    if bad.any():
        start, end = fold_excluded_range(fold_year, gap_days)
        raise LeakError(
            f"{what or 'fit'}: {int(bad.sum())} date(s) inside the excluded range "
            f"{start:%Y-%m-%d}..{end:%Y-%m-%d} (first {d[bad][0]:%Y-%m-%d})"
        )


# --- floods and coverage ----------------------------------------------------------------------


def window_days(peak: pd.Timestamp) -> pd.DatetimeIndex:
    p = pd.Timestamp(peak).normalize()
    return pd.date_range(p - pd.Timedelta(days=HALF_WINDOW), p + pd.Timedelta(days=HALF_WINDOW))


def needed_pairs(peak: pd.Timestamp) -> list[tuple[pd.Timestamp, int]]:
    """Scored ``(issue day t, lead L)``: t and v = t + L - 1 both inside peak-15..peak+15."""
    days = window_days(peak)
    lo, hi = days[0], days[-1]
    out = []
    for t in days:
        for lead in LEADS:
            if t + pd.Timedelta(days=lead - 1) <= hi:
                out.append((t, lead))
    assert all(t >= lo for t, _ in out)
    return out


def coverage(
    peak: pd.Timestamp,
    forcing_last: pd.Timestamp,
    ops_inits: set[pd.Timestamp] | None = None,
) -> tuple[str | None, str]:
    """``(source, reason)``: source is ``"reforecast"``, ``"operational"`` or ``None`` with the reason."""
    days = window_days(peak)
    t0, t1 = days[0], days[-1]
    if t1 > forcing_last:
        return None, f"después del forzante ERA5 (hasta {forcing_last:%Y-%m-%d})"
    if t0 >= REFORECAST_FIRST_VALID and t1 <= REFORECAST_LAST_VALID:
        return "reforecast", ""
    if t1 < REFORECAST_FIRST_VALID:
        return (
            None,
            f"antes del reforecast GEFSv12 (válido desde {REFORECAST_FIRST_VALID:%Y-%m-%d})",
        )
    if t0 < REFORECAST_FIRST_VALID:
        return None, "la ventana empieza antes del reforecast GEFSv12 (2000-01-10)"
    if t0 < OPS_FIRST_INIT:
        return None, (
            f"hueco sin pronóstico: el reforecast termina el {REFORECAST_LAST_VALID:%Y-%m-%d} y el "
            f"archivo operativo pgrb2sp25 empieza el {OPS_FIRST_INIT:%Y-%m-%d}"
        )
    need = {pd.Timestamp(d) for d in days}
    have = ops_inits or set()
    missing = sorted(need - have)
    if missing:
        return (
            None,
            f"archivo operativo sin descargar o incompleto ({len(missing)} de {len(need)} días)",
        )
    return "operational", ""


def station_floods(
    df: pd.DataFrame,
    station_id: int,
    forcing_last: pd.Timestamp,
    ops_inits: set[pd.Timestamp] | None = None,
) -> pd.DataFrame:
    """All annual maxima of a station with ``large`` and the forecast coverage of each."""
    maxima, _ = extremes.annual_maxima(df)
    if maxima.empty:
        return pd.DataFrame(
            columns=[
                "station_id",
                "hydro_year",
                "peak_date",
                "q_peak_m3s",
                "large",
                "source",
                "reason",
            ]
        )
    med = float(np.median(maxima["q_m3s"]))
    rows = []
    for r in maxima.itertuples():
        src, reason = coverage(pd.Timestamp(r.date), forcing_last, ops_inits)
        rows.append(
            {
                "station_id": int(station_id),
                "hydro_year": int(r.hydro_year),
                "peak_date": pd.Timestamp(r.date),
                "q_peak_m3s": float(r.q_m3s),
                "large": bool(r.q_m3s >= med),
                "median_annual_max_m3s": med,
                "source": src,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


# --- forecast tables --------------------------------------------------------------------------


class ForecastTable:
    """Daily station-box precipitation of the members, keyed by ``(station, init, lead)``.

    Rows are ``station_id, init_date, lead, valid_date, member, precip_mm``. The lead convention is
    checked on construction (``valid_date == init_date + lead - 1``). ``get`` returns only the row of the
    run issued on the given day, so a later init can never feed an earlier issue day.
    """

    COLUMNS = ("station_id", "init_date", "lead", "valid_date", "member", "precip_mm")

    def __init__(self, df: pd.DataFrame, members: Sequence[str] = MEMBERS):
        missing = set(self.COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"forecast table lacks columns {sorted(missing)}")
        init = pd.to_datetime(df["init_date"]).dt.normalize()
        valid = pd.to_datetime(df["valid_date"]).dt.normalize()
        bad = valid != init + pd.to_timedelta(df["lead"].astype(int) - 1, unit="D")
        if bad.any():
            raise ValueError(f"{int(bad.sum())} rows break valid_date = init_date + lead - 1")
        self.members = tuple(members)
        self._d: dict[tuple[int, pd.Timestamp, int], np.ndarray] = {}
        col = {m: i for i, m in enumerate(self.members)}
        arr: dict[tuple[int, pd.Timestamp, int], np.ndarray] = {}
        for sid, i, lead, m, p in zip(
            df["station_id"].astype(int),
            init,
            df["lead"].astype(int),
            df["member"],
            df["precip_mm"].astype(float),
            strict=True,
        ):
            if m not in col:
                continue
            a = arr.setdefault((sid, i, lead), np.full(len(self.members), np.nan))
            a[col[m]] = p
        self._d = {k: v for k, v in arr.items() if np.isfinite(v).all()}

    def get(self, station_id: int, issue: pd.Timestamp, lead: int) -> np.ndarray | None:
        """Member totals (mm) of the lead of the run issued on ``issue``; ``None`` if incomplete."""
        return self._d.get((int(station_id), pd.Timestamp(issue).normalize(), int(lead)))

    def has_all(self, station_id: int, peak: pd.Timestamp) -> bool:
        return all(self.get(station_id, t, lead) is not None for t, lead in needed_pairs(peak))

    def inputs_for_issue(self, station_id: int, issue: pd.Timestamp) -> dict[int, np.ndarray]:
        """``{lead: members}`` for every lead of the run of ``issue`` (valid day = issue + lead - 1)."""
        out = {}
        for lead in LEADS:
            a = self.get(station_id, issue, lead)
            if a is not None:
                out[lead] = a
        return out


def box_weights(lat, lon, box) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(ilat, ilon, w)``: cells with centre inside ``box`` and cos(lat) weights summing to 1."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    ilat, ilon = forcing.box_cells(lat, lon, box)
    w = np.cos(np.radians(lat[ilat]))[:, None] * np.ones((1, len(ilon)))
    return ilat, ilon, w / w.sum()


def box_mean_grid(arr: np.ndarray, ilat, ilon, w) -> np.ndarray:
    """Weighted mean over the last two axes (lat, lon) of ``arr`` restricted to the box cells."""
    sub = np.asarray(arr)[..., np.asarray(ilat)[:, None], np.asarray(ilon)[None, :]]
    return (sub * w).sum(axis=(-2, -1))


def load_reforecast(
    zarr_path: Path | str, needs: dict[int, Iterable[pd.Timestamp]], boxes=BOXES
) -> pd.DataFrame:
    """Station-box daily totals of the reforecast for the valid days in ``needs`` (station -> days).

    Entries with ``status != 0`` (not published) are dropped. Columns of :class:`ForecastTable`.
    """
    import xarray as xr

    ds = xr.open_zarr(zarr_path, consolidated=False)
    all_days = sorted({pd.Timestamp(d).normalize() for v in needs.values() for d in v})
    valid = pd.DatetimeIndex(ds["valid_date"].values).normalize()
    idx = np.flatnonzero(valid.isin(all_days))
    if not len(idx):
        return pd.DataFrame(columns=list(ForecastTable.COLUMNS))
    sub = ds.isel(case=idx)
    precip = np.asarray(sub["precip_mm"].values, dtype=float)  # (case, lead, member, lat, lon)
    status = np.asarray(sub["status"].values)  # (case, lead, member)
    init = np.asarray(sub["init_date"].values)  # (case, lead)
    members = [str(m) for m in sub["member"].values]
    leads = [int(x) for x in sub["lead"].values]
    case_valid = valid[idx]
    out = []
    for sid, box in boxes.items():
        if sid not in needs:
            continue
        want = {pd.Timestamp(d).normalize() for d in needs[sid]}
        ilat, ilon, w = box_weights(sub["lat"].values, sub["lon"].values, box)
        series = box_mean_grid(precip, ilat, ilon, w)  # (case, lead, member)
        for ci, v in enumerate(case_valid):
            if v not in want:
                continue
            for li, lead in enumerate(leads):
                for mi, m in enumerate(members):
                    if status[ci, li, mi] != 0 or not np.isfinite(series[ci, li, mi]):
                        continue
                    out.append(
                        (
                            sid,
                            pd.Timestamp(init[ci, li]).normalize(),
                            lead,
                            v,
                            m,
                            float(series[ci, li, mi]),
                        )
                    )
    return pd.DataFrame(out, columns=list(ForecastTable.COLUMNS))


# --- operational archive ----------------------------------------------------------------------


def ops_paths(out_dir: Path | str, init: date | pd.Timestamp) -> tuple[Path, Path]:
    stem = pd.Timestamp(init).strftime("%Y%m%d")
    d = Path(out_dir)
    return d / f"{stem}.parquet", d / f"{stem}.json"


def ops_inits_available(out_dir: Path | str, days: Iterable[pd.Timestamp] | None = None) -> set:
    """Init days with a cached parquet that has all 5 members for lead 1."""
    d = Path(out_dir)
    if not d.is_dir():
        return set()
    wanted = None if days is None else {pd.Timestamp(x).normalize() for x in days}
    out = set()
    for p in d.glob("*.parquet"):
        try:
            day = pd.Timestamp(p.stem)
        except ValueError:
            continue
        if wanted is not None and day not in wanted:
            continue
        side = p.with_suffix(".json")
        if side.is_file() and json.loads(side.read_text()).get("status") == "ok":
            out.add(day)
    return out


def read_ops_table(out_dir: Path | str, days: Iterable[pd.Timestamp]) -> pd.DataFrame:
    frames = []
    for day in sorted({pd.Timestamp(x).normalize() for x in days}):
        p, _ = ops_paths(out_dir, day)
        if p.is_file():
            frames.append(pd.read_parquet(p))
    if not frames:
        return pd.DataFrame(columns=list(ForecastTable.COLUMNS))
    return pd.concat(frames, ignore_index=True)


def flood_inits(peaks: Iterable[pd.Timestamp]) -> list[pd.Timestamp]:
    """Distinct issue days of the windows peak-15..peak+15 (operational years only)."""
    days: set[pd.Timestamp] = set()
    for p in peaks:
        days.update(pd.Timestamp(d) for d in window_days(p))
    return sorted(d for d in days if d >= OPS_FIRST_INIT)


def _fetch_one(fetcher, init: date, member: str, step: int, area, boxes, retries: int, wait: float):
    from clima_nqn.ops.ingest import NotAvailable, box_means

    last: Exception | None = None
    for attempt in range(retries):
        try:
            field = fetcher(init, member, step, area)
            return box_means(field, boxes)
        except NotAvailable as exc:
            return exc  # not published: no retry
        except Exception as exc:  # noqa: BLE001 - network, grib and idx errors are recorded, not fatal
            last = exc
            time.sleep(wait * (2**attempt))
    return last


def fetch_init(
    init: date | pd.Timestamp,
    out_dir: Path | str,
    boxes=BOXES,
    workers: int = 16,
    members: Sequence[str] = MEMBERS,
    steps: Sequence[int] = STEPS,
    fetcher: Callable | None = None,
    retries: int = 3,
    wait: float = 1.0,
    refresh: bool = False,
    retry_missing: bool = False,
) -> dict:
    """Download one operational init into the cache (idempotent); returns the sidecar dict."""
    from clima_nqn.ops import ingest

    fetcher = fetcher or ingest.fetch_gefs25_apcp
    day = pd.Timestamp(init).normalize()
    pq_path, js_path = ops_paths(out_dir, day)
    if pq_path.is_file() and js_path.is_file() and not refresh:
        side = json.loads(js_path.read_text())
        if not (retry_missing and side.get("n_missing_errors", 0) > 0):
            return side
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    area = ingest.union_area(boxes)
    jobs = [(m, s) for m in members for s in steps]

    def one(job):
        return job, _fetch_one(fetcher, day.date(), job[0], job[1], area, boxes, retries, wait)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = dict(pool.map(one, jobs))
    missing, errors = [], 0
    for (m, s), v in got.items():
        if isinstance(v, ingest.NotAvailable):
            missing.append({"member": m, "step": s, "reason": "not published"})
        elif isinstance(v, Exception):
            errors += 1
            missing.append({"member": m, "step": s, "reason": f"{type(v).__name__}: {v}"[:200]})
    rows = []
    for m in members:
        for lead in LEADS:
            ends = [e for e in steps if 24 * (lead - 1) < e <= 24 * lead]
            if len(ends) != 4 or any(isinstance(got[(m, e)], Exception | type(None)) for e in ends):
                continue
            for sid in boxes:
                rows.append(
                    {
                        "station_id": int(sid),
                        "init_date": day,
                        "lead": lead,
                        "valid_date": day + pd.Timedelta(days=lead - 1),
                        "member": m,
                        "precip_mm": ingest.daily_from_buckets(
                            {e: got[(m, e)][sid] for e in ends}, lead
                        ),
                    }
                )
    df = pd.DataFrame(rows, columns=list(ForecastTable.COLUMNS))
    status = "ok" if len(df) else "absent"
    side = {
        "init": f"{day:%Y-%m-%d}",
        "status": status,
        "n_files": len(jobs),
        "n_missing": len(missing),
        "n_missing_errors": errors,
        "missing": missing,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "NOAA GEFS operational 0.25 deg pgrb2sp25, 00 UTC (noaa-gefs-pds), APCP 6 h buckets",
    }
    tmp = pq_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(pq_path)
    js_path.write_text(json.dumps(side, indent=1))
    return side

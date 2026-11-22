"""F5.5: ERA5 analogs of every F1.3 atmospheric-river event, and what happened on those days.

Rules (fixed by the user on 2026-11-22, before running):

- library: daily IVT components = mean of the 00/06/12/18 UTC values of ARCO ``viwve``/``viwvn`` over ``era5.NEUQUEN_BOX``
  (0.25 deg), 1980..2025 (whatever ARCO holds for the last year);
- target: the UTC day of ``ivt_max_time`` of each event (same rule as ``cases.event_cases`` of F5.1);
- distance: Euclidean on anomalies (day-of-year climatology of the library, +-15 day window) of (viwve, viwvn), each cell
  weighted by sqrt(cos(lat)); candidates are the days within +-30 days of the target's day of year in any year (wrapping
  across New Year), excluding +-15 days around the target; greedy one analog per system (no two chosen within +-3 days); k = 10;
- outcomes per analog day: the F1.3 event it touches ([start, end) by day), box maximum of the daily |IVT|, regional rain of
  the 3 F5.3 regions from IMERG (2000-06..2025-09) and from ERA5 (``reports/05/F5.3-obs.csv``, 2000..2019); outside those
  periods the value is ``None`` ("sin dato");
- baseline: k = 10 random days from the same pool (same window, exclusion and one-per-system rule), seed 20261122; the
  fraction of AR days and the mean regional rain of analogs vs baseline carry a 95 % bootstrap CI over events (1000, seed 0).

Pure numpy/pandas helpers are tested on synthetic data; the ARCO fetch reuses ``era5.fetch_month``.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.io import era5
from clima_nqn.stages.hindcast import cases as cases_mod
from clima_nqn.stages.hindcast import verify as v

K = 10
WINDOW_DAYS = 30  # candidate day-of-year distance to the target
EXCLUDE_DAYS = 15  # absolute-date exclusion around the target
SEPARATION_DAYS = 3  # two chosen days must be farther apart than this (one per system)
CLIM_HALF_DAYS = 15
BASELINE_SEED = 20261122
N_BOOT = 1000
BOOT_SEED = 0
HOURS = (0, 6, 12, 18)
LIB_VARIABLES = {
    "vertical_integral_of_eastward_water_vapour_flux": "viwve",
    "vertical_integral_of_northward_water_vapour_flux": "viwvn",
}
LIB_FIRST_YEAR, LIB_LAST_YEAR = 1980, 2025
REGIONS = ("cordillera_norte", "cordillera_sur", "confluencia")
SOURCES = ("imerg", "era5")
SOURCE = "ERA5 (Copernicus) vía ARCO-ERA5; IMERG Final V07 (NASA)"
LICENSE = "CC BY 4.0"
IMERG_PERIOD = ("2000-06-01", "2025-09-30")
ERA5_RAIN_PERIOD = ("2000-01-01", "2019-12-31")
MIN_IMERG_COVERAGE = 0.5  # regions less covered by the IMERG box get imerg = null
IMERG_NO_COVER = "IMERG no cubre la región"
LIBRARY_NAME = "era5-ivt-daily.zarr"
STEP_HOURS = 0.5  # IMERG half-hourly rate in mm/h
IMERG_BBOX = (
    (-40.0, -37.5),
    (-70.0, -67.0),
)  # store bbox (lat, lon); the cordillera lies mostly west of it


# --- day of year and climatology -------------------------------------------------------------------------------


def doy365(dates) -> np.ndarray:
    """Day of year on a 365-day calendar: 29 February counts as 28 February, later leap-year days shift by one."""
    d = pd.DatetimeIndex(pd.to_datetime(np.asarray(dates)))
    doy = np.asarray(d.day_of_year, dtype="int64")
    leap = np.asarray(d.is_leap_year)
    after_feb = np.asarray(d.month) > 2
    doy = np.where(leap & after_feb, doy - 1, doy)
    return np.where(leap & (np.asarray(d.month) == 2) & (np.asarray(d.day) == 29), 59, doy)


def circular_distance(a, b, period: int = 365) -> np.ndarray:
    diff = np.abs(np.asarray(a) - np.asarray(b))
    return np.minimum(diff, period - diff)


def climatology(values: np.ndarray, dates, half: int = CLIM_HALF_DAYS) -> np.ndarray:
    """Day-of-year mean (365 rows) of ``values`` (time first), over all years and a +-``half`` day circular window."""
    x = np.asarray(values, dtype="float64")
    doy = doy365(dates) - 1
    if len(doy) != len(x):
        raise ValueError("values and dates differ in length")
    valid = ~np.isnan(x)
    sums = np.zeros((365,) + x.shape[1:])
    counts = np.zeros((365,) + x.shape[1:])
    np.add.at(sums, doy, np.where(valid, x, 0.0))
    np.add.at(counts, doy, valid.astype("float64"))
    s_win = np.zeros_like(sums)
    c_win = np.zeros_like(counts)
    for shift in range(-half, half + 1):
        s_win += np.roll(sums, shift, axis=0)
        c_win += np.roll(counts, shift, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(c_win > 0, s_win / c_win, np.nan)


def anomalies(values: np.ndarray, dates, clim: np.ndarray) -> np.ndarray:
    """``values`` minus the climatology of their day of year."""
    return np.asarray(values, dtype="float64") - clim[doy365(dates) - 1]


# --- search -------------------------------------------------------------------------------------------------------


def candidate_mask(
    dates, target, window: int = WINDOW_DAYS, exclude: int = EXCLUDE_DAYS
) -> np.ndarray:
    """Days within +-``window`` of the target's day of year (any year, wrapping New Year), minus +-``exclude`` days around it."""
    d = pd.DatetimeIndex(pd.to_datetime(np.asarray(dates)))
    t = pd.Timestamp(target)
    near_doy = circular_distance(doy365(d), doy365([t])[0]) <= window
    gap = np.abs((d - t) / pd.Timedelta(days=1))
    return near_doy & (np.asarray(gap) > exclude)


def target_position(dates, target) -> int:
    d = pd.DatetimeIndex(pd.to_datetime(np.asarray(dates)))
    t = pd.Timestamp(target).normalize()
    loc = d.get_indexer([t])[0]
    if loc < 0:
        raise ValueError(f"target {t:%Y-%m-%d} is not in the library")
    return int(loc)


def greedy_separated(order: Iterable[int], dates, k: int, sep: int = SEPARATION_DAYS) -> list[int]:
    """Walk ``order`` (positions) and keep a day only if no kept day lies within ``sep`` days; stop at ``k``."""
    d = pd.DatetimeIndex(pd.to_datetime(np.asarray(dates)))
    day = np.asarray((d - d[0]) / pd.Timedelta(days=1)).round().astype("int64")
    kept: list[int] = []
    for pos in order:
        if all(abs(int(day[pos]) - int(day[q])) > sep for q in kept):
            kept.append(int(pos))
            if len(kept) >= k:
                break
    return kept


def find_analogs(
    feat: np.ndarray,
    dates,
    target_pos: int,
    k: int = K,
    window: int = WINDOW_DAYS,
    exclude: int = EXCLUDE_DAYS,
    sep: int = SEPARATION_DAYS,
) -> list[tuple[int, float]]:
    """Up to ``k`` (library position, distance) pairs, nearest first. ``feat`` (time, D) holds weighted anomalies."""
    pool = candidate_mask(dates, dates[target_pos], window, exclude)
    cand = np.flatnonzero(pool)
    diff = feat[cand].astype("float64") - feat[target_pos].astype("float64")
    dist = np.sqrt((diff * diff).sum(axis=1))
    ok = np.isfinite(dist)
    cand, dist = cand[ok], dist[ok]
    order = np.argsort(dist, kind="stable")
    kept = greedy_separated(cand[order], dates, k, sep)
    by_pos = dict(zip(cand.tolist(), dist.tolist(), strict=True))
    return [(p, float(by_pos[p])) for p in kept]


def baseline_days(
    dates,
    target_pos: int,
    k: int = K,
    seed: int = BASELINE_SEED,
    salt: int = 0,
    window: int = WINDOW_DAYS,
    exclude: int = EXCLUDE_DAYS,
    sep: int = SEPARATION_DAYS,
) -> list[int]:
    """``k`` random library positions from the target's pool (same exclusions as the analogs). Reproducible per ``(seed, salt)``."""
    pool = np.flatnonzero(candidate_mask(dates, dates[target_pos], window, exclude))
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), int(salt)]))
    order = pool[rng.permutation(len(pool))]
    return greedy_separated(order, dates, k, sep)


# --- outcomes -------------------------------------------------------------------------------------------------------


def _naive(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s)
    return s.dt.tz_convert("UTC").dt.tz_localize(None) if s.dt.tz is not None else s


def touching_event(day, events: pd.DataFrame) -> str | None:
    """Id of the first (by start) event whose ``[start, end)`` overlaps the UTC day, else ``None``."""
    d0 = pd.Timestamp(day).normalize()
    d1 = d0 + pd.Timedelta(days=1)
    start, end = _naive(events["start"]), _naive(events["end"])
    hit = events.loc[(start < d1) & (end > d0)]
    if hit.empty:
        return None
    first = hit.assign(_s=start[hit.index]).sort_values(["_s", "event_id"]).iloc[0]
    return str(first["event_id"])


def _num(x, nd: int = 2):
    if x is None:
        return None
    x = float(x)
    return round(x, nd) + 0.0 if np.isfinite(x) else None


def rain_for_day(day, table: pd.DataFrame, regions: Iterable[str] = REGIONS) -> dict:
    """``{region: {imerg, era5}}`` mm/day for a UTC day; ``None`` when the day or the value is not in ``table``."""
    d = pd.Timestamp(day).normalize()
    row = table.loc[d] if d in table.index else None
    out: dict[str, dict] = {}
    for r in regions:
        out[r] = {
            src: _num(row[f"{src}_{r}"]) if row is not None and f"{src}_{r}" in row.index else None
            for src in SOURCES
        }
    return out


def imerg_usable(
    coverage: dict[str, float], minimum: float = MIN_IMERG_COVERAGE
) -> dict[str, bool]:
    return {r: coverage.get(r, 0.0) >= minimum for r in REGIONS}


def drop_uncovered_imerg(rain: pd.DataFrame, coverage: dict[str, float]) -> pd.DataFrame:
    """Remove ``imerg_<region>`` columns of regions the IMERG box covers less than ``MIN_IMERG_COVERAGE``."""
    bad = [f"imerg_{r}" for r, ok in imerg_usable(coverage).items() if not ok]
    return rain.drop(columns=[c for c in bad if c in rain.columns])


def load_rain(imerg_csv: Path | None, era5_csv: Path | None) -> pd.DataFrame:
    """Daily regional rain table indexed by UTC date; columns ``imerg_<region>`` and ``era5_<region>`` (mm/day)."""
    parts = []
    if imerg_csv is not None and Path(imerg_csv).exists():
        im = pd.read_csv(imerg_csv, index_col="date", parse_dates=True)
        im = im.rename(columns={f"{r}_mm": f"imerg_{r}" for r in REGIONS})
        parts.append(im[[f"imerg_{r}" for r in REGIONS if f"imerg_{r}" in im]])
    if era5_csv is not None and Path(era5_csv).exists():
        er = pd.read_csv(era5_csv, index_col="date", parse_dates=True)
        er = er.rename(columns={f"{r}_tp_mm": f"era5_{r}" for r in REGIONS})
        parts.append(er[[f"era5_{r}" for r in REGIONS if f"era5_{r}" in er]])
    if not parts:
        return pd.DataFrame(columns=[f"{s}_{r}" for s in SOURCES for r in REGIONS])
    return pd.concat(parts, axis=1).sort_index()


# --- IMERG daily regional means ----------------------------------------------------------------------------------------


def imerg_daily_regional(
    precip,
    time_index,
    lat,
    lon,
    masks: dict[str, np.ndarray],
    chunk_steps: int = 48 * 200,
    step_hours: float = STEP_HOURS,
) -> pd.DataFrame:
    """UTC daily regional rain (mm) from half-hourly IMERG rates (mm/h), cos(lat)-weighted over each region mask.

    ``precip`` is indexable on its first (time) axis; each half-hour contributes ``rate * step_hours``. A day with any missing
    half-hour (or fewer than 24 / ``step_hours`` steps) is NaN. Columns ``<region>_mm``.
    """
    t = pd.DatetimeIndex(pd.to_datetime(np.asarray(time_index)))
    w_lat = np.cos(np.deg2rad(np.asarray(lat, dtype="float64")))[:, None]
    weights = {r: np.where(m, w_lat, 0.0) for r, m in masks.items()}
    per_step = {r: np.full(len(t), np.nan) for r in masks}
    for i in range(0, len(t), chunk_steps):
        block = np.asarray(precip[i : i + chunk_steps], dtype="float64")
        ok = np.isfinite(block)
        filled = np.where(ok, block, 0.0)
        for r, w in weights.items():
            den = (ok * w).sum(axis=(1, 2))
            num = (filled * w).sum(axis=(1, 2))
            with np.errstate(invalid="ignore", divide="ignore"):
                per_step[r][i : i + len(block)] = np.where(den > 0, num / den, np.nan)
    frame = pd.DataFrame(per_step, index=t)
    per_day = round(24 / step_hours)
    day = frame.index.floor("D")
    sums = frame.groupby(day).sum(min_count=1) * step_hours
    counts = frame.notna().groupby(day).sum()
    sums = sums.where(counts >= per_day)
    sums.index.name = "date"
    return sums.rename(columns={r: f"{r}_mm" for r in masks})


def box_coverage(
    lat_range: tuple[float, float], lon_range: tuple[float, float], step: float = 0.05
) -> dict[str, float]:
    """Share of each F5.3 region (cos(lat)-weighted, 0.05 deg cells) that lies inside the given box (IMERG store bbox)."""
    from clima_nqn.stages.hindcast import riskday as rd

    lat = np.round(np.arange(-43.0, -34.0 + 1e-9, step), 4)
    lon = np.round(np.arange(-74.0, -66.0 + 1e-9, step), 4)
    masks = rd.regions(lat, lon)
    w = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, len(lon)))
    inside = ((lat >= lat_range[0]) & (lat <= lat_range[1]))[:, None] & (
        (lon >= lon_range[0]) & (lon <= lon_range[1])
    )[None, :]
    return {
        r: float((m & inside).astype(float).__mul__(w).sum() / max((m * w).sum(), 1e-12))
        for r, m in masks.items()
    }


# --- library -------------------------------------------------------------------------------------------------------------


def daily_mean(hourly: xr.Dataset, per_day: int = len(HOURS)) -> xr.Dataset:
    """Daily mean of the sub-daily steps; a day with fewer than ``per_day`` steps is NaN."""
    counts = hourly[next(iter(hourly.data_vars))].resample(time="1D").count()
    out = hourly.resample(time="1D").mean(skipna=False)
    out = out.where(counts.isel(lat=0, lon=0, drop=True) >= per_day)
    return out.astype("float32")


def _expected_days(year: int, months: Iterable[int]) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        sorted(
            d
            for m in months
            for d in pd.date_range(
                pd.Timestamp(year, m, 1),
                pd.Timestamp(year, m, 1) + pd.offsets.MonthEnd(0),
                freq="D",
            )
        )
    )


def _available_months(year: int, opener: era5.Opener) -> list[int]:
    """Months of ``year`` that ARCO holds at least for day 1 (the last year may be partial)."""
    raw = opener()
    last = pd.Timestamp(raw["time"].values[-1])
    return [m for m in range(1, 13) if pd.Timestamp(year, m, 1) <= last]


def fetch_library_year(
    year: int,
    out_dir: Path,
    opener: era5.Opener = era5.open_arco,
    area=era5.NEUQUEN_BOX,
    workers: int = era5.DEFAULT_WORKERS,
    retries: int = 3,
    retry_wait: float = 60,
    months: Iterable[int] | None = None,
) -> Path:
    """Fetch one year at 00/06/12/18 UTC, average to days and write ``<out_dir>/<year>.zarr`` (atomic)."""
    out_dir = Path(out_dir)
    months = list(months) if months is not None else _available_months(year, opener)
    if not months:
        raise ValueError(f"ARCO holds no data for {year}")
    target = out_dir / f"{year}.zarr"
    if target.exists():
        try:
            have = xr.open_zarr(target, consolidated=False, chunks=None)
            if have["time"].values.tolist() == _expected_days(
                year, months
            ).values.tolist() and bool(have["viwve"].isel(time=-1).notnull().any()):
                print(f"skip {target} (complete)", flush=True)
                return target
        except Exception:  # noqa: BLE001,S110 - unreadable store counts as incomplete
            pass
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"{year}.zarr.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    parts = []
    started = time.monotonic()
    for month in months:
        t0 = time.monotonic()
        ds = era5.fetch_month(
            year, month, HOURS, area, opener, retries, retry_wait, workers, variables=LIB_VARIABLES
        )
        parts.append(daily_mean(ds))
        print(
            f"{year}-{month:02d}: {ds.sizes['time']} steps in {time.monotonic() - t0:.1f}s",
            flush=True,
        )
    out = xr.concat(parts, dim="time")
    out.attrs = {
        "title": "Daily IVT components, ERA5 over Neuquén",
        "source": era5.SOURCE,
        "license": era5.LICENSE,
        "period": f"{out['time'].values[0].astype('datetime64[D]')} to {out['time'].values[-1].astype('datetime64[D]')}",
        "method": "daily mean of 00/06/12/18 UTC viwve, viwvn (kg m-1 s-1)",
        "area": f"N={area[0]:g} W={area[1]:g} S={area[2]:g} E={area[3]:g}",
    }
    enc = {
        "time": {"units": "days since 1900-01-01", "dtype": "int64"},
        **{
            n: {
                "dtype": "float32",
                "chunks": (min(366, out.sizes["time"]), out.sizes["lat"], out.sizes["lon"]),
            }
            for n in out.data_vars
        },
    }
    out.to_zarr(tmp, mode="w", consolidated=False, encoding=enc)
    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)
    print(
        f"wrote {target}: {out.sizes['time']} days in {time.monotonic() - started:.0f}s", flush=True
    )
    return target


def combine_library(in_dir: Path, out: Path) -> Path:
    """Concatenate ``<year>.zarr`` stores into one daily library (checks that grids agree and days are contiguous)."""
    in_dir, out = Path(in_dir), Path(out)
    paths = sorted(p for p in in_dir.glob("[0-9][0-9][0-9][0-9].zarr") if p.is_dir())
    if not paths:
        raise FileNotFoundError(f"no <year>.zarr stores in {in_dir}")
    ds = xr.concat(
        [xr.open_zarr(p, consolidated=False, chunks=None).load() for p in paths], dim="time"
    )
    ds = ds.sortby("time")
    days = pd.DatetimeIndex(ds["time"].values)
    full = pd.date_range(days[0], days[-1], freq="D")
    missing = full.difference(days)
    if len(missing):
        raise ValueError(f"library has {len(missing)} missing days, first {missing[0]:%Y-%m-%d}")
    ds.attrs = {
        **xr.open_zarr(paths[0], consolidated=False, chunks=None).attrs,
        "period": f"{days[0]:%Y-%m-%d} to {days[-1]:%Y-%m-%d}",
        "n_days": len(days),
    }
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    enc = {
        "time": {"units": "days since 1900-01-01", "dtype": "int64"},
        **{
            n: {"dtype": "float32", "chunks": (366, ds.sizes["lat"], ds.sizes["lon"])}
            for n in ds.data_vars
        },
    }
    ds.to_zarr(tmp, mode="w", consolidated=False, encoding=enc)
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    print(f"wrote {out}: {len(paths)} years, {days[0]:%Y-%m-%d} .. {days[-1]:%Y-%m-%d}", flush=True)
    return out


def library_features(ds: xr.Dataset) -> dict:
    """Weighted anomaly matrix (time, 2 * ny * nx) float32 plus daily box-max |IVT| and the dates."""
    dates = pd.DatetimeIndex(ds["time"].values)
    u = ds["viwve"].values.astype("float64")
    w = ds["viwvn"].values.astype("float64")
    stack = np.stack([u, w], axis=1)  # (T, 2, ny, nx)
    flat = stack.reshape(len(dates), -1)
    clim = climatology(flat, dates)
    anom = anomalies(flat, dates, clim).reshape(stack.shape)
    sw = np.sqrt(np.cos(np.deg2rad(ds["lat"].values.astype("float64"))))[None, None, :, None]
    feat = (anom * sw).reshape(len(dates), -1).astype("float32")
    ivt_max = np.hypot(u, w).max(axis=(1, 2))
    return {"dates": dates, "feat": feat, "ivt_daily_max": ivt_max}


# --- run ------------------------------------------------------------------------------------------------------------------


def _mean_or_none(values: list) -> float | None:
    vals = [x for x in values if x is not None]
    return float(np.mean(vals)) if vals else None


def summarize_days(days: list[dict], regions: Iterable[str] = REGIONS) -> dict:
    """AR fraction and mean regional rain (over the days that have data) of a list of day records."""
    rain = {
        r: {src: _num(_mean_or_none([d["rain"][r][src] for d in days])) for src in SOURCES}
        for r in regions
    }
    n_ar = sum(1 for d in days if d["ar_event_id"] is not None)
    return {
        "n_days": len(days),
        "ar_fraction": _num(n_ar / len(days), 4) if days else None,
        "ivt_max_mean": _num(_mean_or_none([d["ivt_max"] for d in days]), 1),
        "rain": rain,
    }


def _boot(values: np.ndarray, n_boot: int, seed: int) -> tuple[float | None, float | None]:
    lo, hi = v.bootstrap_ci(
        lambda idx: float(np.mean(values[idx])), np.arange(len(values)), n_boot, seed
    )
    return (_num(lo, 4), _num(hi, 4)) if np.isfinite(lo) else (None, None)


def _paired(a: np.ndarray, b: np.ndarray, n_boot: int, seed: int) -> dict:
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) == 0:
        return {
            "n_events": 0,
            "analogs": None,
            "baseline": None,
            "diff": None,
            "analogs_ci": [None, None],
            "baseline_ci": [None, None],
            "diff_ci": [None, None],
        }
    return {
        "n_events": len(a),
        "analogs": _num(a.mean(), 4),
        "baseline": _num(b.mean(), 4),
        "diff": _num((a - b).mean(), 4),
        "analogs_ci": list(_boot(a, n_boot, seed)),
        "baseline_ci": list(_boot(b, n_boot, seed)),
        "diff_ci": list(_boot(a - b, n_boot, seed)),
    }


def _pair(
    records: list[dict], getter: Callable[[dict], float | None]
) -> tuple[np.ndarray, np.ndarray]:
    def val(rec, key):
        x = getter(rec[key])
        return np.nan if x is None else float(x)

    return (
        np.array([val(r, "analog_summary") for r in records]),
        np.array([val(r, "baseline") for r in records]),
    )


def compare(
    records: list[dict],
    regions: Iterable[str] = REGIONS,
    n_boot: int = N_BOOT,
    seed: int = BOOT_SEED,
) -> dict:
    """Analogs vs baseline over events: AR fraction and regional rain, mean, difference and 95 % CI (bootstrap of events)."""
    a, b = _pair(records, lambda s: s["ar_fraction"])
    out = {"ar_fraction": _paired(a, b, n_boot, seed), "rain": {}}
    for r in regions:
        out["rain"][r] = {}
        for src in SOURCES:
            a, b = _pair(records, lambda s, r=r, src=src: s["rain"][r][src])
            out["rain"][r][src] = _paired(a, b, n_boot, seed)
    return out


def _day_record(
    pos: int, lib: dict, events: pd.DataFrame, rain: pd.DataFrame, distance: float | None, rank: int
) -> dict:
    day = lib["dates"][pos]
    return {
        "rank": rank,
        "date": f"{day:%Y-%m-%d}",
        "distance": _num(distance, 3),
        "ar_event_id": touching_event(day, events),
        "ivt_max": _num(lib["ivt_daily_max"][pos], 1),
        "rain": rain_for_day(day, rain),
    }


def build_records(
    lib: dict,
    events: pd.DataFrame,
    rain: pd.DataFrame,
    k: int = K,
    seed: int = BASELINE_SEED,
    progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """One record per event: analogs, baseline days and their summaries (see module docstring)."""
    targets = cases_mod.event_cases(events)
    targets = targets.sort_values("case_id", kind="stable").reset_index(drop=True)
    ev_ivt = dict(zip(events["event_id"].astype(str), events["ivt_max"].astype(float), strict=True))
    records = []
    for i, row in targets.iterrows():
        t = target_position(lib["dates"], row["valid_date"])
        analog_days = [
            _day_record(p, lib, events, rain, d, rank + 1)
            for rank, (p, d) in enumerate(find_analogs(lib["feat"], lib["dates"], t, k))
        ]
        base_days = [
            _day_record(p, lib, events, rain, None, rank + 1)
            for rank, p in enumerate(baseline_days(lib["dates"], t, k, seed, salt=int(i)))
        ]
        records.append(
            {
                "event_id": str(row["case_id"]),
                "date": f"{lib['dates'][t]:%Y-%m-%d}",
                "ivt_max": _num(ev_ivt[str(row["case_id"])], 1),
                "ivt_daily_max": _num(lib["ivt_daily_max"][t], 1),
                "analogs": analog_days,
                "analog_summary": summarize_days(analog_days),
                "baseline_days": base_days,
                "baseline": summarize_days(base_days),
            }
        )
        if progress:
            progress(int(i) + 1, len(targets))
    return records


METHOD = {
    "library": "media diaria de 00/06/12/18 UTC de viwve y viwvn (ERA5, ARCO-ERA5, 0,25°) en N -34 / W -74 / S -43 / E -66",
    "target": "día UTC del IVT máximo de cada evento F1.3",
    "distance": "euclídea sobre anomalías (climatología del día del año, ventana ±15 días) ponderadas por sqrt(cos(lat))",
    "candidates": "±30 días del día del año del evento en cualquier año; se excluyen ±15 días del evento",
    "one_per_system": "no se eligen dos análogos a ±3 días",
    "k": K,
    "baseline": f"{K} días al azar de la misma época, misma exclusión y misma regla de un día por sistema; semilla {BASELINE_SEED}",
    "bootstrap": f"IC 95 % por percentiles, {N_BOOT} remuestreos de eventos, semilla {BOOT_SEED}",
}


def run(
    library: Path,
    events_path: Path,
    imerg_csv: Path | None,
    era5_csv: Path | None,
    out_dir: Path,
    k: int = K,
    n_boot: int = N_BOOT,
    seed: int = BASELINE_SEED,
) -> dict:
    """Search analogs for every event and write ``analogs.parquet``, ``analogs.json``, ``F5.5.json`` and ``F5.5.md``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ds = xr.open_zarr(library, consolidated=False, chunks=None).load()
    lib = library_features(ds)
    events = pd.read_parquet(events_path)
    coverage = box_coverage(*IMERG_BBOX)
    rain = drop_uncovered_imerg(load_rain(imerg_csv, era5_csv), coverage)
    records = build_records(
        lib,
        events,
        rain,
        k,
        seed,
        progress=lambda i, n: print(f"{i}/{n}", flush=True) if i % 50 == 0 else None,
    )
    summary = compare(records, REGIONS, n_boot=n_boot)
    period = f"{lib['dates'][0]:%Y-%m-%d}/{lib['dates'][-1]:%Y-%m-%d}"
    meta = {
        "id": "hindcast-analogs",
        "source": SOURCE,
        "license": LICENSE,
        "period": period,
        "k": k,
        "regions": list(REGIONS),
        "units": {
            "rain": "mm/día",
            "ivt_max": "kg m-1 s-1",
            "distance": "kg m-1 s-1 (anomalías ponderadas)",
        },
        "imerg_unavailable": {
            r: IMERG_NO_COVER for r, ok in imerg_usable(coverage).items() if not ok
        },
        "imerg_region_coverage": {r: round(c, 3) for r, c in coverage.items()},
        "rain_periods": {"imerg": "/".join(IMERG_PERIOD), "era5": "/".join(ERA5_RAIN_PERIOD)},
        "method": METHOD,
        "n_events": len(records),
        "events_source": str(events_path),
    }
    payload = {
        **meta,
        "summary": summary,
        "events": [{kk: vv for kk, vv in r.items() if kk != "baseline_days"} for r in records],
    }
    write_parquet(records, out_dir / "analogs.parquet")
    (out_dir / "analogs.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    (out_dir / "F5.5.json").write_text(
        json.dumps(
            {**meta, "summary": summary, "coverage": coverage_stats(records)},
            ensure_ascii=False,
            indent=1,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "F5.5.md").write_text(
        render_md(meta, summary, coverage_stats(records)), encoding="utf-8"
    )
    return {"meta": meta, "summary": summary, "n_events": len(records)}


def write_parquet(records: list[dict], path: Path) -> None:
    rows = []
    for rec in records:
        for kind, days in (("analog", rec["analogs"]), ("baseline", rec["baseline_days"])):
            for d in days:
                row = {
                    "event_id": rec["event_id"],
                    "event_date": rec["date"],
                    "kind": kind,
                    "rank": d["rank"],
                    "date": d["date"],
                    "distance": np.nan if d["distance"] is None else d["distance"],
                    "ar_event_id": d["ar_event_id"],
                    "ivt_max": np.nan if d["ivt_max"] is None else d["ivt_max"],
                }
                for r in REGIONS:
                    for src in SOURCES:
                        x = d["rain"][r][src]
                        row[f"{src}_{r}"] = np.nan if x is None else x
                rows.append(row)
    pd.DataFrame(rows).to_parquet(path, index=False)


def coverage_stats(records: list[dict]) -> dict:
    """Share of analog days with data per source and region, and of analogs inside the rain periods."""
    days = [d for r in records for d in r["analogs"]]
    out = {"n_analog_days": len(days)}
    for src in SOURCES:
        out[src] = {
            r: round(sum(1 for d in days if d["rain"][r][src] is not None) / max(len(days), 1), 4)
            for r in REGIONS
        }
    return out


def _fmt(x, nd=2) -> str:
    return "sin dato" if x is None else f"{x:.{nd}f}".replace(".", ",")


def _ci(row: dict, key: str, nd: int = 2) -> str:
    lo, hi = row[key]
    return "—" if lo is None else f"[{_fmt(lo, nd)}; {_fmt(hi, nd)}]"


def render_md(meta: dict, summary: dict, cov: dict) -> str:
    from clima_nqn.stages.hindcast.riskday import REGION_LABELS

    ar = summary["ar_fraction"]
    lines = [
        "# F5.5 — Análogos ERA5 de los eventos de río atmosférico",
        "",
        "Retrospectivo; no es un sistema de alerta oficial. Para avisos vigentes: SMN, AIC y Defensa Civil.",
        "",
        (
            f"Fuente: {meta['source']}. Licencia {meta['license']}. Biblioteca: {meta['period']}. "
            f"Eventos: {meta['n_events']} (catálogo F1.3)."
        ),
        "",
        "## Método",
        "",
        *[f"- {k}: {v}" for k, v in meta["method"].items() if k != "k"],
        f"- k = {meta['k']} análogos por evento.",
        "- Lluvia: IMERG Final V07 "
        + meta["rain_periods"]["imerg"]
        + " y ERA5 (`F5.3-obs.csv`) "
        + meta["rain_periods"]["era5"]
        + '; fuera de esos períodos "sin dato".',
        "",
        "## Análogos contra baseline",
        "",
        (
            "Media sobre eventos (cada evento promedia sus 10 días con dato); IC 95 % por bootstrap de eventos. "
            "La diferencia es análogos menos baseline."
        ),
        "",
        "| Medida | n eventos | Análogos | Baseline | Diferencia | IC 95 % de la diferencia |",
        "|---|---|---|---|---|---|",
        (
            f"| Fracción de días con río atmosférico | {ar['n_events']} | {_fmt(ar['analogs'], 3)} | "
            f"{_fmt(ar['baseline'], 3)} | {_fmt(ar['diff'], 3)} | {_ci(ar, 'diff_ci', 3)} |"
        ),
    ]
    for r in REGIONS:
        for src, label in (("imerg", "IMERG"), ("era5", "ERA5")):
            row = summary["rain"][r][src]
            lines.append(
                f"| Lluvia media {REGION_LABELS[r]} ({label}, mm/día) | {row['n_events']} | {_fmt(row['analogs'])} | "
                f"{_fmt(row['baseline'])} | {_fmt(row['diff'])} | {_ci(row, 'diff_ci')} |"
            )
    lines += [
        "",
        "## Cobertura de los datos de lluvia en los análogos",
        "",
        f"{cov['n_analog_days']} días análogos en total; fracción con dato:",
        "",
        "| Región | IMERG | ERA5 |",
        "|---|---|---|",
        *[
            f"| {REGION_LABELS[r]} | {_fmt(cov['imerg'][r], 2)} | {_fmt(cov['era5'][r], 2)} |"
            for r in REGIONS
        ],
        "",
        "Fracción de cada región dentro de la caja de IMERG: "
        + ", ".join(
            f"{REGION_LABELS[r]} {_fmt(meta['imerg_region_coverage'][r], 3)}" for r in REGIONS
        )
        + ".",
        "",
        "## Límites",
        "",
        (
            "- El IVT diario es la media de 4 horas del día (00/06/12/18 UTC); el IVT máximo de los eventos del catálogo "
            "es horario, por eso el de la capa se rotula aparte (`ivt_daily_max`). Sin verificar cuánto difiere."
        ),
        (
            "- Los análogos comparan el campo de flujo de vapor de la caja, no la causa de la lluvia: dos días parecidos pueden "
            "llover distinto."
        ),
        (
            '- La lluvia de ERA5 es una referencia débil para convección (F3.4). IMERG se descarta ("sin dato") en las '
            "regiones que la caja de IMERG (W -70 / E -67, S -40 / N -37,5) cubre menos de la mitad (cos(lat)): "
            + (
                ", ".join(f"{REGION_LABELS[r]}: {m}" for r, m in meta["imerg_unavailable"].items())
                or "ninguna"
            )
            + "."
        ),
        "- Un día baseline puede ser río atmosférico por azar: por eso se compara contra el baseline y no contra cero.",
        (
            "- Los análogos de 1980–1999 no tienen lluvia (ERA5 empieza en 2000 en este análisis, IMERG en 2000-06): "
            '"sin dato", no cero.'
        ),
        "",
    ]
    return "\n".join(lines)

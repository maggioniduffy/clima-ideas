"""Quality-controlled station precipitation from NOAA ISD (plan/03 F3.2).

One row per raw AA1-AA4 accumulation group of station 877150-99999 (Neuquén Aero), whatever its quality: nothing is
dropped, every row carries ``valid`` and a ``reason``. The 6 h and 24 h windows are the ones F3.4 uses.

Reasons, applied in this order (the first that matches wins):

``missing_value``     depth is the ISD missing value 9999.
``qc_flag``           quality code outside ``isd.ADMISSIBLE_QC`` (suspect, erroneous, missing, letter flags).
``period_not_used``   accumulation period is not 6 h or 24 h (1, 3, 12 h or the missing period 99).
``condition_code``    condition code 1 (measurement impossible or inaccurate).
``duplicate_window``  same (report time, period) as an earlier admissible group; SYNOP first, then file order.
``implausible``       24 h depth above ``MAX_P24_MM`` (see F3.4: repeated exact values, e.g. 326.9 mm in two years).
``inconsistent_p6``   24 h depth that differs from the sum of the four 6 h values of its window by more than
                      max(5 mm, 50 %).
``ok``                everything else (``valid`` = True).

For the 24 h rows that reach the last two checks, ``p24_check`` is ``corroborated`` / ``unchecked`` / ``inconsistent`` /
``implausible`` and ``n6`` / ``sum6`` give the 6 h evidence; ``unchecked`` rows (fewer than four 6 h values) stay valid.

Usage (from ``backend/``)::

    uv run clima-nqn stations qc
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.io import isd

OUT_DIR = Path("data/interim/stations")
QC_NAME = "isd_877150.parquet"
GAPS_NAME = "isd_877150_gaps.parquet"
USED_PERIODS = (6, 24)
MAX_P24_MM = 150.0
CORROB_ABS_MM = 5.0
CORROB_REL = 0.5

REASONS = (
    "ok",
    "missing_value",
    "qc_flag",
    "period_not_used",
    "condition_code",
    "duplicate_window",
    "implausible",
    "inconsistent_p6",
)
SOURCE = "NOAA NCEI Integrated Surface Database (public bucket noaa-isd-pds), station 877150-99999"
LICENSE = "Public domain (NOAA)"

COLUMNS = [
    "station",
    "time",
    "date",
    "report_type",
    "slot",
    "period_h",
    "value_mm",
    "condition",
    "qc_flag",
    "valid",
    "reason",
    "p24_check",
    "n6",
    "sum6",
]


def _duplicate_mask(g: pd.DataFrame) -> pd.Series:
    """True for every group that is not the first of its (time, period) in preference order (SYNOP, then file order)."""
    prio = g["report_type"].map(isd.TYPE_PRIORITY).fillna(9)
    order = pd.Series(np.arange(len(g)), index=g.index)
    ranked = pd.DataFrame(
        {"time": g["time"], "period_h": g["period_h"], "prio": prio, "order": order}
    ).sort_values(["time", "period_h", "prio", "order"], kind="stable")
    dup = ranked.duplicated(["time", "period_h"], keep="first")
    return dup.reindex(g.index)


def apply_qc(groups: pd.DataFrame, station: str = isd.STATION) -> pd.DataFrame:
    """Classify every AA group (``isd.load_all_groups`` output, in file order). Returns the product frame."""
    g = groups.reset_index(drop=True).copy()
    reason = pd.Series("ok", index=g.index, dtype="object")

    def mark(mask: pd.Series, name: str) -> None:
        reason.loc[mask & (reason == "ok")] = name

    mark(g["depth_mm"].isna(), "missing_value")
    mark(~g["quality"].isin(isd.ADMISSIBLE_QC), "qc_flag")
    mark(~g["period_h"].isin(list(USED_PERIODS)), "period_not_used")
    mark(g["condition"].isin(isd.EXCLUDED_CONDITIONS), "condition_code")
    live = reason == "ok"
    dup = pd.Series(False, index=g.index)
    if live.any():
        dup.loc[live] = _duplicate_mask(g.loc[live])
    mark(dup, "duplicate_window")

    # 24 h screening against the 6 h values of the same window (6 h values are never screened)
    live = reason == "ok"
    p6 = g.loc[live & (g["period_h"] == 6)].set_index("time")["depth_mm"]
    p24_idx = g.index[live & (g["period_h"] == 24)]
    check = pd.Series(pd.NA, index=g.index, dtype="object")
    n6 = pd.Series(pd.NA, index=g.index, dtype="Int64")
    sum6 = pd.Series(np.nan, index=g.index)
    for i in p24_idx:
        t, depth = g.at[i, "time"], g.at[i, "depth_mm"]
        vals = [p6.get(t - pd.Timedelta(hours=h)) for h in (18, 12, 6, 0)]
        vals = [float(v) for v in vals if v is not None and not np.isnan(v)]
        n6.at[i], sum6.at[i] = len(vals), float(sum(vals))
        if depth > MAX_P24_MM:
            check.at[i] = "implausible"
        elif len(vals) < 4:
            check.at[i] = "unchecked"
        elif abs(depth - sum(vals)) > max(CORROB_ABS_MM, CORROB_REL * depth):
            check.at[i] = "inconsistent"
        else:
            check.at[i] = "corroborated"
    reason.loc[check == "implausible"] = "implausible"
    reason.loc[check == "inconsistent"] = "inconsistent_p6"

    out = pd.DataFrame(
        {
            "station": station,
            "time": g["time"],
            "date": g["time"].dt.normalize(),
            "report_type": g["report_type"],
            "slot": g["slot"].astype("int8"),
            "period_h": g["period_h"].astype("int16"),
            "value_mm": g["depth_mm"].astype("float64"),
            "condition": g["condition"],
            "qc_flag": g["quality"],
            "valid": reason == "ok",
            "reason": reason.astype("category").cat.set_categories(list(REASONS)),
            "p24_check": check,
            "n6": n6,
            "sum6": sum6,
        }
    )
    return out[COLUMNS]


def valid_windows(qc: pd.DataFrame, *, screened: bool = True) -> pd.DataFrame:
    """Windows in the shape ``bias`` expects (``time``, ``report_type``, ``slot``, ``period_h``, ``depth_mm``,
    ``condition``, ``quality``), one per (time, period).

    ``screened=True``: valid rows only (F3.4 variant A). ``screened=False``: also the rows removed only by the 24 h
    plausibility / consistency screen (F3.4 variant C, "sin filtrar").
    """
    keep = qc["valid"]
    if not screened:
        keep = keep | qc["reason"].isin(["implausible", "inconsistent_p6"])
    cols = {"value_mm": "depth_mm", "qc_flag": "quality"}
    keep_cols = ["time", "report_type", "slot", "period_h", "value_mm", "condition", "qc_flag"]
    out = qc.loc[keep, keep_cols].rename(columns=cols)
    return out.sort_values(["time", "period_h"], kind="stable").reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ gaps


def gap_summary(qc: pd.DataFrame, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Per year and per month: days with valid observations, missing days and discarded rows by reason.

    Days are UTC dates of the report time. Calendar days counted run from ``start`` to ``end`` (default: first to last
    date with any AA group in ``qc``). A day is ``valid_any`` if it has a valid 6 h or 24 h value, ``missing`` if it has
    none (including days with only discarded rows, listed as ``discarded_only`` too, and days with no group at all).
    ``n_<reason>`` columns count every row of ``qc`` dated in the range (all periods, so ``n_period_not_used`` holds
    the 1, 3, 12 h... rows). Days with no report at all are missing, never zero rain.
    """
    d0 = pd.Timestamp(start) if start else qc["date"].min().normalize()
    d1 = pd.Timestamp(end) if end else qc["date"].max().normalize()
    days = pd.DataFrame({"date": pd.date_range(d0, d1, freq="D")})
    v = qc.loc[qc["valid"]]
    for p in USED_PERIODS:
        days[f"valid_p{p}"] = days["date"].isin(v.loc[v["period_h"] == p, "date"])
    days["valid_any"] = days["valid_p6"] | days["valid_p24"]
    days["has_rows"] = days["date"].isin(qc.loc[qc["period_h"].isin(USED_PERIODS), "date"])
    days["discarded_only"] = days["has_rows"] & ~days["valid_any"]
    days["missing"] = ~days["valid_any"]
    days["year"] = days["date"].dt.year
    days["month"] = days["date"].dt.month

    rows = qc.loc[(qc["date"] >= d0) & (qc["date"] <= d1)].copy()
    rows["year"], rows["month"] = rows["date"].dt.year, rows["date"].dt.month
    counts = rows.groupby(["year", "month", "reason"], observed=True).size().unstack(fill_value=0)
    counts = counts.reindex(columns=list(REASONS), fill_value=0)
    counts.columns = [f"n_{c}" for c in counts.columns]

    flags = ["valid_p6", "valid_p24", "valid_any", "discarded_only", "missing"]
    monthly = days.groupby(["year", "month"])[flags].sum()
    monthly.insert(0, "days", days.groupby(["year", "month"]).size())
    monthly = monthly.join(counts, how="left").fillna(0)
    monthly = monthly.reset_index()
    monthly.insert(0, "level", "month")
    yearly = monthly.drop(columns=["month", "level"]).groupby("year", as_index=False).sum()
    yearly.insert(0, "month", 0)
    yearly.insert(0, "level", "year")
    out = pd.concat([yearly, monthly], ignore_index=True)
    int_cols = [c for c in out.columns if c not in ("level",)]
    out[int_cols] = out[int_cols].astype("int64")
    out = out.rename(
        columns={
            "valid_p6": "days_valid_p6",
            "valid_p24": "days_valid_p24",
            "valid_any": "days_valid_any",
            "discarded_only": "days_discarded_only",
            "missing": "days_missing",
        }
    )
    return out.sort_values(["level", "year", "month"], ascending=[False, True, True]).reset_index(
        drop=True
    )


# ----------------------------------------------------------------------------------------------- build


def write_parquet(df: pd.DataFrame, path: Path, meta: dict[str, object]) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pandas(df, preserve_index=False)
    tbl = tbl.replace_schema_metadata(
        {**(tbl.schema.metadata or {}), **{k: str(v).encode() for k, v in meta.items()}}
    )
    pq.write_table(tbl, path)
    return path


def build(
    isd_dir: Path = isd.DEFAULT_DIR,
    years: Iterable[int] = range(2000, 2026),
    out_dir: Path = OUT_DIR,
    download: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Path]]:
    """Read the annual ISD files (downloading missing ones when ``download``), apply QC, write both Parquet files."""
    years = list(years)
    if download:
        paths = isd.download_years(years, isd_dir)
    else:
        paths = [p for y in years if (p := isd_dir / f"{isd.STATION}-{y}.gz").exists()]
    qc = apply_qc(isd.load_all_groups(paths))
    if qc.empty:
        raise ValueError(f"no ISD precipitation groups in {isd_dir} for {years[0]}-{years[-1]}")
    gaps = gap_summary(qc)
    first, last = qc["time"].min(), qc["time"].max()
    meta = {
        "source": SOURCE,
        "license": LICENSE,
        "period": f"{first:%Y-%m-%d} to {last:%Y-%m-%d} (UTC, first to last AA group)",
        "periods_used_h": "6, 24",
        "reasons": ",".join(REASONS),
        "admissible_qc": "".join(sorted(isd.ADMISSIBLE_QC)),
        "max_p24_mm": MAX_P24_MM,
        "counts_by_reason": json.dumps(qc["reason"].value_counts().to_dict()),
        "units": "value_mm in mm over period_h hours ending at time (UTC)",
    }
    out = {
        "qc": write_parquet(qc, out_dir / QC_NAME, meta),
        "gaps": write_parquet(gaps, out_dir / GAPS_NAME, meta),
    }
    return qc, gaps, out

"""Event and control cases for the hindcast forecasts (F5.1).

Event case: the UTC calendar day of ``ivt_max_time`` of every catalog event (F1.3), one case per event
(two events can share a day; they stay two cases with the same ``valid_date``).

Control case: for each event case inside a pool (2000-2019, and 2023-2025 for the ECMWF era) one
day drawn uniformly from the days of the same calendar month inside the pool years that
- have no AR event within +-3 days (every event ``[start, end)`` is widened by 3 days; a day is
  excluded when it touches the widened interval),
- are not an event-case day and not an earlier control (no duplicates),
- fall inside the pool period.
The draw is seeded, so the table is reproducible.

All-days table (F5.3): ``all_days_cases`` gives one case per valid day, ``kind="all"``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_SEED = 20261122
GUARD_DAYS = 3
COLUMNS = ["case_id", "kind", "event_id", "valid_date", "month", "ivt_max"]


@dataclass(frozen=True)
class Pool:
    name: str
    first: pd.Timestamp
    last: pd.Timestamp  # inclusive


POOLS = (
    Pool("2000-2019", pd.Timestamp("2000-01-02"), pd.Timestamp("2019-12-31")),
    Pool("2023-2025", pd.Timestamp("2023-01-28"), pd.Timestamp("2025-12-31")),
)

RULE = (
    "event case = UTC day of ivt_max_time of each catalog event; control case = per event case inside a "
    "pool, one seeded uniform draw among days of the same calendar month within the pool period "
    f"with no AR event within +-{GUARD_DAYS} days (event [start,end) widened), not an event day, "
    "not repeated. Pools: "
    + ", ".join(f"{p.name} ({p.first:%Y-%m-%d}..{p.last:%Y-%m-%d})" for p in POOLS)
)


ALL_DAYS_FIRST = pd.Timestamp("2000-01-10")  # first day whose lead-10 init (2000-01-01) exists
ALL_DAYS_LAST = pd.Timestamp("2019-12-31")
ALL_DAYS_RULE = (
    "all-days table: one case per UTC valid day, kind 'all' (no events, no controls); "
    "default period 2000-01-10..2019-12-31, the days of GEFS reforecast whose lead 1..10 inits "
    "(valid - (L-1)) all lie in 2000-01-01..2019-12-31"
)


def all_days_cases(first=ALL_DAYS_FIRST, last=ALL_DAYS_LAST) -> pd.DataFrame:
    """One case per UTC day in ``first..last`` (inclusive), same columns as ``build_cases``."""
    first, last = pd.Timestamp(first).normalize(), pd.Timestamp(last).normalize()
    if last < first:
        raise ValueError(f"last {last:%Y-%m-%d} is before first {first:%Y-%m-%d}")
    days = pd.date_range(first, last, freq="D")
    out = pd.DataFrame(
        {
            "case_id": [f"ALL-{d:%Y%m%d}" for d in days],
            "kind": "all",
            "event_id": None,
            "valid_date": days.astype("datetime64[ns]"),
            "ivt_max": np.nan,
        }
    )
    out["month"] = out["valid_date"].dt.month.astype("int8")
    return out[COLUMNS]


def forbidden_days(events: pd.DataFrame, guard_days: int = GUARD_DAYS) -> set[pd.Timestamp]:
    """UTC days touched by any event ``[start, end)`` widened by ``guard_days`` on both sides."""
    guard = pd.Timedelta(days=guard_days)
    out: set[pd.Timestamp] = set()
    for start, end in zip(events["start"], events["end"], strict=True):
        lo = (pd.Timestamp(start) - guard).floor("D")
        hi = pd.Timestamp(end) + guard  # exclusive
        last = hi.ceil("D") - pd.Timedelta(days=1)
        out.update(pd.date_range(lo, last, freq="D"))
    return out


def event_cases(events: pd.DataFrame) -> pd.DataFrame:
    days = pd.to_datetime(events["ivt_max_time"]).dt.normalize()
    out = pd.DataFrame(
        {
            "case_id": events["event_id"].astype(str).to_numpy(),
            "kind": "event",
            "event_id": events["event_id"].astype(str).to_numpy(),
            "valid_date": days.to_numpy(),
            "ivt_max": events["ivt_max"].astype(float).to_numpy(),
        }
    )
    return out.sort_values(["valid_date", "case_id"], kind="stable").reset_index(drop=True)


def _pool_days(pool: Pool, month: int) -> pd.DatetimeIndex:
    days = pd.date_range(pool.first, pool.last, freq="D")
    return days[days.month == month]


def build_cases(
    events: pd.DataFrame, seed: int = DEFAULT_SEED, pools: tuple[Pool, ...] = POOLS
) -> pd.DataFrame:
    """Event cases plus seeded control cases (see module docstring)."""
    ev = event_cases(events)
    banned = forbidden_days(events)
    used = set(ev["valid_date"])
    rng = np.random.default_rng(seed)
    rows = []
    for pool in pools:
        inside = ev[(ev["valid_date"] >= pool.first) & (ev["valid_date"] <= pool.last)]
        for month in inside["valid_date"].dt.month:
            eligible = [
                d for d in _pool_days(pool, int(month)) if d not in banned and d not in used
            ]
            if not eligible:
                raise ValueError(f"no eligible control day for month {month} in pool {pool.name}")
            day = eligible[int(rng.integers(len(eligible)))]
            used.add(day)
            rows.append(
                {
                    "case_id": f"CTL-{day:%Y%m%d}",
                    "kind": "control",
                    "event_id": None,
                    "valid_date": day,
                    "ivt_max": np.nan,
                }
            )
    ctl = pd.DataFrame(rows, columns=["case_id", "kind", "event_id", "valid_date", "ivt_max"])
    out = pd.concat([ev, ctl], ignore_index=True)
    out["valid_date"] = pd.to_datetime(out["valid_date"]).astype("datetime64[ns]")
    out["month"] = out["valid_date"].dt.month.astype("int8")
    out = out.sort_values(["valid_date", "case_id"], kind="stable").reset_index(drop=True)
    return out[COLUMNS]


def case_counts(cases: pd.DataFrame, pools: tuple[Pool, ...] = POOLS) -> dict:
    counts = {
        "events": int((cases["kind"] == "event").sum()),
        "controls": int((cases["kind"] == "control").sum()),
    }
    if (cases["kind"] == "all").any():
        counts["all"] = int((cases["kind"] == "all").sum())
    for pool in pools:
        sel = cases[(cases["valid_date"] >= pool.first) & (cases["valid_date"] <= pool.last)]
        counts[pool.name] = {k: int((sel["kind"] == k).sum()) for k in ("event", "control")}
    return counts


def write_cases(
    cases: pd.DataFrame, path: Path, seed: int, source: str = "", rule: str = RULE
) -> dict:
    counts = case_counts(cases)
    table = pa.Table.from_pandas(cases, preserve_index=False)
    meta = {
        b"rule": rule.encode(),
        b"seed": str(seed).encode(),
        b"counts": json.dumps(counts).encode(),
        b"events_source": source.encode(),
    }
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **meta})
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return counts


def read_cases(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)

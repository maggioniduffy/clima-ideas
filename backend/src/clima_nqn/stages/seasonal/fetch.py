"""Fetch the ERA5 land state at issue (F6.2): snow water equivalent and soil water, box means.

One UTC hour per issue: 00 UTC of (issue date - 5 days), issue = 1st of each month (ERA5T latency of
~5 days, so this is the state actually available at issue). Variables (ARCO name -> short):
``snow_depth`` (m of water equivalent, ERA5 ``sd``) and ``volumetric_soil_water_layer_1..3``
(m3/m3, ``swvl1..3``), averaged over ``snow.UPSTREAM_BOXES`` (approximate rectangles, sin verificar)
with ``forcing.box_mean``. This is ERA5 0.25 degrees, NOT ERA5-Land (sensitivity pending).

Output ``data/seasonal/state.parquet``: one row per (issue_date, box) with ``available_on`` (the sampled
hour). Idempotent: issues already complete in the file are skipped; the file is rewritten atomically
after every batch.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.io import era5, forcing, snow

DATA_DIR = Path("data/seasonal")
STATE_PATH = DATA_DIR / "state.parquet"
LOG_PATH = DATA_DIR / "fetch.log"
ARCO_VARS = {
    "snow_depth": "sd",
    "volumetric_soil_water_layer_1": "swvl1",
    "volumetric_soil_water_layer_2": "swvl2",
    "volumetric_soil_water_layer_3": "swvl3",
}
STATE_COLS = list(ARCO_VARS.values())
LATENCY_DAYS = 5
SOURCE = "ERA5 (Copernicus C3S) via ARCO-ERA5; 0.25 degrees, not ERA5-Land"
LICENSE = "CC-BY 4.0"
BOXES_NOTE = "cajas de la cuenca alta (snow.UPSTREAM_BOXES), rectángulos aproximados, sin verificar"


def issue_dates(first: str = "1980-01-01", last: str = "2026-06-01") -> pd.DatetimeIndex:
    return pd.date_range(first, last, freq="MS")


def sample_time(issue: pd.Timestamp) -> pd.Timestamp:
    """00 UTC of issue - 5 days: the hour whose state is available at issue."""
    return pd.Timestamp(issue).normalize() - pd.Timedelta(days=LATENCY_DAYS)


def complete_issues(df: pd.DataFrame, boxes) -> set[pd.Timestamp]:
    """Issues with all boxes and all variables present."""
    if df.empty:
        return set()
    ok = df.dropna(subset=STATE_COLS).groupby("issue_date")["box"].nunique()
    return set(ok[ok == len(boxes)].index)


def _write(df: pd.DataFrame, path: Path) -> None:
    df = df.sort_values(["issue_date", "box"]).reset_index(drop=True)
    df.attrs.update({"source": SOURCE, "license": LICENSE, "boxes": BOXES_NOTE,
                     "sample": "00 UTC of issue - 5 days", "units": "sd: m w.e.; swvl: m3/m3"})  # fmt: skip
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def fetch_state(
    out: Path = STATE_PATH,
    first: str = "1980-01-01",
    last: str = "2026-06-01",
    boxes=snow.UPSTREAM_BOXES,
    opener=era5.open_arco,
    workers: int = 16,
    batch: int = 24,
    retries: int = 4,
    retry_wait: float = 20,
    log=print,
) -> Path:
    import zarr

    zarr.config.set({"async.concurrency": max(10, workers)})
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    have = pd.read_parquet(out) if out.exists() else pd.DataFrame()
    done = complete_issues(have, boxes)
    todo = [d for d in issue_dates(first, last) if d not in done]
    log(f"{len(done)} issues done, {len(todo)} to fetch")
    if not todo:
        return out
    raw = era5._retry(opener, retries, retry_wait, "open")
    stop = pd.Timestamp(raw.attrs.get("valid_time_stop", era5.FINAL_ERA5_STOP))
    area = (
        max(b[1] for b in boxes.values()) + 0.5, min(b[2] for b in boxes.values()) - 0.5,
        min(b[0] for b in boxes.values()) - 0.5, max(b[3] for b in boxes.values()) + 0.5,
    )  # fmt: skip

    def one(task):
        issue, name = task
        t = sample_time(issue)

        def load():
            lazy = raw[[name]].sel(time=[t])
            ds = era5.crop_to_area(lazy, area, {name: ARCO_VARS[name]}).load()
            return {b: float(forcing.box_mean(ds[ARCO_VARS[name]], box)[0]) for b, box in boxes.items()}

        return era5._retry(load, retries, retry_wait, f"{t:%Y-%m-%d} {name}")

    started = time.monotonic()
    frames = [have] if not have.empty else []
    for i in range(0, len(todo), batch):
        part = todo[i : i + batch]
        tasks = [(d, n) for d in part for n in ARCO_VARS]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            res = list(pool.map(one, tasks))
        rows = {}
        for (d, n), vals in zip(tasks, res, strict=True):
            for b, v in vals.items():
                rows.setdefault((d, b), {})[ARCO_VARS[n]] = v
        new = pd.DataFrame(
            [
                {"issue_date": d, "box": b, "available_on": sample_time(d), **r}
                for (d, b), r in rows.items()
            ]
        )
        new["era5t"] = new["available_on"] > stop
        frames.append(new)
        cur = pd.concat(frames, ignore_index=True).drop_duplicates(["issue_date", "box"], keep="last")
        frames = [cur]
        _write(cur, out)
        log(f"{min(i + batch, len(todo))}/{len(todo)} issues, {time.monotonic() - started:.0f}s")
    log(f"wrote {out}: {len(frames[0])} rows")
    return out

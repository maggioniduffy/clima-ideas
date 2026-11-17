"""Regional GPM IMERG Final V07 for Neuquén, downloaded with NASA Harmony.

Usage (from ``backend/``)::

    uv run clima-nqn imerg fetch --year 2014 --months 4
    uv run clima-nqn imerg fetch --years 2000-2026
    uv run clima-nqn imerg combine

Source: GPM IMERG Final Run V07 half-hourly (GPM_3IMERGHH), NASA GES DISC.
License: CC BY 4.0. DOI: https://doi.org/10.5067/GPM/IMERG/3B-HH/07.
Citation: Huffman et al. (2023). Final latency is approximately 3.5 months.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from calendar import monthrange
from collections.abc import Iterable
from datetime import UTC
from itertools import pairwise
from pathlib import Path

import pandas as pd
import xarray as xr

COLLECTION_ID = "C2723754847-GES_DISC"
BBOX = (-70.0, -40.0, -67.0, -37.5)  # west, south, east, north
VARIABLE = "Grid/precipitation"
FIRST_MONTH = (2000, 6)
DEFAULT_OUT = Path("data/raw/imerg/neuquen")
COMBINED = Path("data/raw/imerg/neuquen.zarr")
SOURCE = "GPM IMERG Final Run V07 half-hourly (GPM_3IMERGHH), NASA GES DISC via Harmony"
LICENSE = "CC BY 4.0"
DOI = "https://doi.org/10.5067/GPM/IMERG/3B-HH/07"
PRODUCT = "GPM IMERG Final Run V07 half-hourly (GPM_3IMERGHH)"
DEFAULT_WORKERS = 32  # download threads per Harmony job
DEFAULT_PARALLEL_MONTHS = 4  # Harmony jobs in flight at once
COMBINED_CHUNKS = (17520, 5, 5)
# The HDF5 library in the netCDF4 wheels is not thread-safe. With --parallel, several months merge granules at
# once, and concurrent reads crashed the process (SIGBUS, exit 135). Downloads stay parallel; only reads take turns.
_HDF5_LOCK = threading.Lock()
_TIME_CODER = xr.coders.CFDatetimeCoder(use_cftime=True)
HARMONY_LABEL = "clima-nqn-imerg"
ACTIVE_STATES = frozenset({"accepted", "running", "running_with_errors", "paused", "previewing"})
_monotonic = time.monotonic  # bound here so tests can stub the module's `time` for sleep only


def month_list(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    """Return inclusive calendar months, clipping the start to the first available month."""
    y, m = max(first, FIRST_MONTH)
    end_y, end_m = last
    if (y, m) > (end_y, end_m):
        return []
    return [
        (yy, mm)
        for yy in range(y, end_y + 1)
        for mm in range(1, 13)
        if (yy, mm) >= (y, m) and (yy, mm) <= (end_y, end_m)
    ]


def expected_times(year: int, month: int) -> pd.DatetimeIndex:
    """Expected half-hour start times for a calendar month (naive, UTC like the IMERG files)."""
    return pd.date_range(
        f"{year:04d}-{month:02d}-01", periods=monthrange(year, month)[1] * 48, freq="30min"
    )


def merge_granules(paths: Iterable[Path]) -> xr.Dataset:
    """Open Harmony granules, retain precipitation, and normalize dimensions and axes."""
    pieces = []
    for path in paths:
        # Harmony keeps the HDF5 layout: the variable sits in group "Grid"
        with (
            _HDF5_LOCK,
            xr.open_dataset(path, engine="netcdf4", group="Grid", decode_times=_TIME_CODER) as raw,
        ):
            var = raw["precipitation"].astype("float32").transpose("time", "lat", "lon").load()
        # IMERG labels time with a "julian" calendar; keep the date labels as naive UTC datetimes
        stamps = pd.DatetimeIndex([pd.Timestamp(t.isoformat()) for t in var.time.values])
        pieces.append(var.assign_coords(time=stamps))
    if not pieces:
        raise FileNotFoundError("Harmony returned no granules")
    data = xr.concat(pieces, dim="time").sortby("time")
    data = data.isel(time=~pd.DatetimeIndex(data.time.values).duplicated())
    data = data.sortby("lat").sortby("lon").rename("precipitation")
    data.attrs["units"] = "mm/h"
    return data.to_dataset()


def check_complete(ds: xr.Dataset, year: int, month: int) -> None:
    """Raise with the missing or duplicate expected timestamps."""
    have = pd.DatetimeIndex(ds.time.values)
    want = expected_times(year, month)
    duplicated = have[have.duplicated()]
    if len(duplicated):
        raise ValueError(f"duplicate timestamp: {duplicated[0]}")
    missing = want.difference(have)
    if len(missing):
        raise ValueError(f"missing timestamp: {missing[0]}")
    if len(have) != len(want):
        raise ValueError(f"unexpected timestamp: {have.difference(want)[0]}")


def is_complete(store: Path, year: int, month: int) -> bool:
    try:
        ds = xr.open_zarr(store, consolidated=False, chunks=None)
        check_complete(ds, year, month)
        return "precipitation" in ds
    except Exception:  # noqa: BLE001 - unreadable stores are rebuilt
        return False


def _client(workers: int):
    username, password = os.getenv("EARTHDATA_USERNAME"), os.getenv("EARTHDATA_PASSWORD")
    if not username or not password:
        raise RuntimeError("set EARTHDATA_USERNAME and EARTHDATA_PASSWORD to fetch IMERG")
    os.environ["NUM_REQUESTS_WORKERS"] = str(workers)
    import harmony

    return harmony.Client(auth=(username, password))


def build_request(start, stop):
    """Harmony request for the box, one variable, no preview pause (UTC naive datetimes)."""
    import harmony

    utc = {"tzinfo": UTC}
    return harmony.Request(
        harmony.Collection(id=COLLECTION_ID),
        spatial=harmony.BBox(*BBOX),
        temporal={"start": start.replace(**utc), "stop": stop.replace(**utc)},
        variables=[VARIABLE],
        skip_preview=True,
        labels=[HARMONY_LABEL],
    )


def _cancel_quietly(client, job) -> None:
    try:
        client.cancel(job)
    except Exception as exc:  # noqa: BLE001 - best effort, never mask the original error
        print(f"could not cancel harmony job {job}: {exc}", flush=True)


def cancel_running(client, label: str = HARMONY_LABEL) -> list[str]:
    """Cancel this account's active Harmony jobs carrying ``label``; return the cancelled job ids."""
    import harmony

    limit, page, cancelled = 100, 1, []
    while True:
        data = client.submit(harmony.JobsRequest(page=page, limit=limit, labels=[label]))
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        for item in jobs:
            job_id = item.get("jobID")
            if item.get("status") not in ACTIVE_STATES or not job_id:
                continue
            try:
                client.cancel(job_id)
            except Exception as exc:  # noqa: BLE001 - log and skip
                print(f"could not cancel harmony job {job_id}: {exc}", flush=True)
                continue
            cancelled.append(job_id)
        if len(jobs) < limit:
            return cancelled
        page += 1


def fetch_month(
    year: int,
    month: int,
    out_dir: Path = DEFAULT_OUT,
    client=None,
    workers: int = DEFAULT_WORKERS,
    deadline: float | None = None,
    log_every: float = 60,
) -> Path | None:
    """Fetch and atomically store one complete month; return None if unavailable as Final.

    ``deadline`` is a ``time.monotonic()`` value; a job still polling then is cancelled and TimeoutError raised.
    The Harmony job is also cancelled on any error or interrupt before its downloads complete.
    """
    out_dir = Path(out_dir)
    tag = f"{year:04d}-{month:02d}"
    target = out_dir / f"{tag}.zarr"
    if is_complete(target, year, month):
        print(f"skip {target} (complete)", flush=True)
        return target
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    if client is None:
        client = _client(workers)
    raw_dir = out_dir / f"{tag}-raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    start, stop = expected_times(year, month)[[0, -1]]
    request = build_request(
        start.to_pydatetime(), (stop + pd.Timedelta(minutes=29, seconds=59)).to_pydatetime()
    )
    job = client.submit(request)
    print(f"{tag}: harmony job {job} submitted", flush=True)
    successful = False
    try:
        last_log = None
        while True:
            status = client.status(job)
            state = status["status"] if isinstance(status, dict) else status
            now = _monotonic()
            if last_log is None or now - last_log >= log_every:
                progress = status.get("progress") if isinstance(status, dict) else None
                suffix = f" {progress}%" if progress is not None else ""
                print(f"{tag}: harmony job {job} {state}{suffix}", flush=True)
                last_log = now
            if state == "paused":
                client.resume(job)
            elif state == "successful":
                successful = True
                break
            elif state in {"failed", "canceled", "complete_with_errors"}:
                message = status.get("message", "") if isinstance(status, dict) else ""
                successful = True  # terminal: nothing left to cancel
                raise RuntimeError(f"Harmony job {job} {state}: {message}")
            elif deadline is not None and now >= deadline:
                raise TimeoutError(f"{tag}: harmony job {job} not done by deadline")
            else:
                time.sleep(10)
        print(f"{tag}: downloads starting", flush=True)
        futures = list(client.download_all(job, directory=raw_dir))
        paths = [future.result() for future in futures]
        print(f"{tag}: downloaded {len(paths)} granules", flush=True)
    except BaseException:
        if not successful:
            _cancel_quietly(client, job)
        raise
    if not paths:
        shutil.rmtree(raw_dir, ignore_errors=True)
        print(f"{tag}: not available", flush=True)
        return None
    ds = merge_granules(paths)
    check_complete(ds, year, month)
    ds.attrs.update(
        {"source": SOURCE, "license": LICENSE, "doi": DOI, "product": PRODUCT, "bbox": str(BBOX)}
    )
    ds.to_zarr(tmp, mode="w", consolidated=False)
    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)
    shutil.rmtree(raw_dir)
    return target


def combine(in_dir: Path = DEFAULT_OUT, out: Path = COMBINED) -> Path:
    """Concatenate available monthly stores with provenance and missing-month metadata."""
    stores = sorted(Path(in_dir).glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].zarr"))
    if not stores:
        raise FileNotFoundError(f"no YYYY-MM.zarr stores in {in_dir}")
    opened = [xr.open_zarr(p, consolidated=False, chunks=None) for p in stores]
    times = [pd.DatetimeIndex(ds.time.values) for ds in opened]
    if any(len(a) and len(b) and b[0] <= a[-1] for a, b in pairwise(times)):
        raise ValueError("monthly stores overlap or are out of order")
    present = {(int(p.name[:4]), int(p.name[5:7])) for p in stores}
    first, last = min(present), max(present)
    all_months = month_list(first, last)
    missing = [f"{y:04d}-{m:02d}" for y, m in all_months if (y, m) not in present]
    joined = xr.concat(opened, dim="time").sortby("time")
    # no dask: on-disk chunking via encoding (the whole box is ~1.4 GB float32 in memory)
    for name in ("precipitation", *joined.coords):
        joined[name].encoding.pop("chunks", None)
    encoding = {"precipitation": {"chunks": COMBINED_CHUNKS}}
    joined["precipitation"].attrs["units"] = "mm/h"
    joined.attrs.update(
        {
            "source": SOURCE,
            "license": LICENSE,
            "doi": DOI,
            "product": PRODUCT,
            "period": f"{pd.Timestamp(joined.time.values[0]).isoformat()}/{pd.Timestamp(joined.time.values[-1]).isoformat()}",
            "bbox": str(BBOX),
            "missing_months": ",".join(missing),
        }
    )
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    joined.to_zarr(tmp, mode="w", consolidated=False, encoding=encoding)
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    for ds in opened:
        ds.close()
    return out

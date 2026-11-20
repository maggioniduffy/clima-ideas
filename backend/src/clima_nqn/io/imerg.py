"""Regional GPM IMERG V07 (Final and Late Run) for Neuquén, downloaded with NASA Harmony.

Usage (from ``backend/``)::

    uv run clima-nqn imerg fetch --year 2014 --months 4
    uv run clima-nqn imerg fetch --years 2000-2026
    uv run clima-nqn imerg combine
    uv run clima-nqn imerg fetch --product late --years 2025-2026   # Late Run, separate stores

Source: GPM IMERG Final Run V07 half-hourly (GPM_3IMERGHH), NASA GES DISC.
License: CC BY 4.0. DOI: https://doi.org/10.5067/GPM/IMERG/3B-HH/07.
Citation: Huffman et al. (2023). Final latency is approximately 3.5 months.
Late Run (GPM_3IMERGHHL, DOI https://doi.org/10.5067/GPM/IMERG/3B-HH-L/07) has ~14 h latency and no monthly gauge
adjustment; it lives in its own labels, directories and stores and must never be mixed with Final.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
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
LATE_NOTE = (
    "Late Run: near-real-time, no monthly gauge adjustment (Final has it); "
    "do not mix with Final without saying so"
)


@dataclass(frozen=True)
class Product:
    """One IMERG product; Final and Late never share labels, directories or stores."""

    name: str
    collection_id: str
    source: str
    product: str
    doi: str
    label: str
    out_dir: Path
    combined: Path
    note: str | None = None


PRODUCTS = {
    "final": Product(
        "final", COLLECTION_ID, SOURCE, PRODUCT, DOI, HARMONY_LABEL, DEFAULT_OUT, COMBINED
    ),
    "late": Product(
        "late",
        "C2723754845-GES_DISC",
        "GPM IMERG Late Run V07 half-hourly (GPM_3IMERGHHL), NASA GES DISC via Harmony",
        "GPM IMERG Late Run V07 half-hourly (GPM_3IMERGHHL)",
        "https://doi.org/10.5067/GPM/IMERG/3B-HH-L/07",
        "clima-nqn-imerg-late",
        Path("data/raw/imerg/neuquen-late"),
        Path("data/raw/imerg/neuquen-late.zarr"),
        LATE_NOTE,
    ),
}
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


def get_product(product: str = "final") -> Product:
    try:
        return PRODUCTS[product]
    except KeyError:
        raise ValueError(
            f"unknown IMERG product {product!r}, expected one of {sorted(PRODUCTS)}"
        ) from None


def month_label(year: int, month: int, product: str = "final") -> str:
    """Per-month Harmony job label, so a later run can find and reuse the job."""
    return f"{get_product(product).label}-{year:04d}-{month:02d}"


def _month_label_re(product: str):
    """Exact month labels of one product: Final's ``clima-nqn-imerg-YYYY-MM`` never matches Late's."""
    return re.compile(re.escape(get_product(product).label) + r"-\d{4}-\d{2}")


def build_request(start, stop, month_tag: str | None = None, product: str = "final"):
    """Harmony request for the box, one variable, no preview pause (UTC naive datetimes)."""
    import harmony

    prod = get_product(product)
    utc = {"tzinfo": UTC}
    return harmony.Request(
        harmony.Collection(id=prod.collection_id),
        spatial=harmony.BBox(*BBOX),
        temporal={"start": start.replace(**utc), "stop": stop.replace(**utc)},
        variables=[VARIABLE],
        skip_preview=True,
        labels=[prod.label] if month_tag is None else [prod.label, month_tag],
    )


def _cancel_quietly(client, job) -> None:
    try:
        client.cancel(job)
    except Exception as exc:  # noqa: BLE001 - best effort, never mask the original error
        print(f"could not cancel harmony job {job}: {exc}", flush=True)


def _list_jobs(client, label: str):
    """Yield this account's Harmony job summaries carrying ``label`` (all pages)."""
    import harmony

    limit, page = 100, 1
    while True:
        data = client.submit(harmony.JobsRequest(page=page, limit=limit, labels=[label]))
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        yield from jobs
        if len(jobs) < limit:
            return
        page += 1


def find_job(client, label: str) -> str | None:
    """Newest job with ``label`` that is active or successful (results stay downloadable), else None."""
    try:
        import harmony

        data = client.submit(harmony.JobsRequest(labels=[label], limit=100))
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        usable = [
            j
            for j in jobs
            if j.get("jobID")
            and (j.get("status") in ACTIVE_STATES or j.get("status") == "successful")
        ]
        if not usable:
            return None
        return max(usable, key=lambda j: j.get("createdAt") or "")["jobID"]
    except Exception as exc:  # noqa: BLE001 - fall back to submitting a new job
        print(f"could not look up harmony jobs for {label}: {exc}", flush=True)
        return None


def cancel_running(
    client, label: str | None = None, keep: Iterable[str] = (), product: str = "final"
) -> list[str]:
    """Cancel this account's active Harmony jobs carrying ``label`` (default: the product's); return job ids.

    Jobs carrying any label in ``keep`` (month labels) survive, except older duplicates: only the newest
    active job per month label is kept, so the queue never holds two jobs for one month.
    """
    keep = set(keep)
    label = get_product(product).label if label is None else label
    month_re = _month_label_re(product)
    active = [
        item
        for item in _list_jobs(client, label)
        if item.get("status") in ACTIVE_STATES and item.get("jobID")
    ]
    newest: dict[str, tuple[str, str]] = {}
    for item in active:
        created = item.get("createdAt") or ""
        for lbl in item.get("labels") or []:
            if month_re.fullmatch(lbl) and (lbl not in newest or created > newest[lbl][0]):
                newest[lbl] = (created, item["jobID"])
    cancelled = []
    for item in active:
        job_id = item["jobID"]
        labels = set(item.get("labels") or [])
        month_labels = {lbl for lbl in labels if month_re.fullmatch(lbl)}
        duplicate = any(newest[lbl][1] != job_id for lbl in month_labels)
        if labels & keep and not duplicate:
            continue
        try:
            client.cancel(job_id)
        except Exception as exc:  # noqa: BLE001 - log and skip
            print(f"could not cancel harmony job {job_id}: {exc}", flush=True)
            continue
        cancelled.append(job_id)
    return cancelled


def fetch_month(
    year: int,
    month: int,
    out_dir: Path | None = None,
    client=None,
    workers: int = DEFAULT_WORKERS,
    deadline: float | None = None,
    log_every: float = 60,
    product: str = "final",
) -> Path | None:
    """Fetch and atomically store one complete month; return None if unavailable as Final.

    ``deadline`` is a ``time.monotonic()`` value; a job still polling then is left running on NASA's side for the
    next run to reuse (see ``find_job``) and TimeoutError is raised. Any other error or interrupt before the
    downloads complete cancels the job.
    """
    prod = get_product(product)
    out_dir = Path(prod.out_dir if out_dir is None else out_dir)
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
    label = month_label(year, month, product)
    job = find_job(client, label)
    if job:
        print(f"{tag}: reusing harmony job {job}", flush=True)
    else:
        request = build_request(
            start.to_pydatetime(),
            (stop + pd.Timedelta(minutes=29, seconds=59)).to_pydatetime(),
            label,
            product,
        )
        job = client.submit(request)
        print(f"{tag}: harmony job {job} submitted", flush=True)
    successful = False
    timed_out = False
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
                timed_out = True  # leave the job running for the next run
                raise TimeoutError(f"{tag}: harmony job {job} still running, left for the next run")
            else:
                time.sleep(10)
        print(f"{tag}: downloads starting", flush=True)
        futures = list(client.download_all(job, directory=raw_dir))
        paths = [future.result() for future in futures]
        print(f"{tag}: downloaded {len(paths)} granules", flush=True)
    except BaseException:
        if not successful and not timed_out:
            _cancel_quietly(client, job)
        raise
    if not paths:
        shutil.rmtree(raw_dir, ignore_errors=True)
        print(f"{tag}: not available", flush=True)
        return None
    ds = merge_granules(paths)
    check_complete(ds, year, month)
    ds.attrs.update(
        {
            "source": prod.source,
            "license": LICENSE,
            "doi": prod.doi,
            "product": prod.product,
            "bbox": str(BBOX),
        }
    )
    if prod.note:
        ds.attrs["note"] = prod.note
    ds.to_zarr(tmp, mode="w", consolidated=False)
    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)
    shutil.rmtree(raw_dir)
    return target


def combine(in_dir: Path | None = None, out: Path | None = None, product: str = "final") -> Path:
    """Concatenate available monthly stores with provenance and missing-month metadata."""
    prod = get_product(product)
    in_dir = prod.out_dir if in_dir is None else in_dir
    out = prod.combined if out is None else out
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
            "source": prod.source,
            "license": LICENSE,
            "doi": prod.doi,
            "product": prod.product,
            "period": f"{pd.Timestamp(joined.time.values[0]).isoformat()}/{pd.Timestamp(joined.time.values[-1]).isoformat()}",
            "bbox": str(BBOX),
            "missing_months": ",".join(missing),
        }
    )
    if prod.note:
        joined.attrs["note"] = prod.note
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

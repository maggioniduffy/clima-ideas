"""Zarr shards for the hindcast forecasts: build, resume, combine (F5.1).

A shard store holds ``precip_mm`` (case, lead, member, lat, lon) float32 for a strided subset of the
model's cases, plus ``status`` (case, lead, member) int8: -1 pending, 0 ok, 1 not published (NaN),
2 transient error after retries (NaN, redone on the next run). The whole shard is rewritten
atomically after every batch of cases (it is a few MB), so an interrupted run resumes without
refetching finished cases.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.stages.hindcast import forecasts as fc

log = logging.getLogger(__name__)

CREATED_BY = "clima-nqn hindcast (F5.1)"
BATCH_CASES = 8


def shard_path(out: Path, model: str, shard: int, n_shards: int) -> Path:
    return out / f"{model}.shard-{shard}-of-{n_shards}.zarr"


def empty_store(
    spec: fc.ModelSpec, cases: pd.DataFrame, leads: tuple[int, ...] = fc.LEADS
) -> xr.Dataset:
    """All-NaN, all-pending dataset for ``cases`` (columns of ``cases.parquet``)."""
    n, nl, nm = len(cases), len(leads), len(spec.members)
    valid = pd.to_datetime(cases["valid_date"]).to_numpy().astype("datetime64[ns]")
    init = np.stack(
        [(valid - np.timedelta64(L - 1, "D")).astype("datetime64[ns]") for L in leads], axis=1
    )
    ds = xr.Dataset(
        {
            "precip_mm": (
                ("case", "lead", "member", "lat", "lon"),
                np.full((n, nl, nm, len(fc.LAT), len(fc.LON)), np.nan, dtype=np.float32),
                {"units": "mm", "long_name": "precipitation over the 24 h lead window"},
            ),
            "status": (
                ("case", "lead", "member"),
                np.full((n, nl, nm), fc.STATUS_PENDING, dtype=np.int8),
                {"flag_values": "-1 pending, 0 ok, 1 not published, 2 error"},
            ),
            "init_date": (("case", "lead"), init),
        },
        coords={
            "case": cases["case_id"].astype(str).to_numpy(),
            "lead": np.array(leads, dtype=np.int8),
            "member": np.array(spec.members, dtype=str),
            "lat": fc.LAT,
            "lon": fc.LON,
            "valid_date": ("case", valid),
            "kind": ("case", cases["kind"].astype(str).to_numpy()),
            "event_id": ("case", cases["event_id"].fillna("").astype(str).to_numpy()),
        },
    )
    return ds


def model_attrs(spec: fc.ModelSpec, ds: xr.Dataset, **extra) -> dict:
    status = ds["status"].values
    return {
        "source": spec.source,
        "license": spec.license,
        "period": spec.period,
        "model": spec.name,
        "lead_convention": fc.LEAD_CONVENTION,
        "grid": "lat -41..-36, lon -71.5..-68, 0.25 deg, ascending, lon in -180..180",
        "notes": spec.notes,
        "created_by": CREATED_BY,
        "n_ok": int((status == fc.STATUS_OK).sum()),
        "n_missing": int((status == fc.STATUS_MISSING).sum()),
        "n_error": int((status == fc.STATUS_ERROR).sum()),
        "n_pending": int((status == fc.STATUS_PENDING).sum()),
        **extra,
    }


def write_store(ds: xr.Dataset, path: Path) -> None:
    """Atomic replace of the zarr directory ``path`` (one chunk per case)."""
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    nl, nm = ds.sizes["lead"], ds.sizes["member"]
    enc = {"precip_mm": {"chunks": (1, nl, nm, ds.sizes["lat"], ds.sizes["lon"])}}
    ds.to_zarr(tmp, mode="w", encoding=enc, consolidated=False)
    if path.exists():
        shutil.rmtree(path)
    os.replace(tmp, path)


def read_store(path: Path) -> xr.Dataset:
    with xr.open_zarr(path, chunks=None, consolidated=False) as ds:
        return ds.load()


def _same_layout(a: xr.Dataset, b: xr.Dataset) -> bool:
    return (
        list(a["case"].values) == list(b["case"].values)
        and list(a["lead"].values) == list(b["lead"].values)
        and list(a["member"].values) == list(b["member"].values)
    )


def fetch_shard(
    spec: fc.ModelSpec,
    cases: pd.DataFrame,
    fetcher: fc.Fetcher,
    path: Path,
    leads: tuple[int, ...] = fc.LEADS,
    workers: int = 16,
    batch_cases: int = BATCH_CASES,
    log_fn: Callable[[str], None] = log.info,
) -> dict:
    """Fetch every pending (case, lead, member) of ``cases`` into the shard store at ``path``.

    ``cases`` is this shard's slice (already eligible for the model). Existing finished entries
    are kept; entries with status error or pending are (re)fetched.
    """
    ds = empty_store(spec, cases, leads)
    if path.exists():
        old = read_store(path)
        if not _same_layout(old, ds):
            raise ValueError(f"{path} holds a different case/lead/member layout; remove it first")
        ds = old
        ds["status"].values[ds["status"].values == fc.STATUS_ERROR] = fc.STATUS_PENDING
    precip, status = ds["precip_mm"].values, ds["status"].values
    inits = ds["init_date"].values
    t0 = time.monotonic()

    def one(ci: int, li: int, mi: int):
        init = pd.Timestamp(inits[ci, li])
        try:
            return (
                ci,
                li,
                mi,
                fetcher.fetch(spec.name, init, int(leads[li]), spec.members[mi]),
                None,
            )
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop a long run
            return ci, li, mi, None, exc

    todo = [ci for ci in range(len(cases)) if (status[ci] == fc.STATUS_PENDING).any()]
    log_fn(f"{spec.name}: {len(todo)}/{len(cases)} cases pending")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for b in range(0, len(todo), batch_cases):
            batch = todo[b : b + batch_cases]
            jobs = [
                pool.submit(one, ci, li, mi)
                for ci in batch
                for li in range(len(leads))
                for mi in range(len(spec.members))
                if status[ci, li, mi] == fc.STATUS_PENDING
            ]
            for job in jobs:
                ci, li, mi, arr, exc = job.result()
                if exc is not None:
                    status[ci, li, mi] = fc.STATUS_ERROR
                    log_fn(f"ERROR {cases['case_id'].iloc[ci]} lead {leads[li]}: {exc}")
                elif arr is None:
                    status[ci, li, mi] = fc.STATUS_MISSING
                    log_fn(
                        f"missing {cases['case_id'].iloc[ci]} lead {leads[li]} "
                        f"init {pd.Timestamp(inits[ci, li]):%Y-%m-%d} {spec.members[mi]}"
                    )
                else:
                    precip[ci, li, mi] = arr
                    status[ci, li, mi] = fc.STATUS_OK
            ds.attrs = model_attrs(spec, ds)
            write_store(ds, path)
            log_fn(
                f"{spec.name}: {b + len(batch)}/{len(todo)} cases, {time.monotonic() - t0:.0f} s"
            )
    ds.attrs = model_attrs(spec, ds)
    write_store(ds, path)
    return {
        "cases": len(cases),
        "pending_cases_run": len(todo),
        "seconds": time.monotonic() - t0,
        **{k: v for k, v in ds.attrs.items() if k.startswith("n_")},
    }


def combine_shards(
    spec: fc.ModelSpec,
    in_dir: Path,
    out_path: Path,
    allow_partial: bool = False,
    run_id: str = "",
) -> xr.Dataset:
    """Merge ``<model>.shard-i-of-n.zarr`` stores into one store ordered by (valid_date, case)."""
    found = sorted(in_dir.glob(f"{spec.name}.shard-*-of-*.zarr"))
    if not found:
        raise FileNotFoundError(f"no {spec.name} shards in {in_dir}")
    totals = {int(p.name.split("-of-")[1].split(".")[0]) for p in found}
    if len(totals) != 1:
        raise ValueError(f"shards disagree on the shard count: {sorted(totals)}")
    n = totals.pop()
    have = {int(p.name.split(".shard-")[1].split("-of-")[0]) for p in found}
    if have != set(range(1, n + 1)) and not allow_partial:
        raise ValueError(f"missing shards {sorted(set(range(1, n + 1)) - have)} of {n}")
    parts = [read_store(p) for p in found]
    ds = xr.concat(parts, dim="case", data_vars="all", coords="minimal", compat="override")
    ds = ds.isel(case=np.lexsort((ds["case"].values, ds["valid_date"].values)))
    pending = int((ds["status"].values == fc.STATUS_PENDING).sum())
    if pending and not allow_partial:
        raise ValueError(f"{pending} entries are still pending; run fetch again or allow partial")
    ds.attrs = model_attrs(spec, ds, n_shards=n, **({"run_id": run_id} if run_id else {}))
    write_store(ds, out_path)
    return ds

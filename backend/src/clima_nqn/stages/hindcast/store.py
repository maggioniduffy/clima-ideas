"""Zarr shards for the hindcast forecasts: build, resume, combine (F5.1, grid parametrizable since F5.3).

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
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.stages.hindcast import forecasts as fc

log = logging.getLogger(__name__)

CREATED_BY = "clima-nqn hindcast (F5.1)"
BATCH_CASES = 8

# what a store holds: ``variable`` option -> (array name, units, long name, file stem suffix)
VARIABLES = {
    "precip": ("precip_mm", "mm", "precipitation over the 24 h lead window", ""),
    "ivt": ("ivt", fc.IVT_UNITS, "daily mean of |IVT| over forecast hours 24(L-1)+6..24L", "-ivt"),
}


def variable_info(variable: str) -> tuple[str, str, str, str]:
    if variable not in VARIABLES:
        raise ValueError(f"variable must be one of {', '.join(VARIABLES)}, got {variable!r}")
    return VARIABLES[variable]


def store_stem(model: str, variable: str = "precip") -> str:
    """File stem of a model's store: ``gefs-reforecast`` (precip) or ``gefs-reforecast-ivt``."""
    return model + variable_info(variable)[3]


def with_members(spec: fc.ModelSpec, members: tuple[str, ...] | None) -> fc.ModelSpec:
    """``spec`` restricted to ``members`` (each must belong to the model)."""
    if members is None:
        return spec
    bad = [m for m in members if m not in spec.members]
    if bad or not members:
        raise ValueError(f"members must be among {', '.join(spec.members)}, got {list(members)}")
    return replace(spec, members=tuple(members))


def shard_path(out: Path, model: str, shard: int, n_shards: int, variable: str = "precip") -> Path:
    return out / f"{store_stem(model, variable)}.shard-{shard}-of-{n_shards}.zarr"


def empty_store(
    spec: fc.ModelSpec,
    cases: pd.DataFrame,
    leads: tuple[int, ...] = fc.LEADS,
    grid: fc.Grid = fc.F51_GRID,
    variable: str = "precip",
) -> xr.Dataset:
    """All-NaN, all-pending dataset for ``cases`` (columns of ``cases.parquet``)."""
    vname, units, long_name, _ = variable_info(variable)
    n, nl, nm = len(cases), len(leads), len(spec.members)
    valid = pd.to_datetime(cases["valid_date"]).to_numpy().astype("datetime64[ns]")
    init = np.stack(
        [(valid - np.timedelta64(L - 1, "D")).astype("datetime64[ns]") for L in leads], axis=1
    )
    ds = xr.Dataset(
        {
            vname: (
                ("case", "lead", "member", "lat", "lon"),
                np.full((n, nl, nm, *grid.shape), np.nan, dtype=np.float32),
                {"units": units, "long_name": long_name},
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
            "lat": grid.lat,
            "lon": grid.lon,
            "valid_date": ("case", valid),
            "kind": ("case", cases["kind"].astype(str).to_numpy()),
            "event_id": ("case", cases["event_id"].fillna("").astype(str).to_numpy()),
        },
    )
    return ds


def store_grid(ds: xr.Dataset) -> fc.Grid:
    """Grid of a store from its ``area`` attr (stores written before F5.3 have none: F5.1)."""
    area = ds.attrs.get("area")
    return fc.F51_GRID if area is None else fc.grid_from_area(area)


def data_variable(ds: xr.Dataset) -> str:
    """Name of the forecast array of a store (``precip_mm`` or ``ivt``)."""
    for vname, *_rest in VARIABLES.values():
        if vname in ds.data_vars:
            return vname
    raise ValueError("store holds neither precip_mm nor ivt")


def model_attrs(spec: fc.ModelSpec, ds: xr.Dataset, grid: fc.Grid | None = None, **extra) -> dict:
    grid = grid or store_grid(ds)
    status = ds["status"].values
    ivt = data_variable(ds) == "ivt"
    return {
        "source": fc.SOURCE_GEFS_IVT if ivt and spec.name == "gefs-reforecast" else spec.source,
        "variable": data_variable(ds),
        **(
            {
                "units": fc.IVT_UNITS,
                "levels_hpa": list(fc.IVT_LEVELS),
                "steps": fc.IVT_STEP_NOTE,
                "members": [str(m) for m in ds["member"].values.tolist()],
            }
            if ivt
            else {}
        ),
        "license": spec.license,
        "period": spec.period,
        "model": spec.name,
        "lead_convention": fc.LEAD_CONVENTION,
        "grid": grid.description,
        "grid_name": grid.name,
        "area": list(grid.area),  # N, W, S, E
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
    enc = {data_variable(ds): {"chunks": (1, nl, nm, ds.sizes["lat"], ds.sizes["lon"])}}
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
        and np.array_equal(a["lat"].values, b["lat"].values)
        and np.array_equal(a["lon"].values, b["lon"].values)
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
    grid: fc.Grid = fc.F51_GRID,
    variable: str = "precip",
) -> dict:
    """Fetch every pending (case, lead, member) of ``cases`` into the shard store at ``path``.

    ``variable`` ``ivt`` calls ``fetcher.fetch_ivt`` instead of ``fetcher.fetch`` (F5.10).

    ``cases`` is this shard's slice (already eligible for the model). Existing finished entries
    are kept; entries with status error or pending are (re)fetched.
    """
    ds = empty_store(spec, cases, leads, grid, variable)
    if path.exists():
        old = read_store(path)
        if not _same_layout(old, ds):
            raise ValueError(f"{path} holds a different case/lead/member layout; remove it first")
        if data_variable(old) != data_variable(ds):
            raise ValueError(f"{path} holds {data_variable(old)}, not {data_variable(ds)}")
        ds = old
        ds["status"].values[ds["status"].values == fc.STATUS_ERROR] = fc.STATUS_PENDING
    precip, status = ds[data_variable(ds)].values, ds["status"].values
    inits = ds["init_date"].values
    t0 = time.monotonic()

    def one(ci: int, li: int, mi: int):
        init = pd.Timestamp(inits[ci, li])
        try:
            if variable == "ivt":
                arr = fetcher.fetch_ivt(init, int(leads[li]), spec.members[mi])
            else:
                arr = fetcher.fetch(spec.name, init, int(leads[li]), spec.members[mi])
            return ci, li, mi, arr, None
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
            ds.attrs = model_attrs(spec, ds, grid)
            write_store(ds, path)
            log_fn(
                f"{spec.name}: {b + len(batch)}/{len(todo)} cases, {time.monotonic() - t0:.0f} s"
            )
    ds.attrs = model_attrs(spec, ds, grid)
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
    variable: str = "precip",
) -> xr.Dataset:
    """Merge ``<stem>.shard-i-of-n.zarr`` stores into one store ordered by (valid_date, case)."""
    stem = store_stem(spec.name, variable)
    found = sorted(in_dir.glob(f"{stem}.shard-*-of-*.zarr"))
    if not found:
        raise FileNotFoundError(f"no {stem} shards in {in_dir}")
    totals = {int(p.name.split("-of-")[1].split(".")[0]) for p in found}
    if len(totals) != 1:
        raise ValueError(f"shards disagree on the shard count: {sorted(totals)}")
    n = totals.pop()
    have = {int(p.name.split(".shard-")[1].split("-of-")[0]) for p in found}
    if have != set(range(1, n + 1)) and not allow_partial:
        raise ValueError(f"missing shards {sorted(set(range(1, n + 1)) - have)} of {n}")
    parts = [read_store(p) for p in found]
    grid = store_grid(parts[0])
    for p, part in zip(found, parts, strict=True):
        if (
            store_grid(part) != grid
            or not np.array_equal(part["lat"].values, grid.lat)
            or not np.array_equal(part["lon"].values, grid.lon)
        ):
            raise ValueError(
                f"shards disagree on the grid: {p.name} is not {grid.name} {grid.area}"
            )
    ds = xr.concat(parts, dim="case", data_vars="all", coords="minimal", compat="override")
    ds = ds.isel(case=np.lexsort((ds["case"].values, ds["valid_date"].values)))
    pending = int((ds["status"].values == fc.STATUS_PENDING).sum())
    if pending and not allow_partial:
        raise ValueError(f"{pending} entries are still pending; run fetch again or allow partial")
    ds.attrs = model_attrs(spec, ds, grid, n_shards=n, **({"run_id": run_id} if run_id else {}))
    write_store(ds, out_path)
    return ds

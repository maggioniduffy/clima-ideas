"""Forecast sources for the hindcast ingest (F5.1): GEFS reforecast and ECMWF open data.

Lead convention (same as ``ops/ingest.py``): lead ``L`` (1..10) of a 00 UTC run is the precipitation
over forecast hours (24 (L-1), 24 L], i.e. UTC day ``init + L - 1``. So the run that forecasts valid day
``D`` at lead ``L`` started on ``D - (L - 1)``.

* ``gefs-reforecast`` (NOAA GEFSv12 retrospective, 0.25 deg, members c00 p01..p04): ``apcp_sfc`` files
  hold 3 h (``X-(X+3)``) and 6 h (``X-(X+6)``, X multiple of 6) accumulations. A lead day is the sum of the
  four 6 h messages ``X-(X+6)`` with X = 24 (L-1) + 0, 6, 12, 18, read through ``.idx`` byte ranges.
* ``ifs`` / ``aifs`` (ECMWF open data, AWS mirror): ``tp`` is cumulative since init, so a lead day is
  ``tp(24 L) - tp(24 (L-1))`` (``tp(0) = 0``), clipped at 0. Directory names changed over time (see
  ``ecmwf_dirs``); 0.4 deg runs (IFS before 2024-02-29) are bilinearly regridded to the 0.25 deg grid.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import httpx
import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.io.grib import grib_fields

log = logging.getLogger(__name__)

LEADS = tuple(range(1, 11))
AREA = (-36.0, -71.5, -41.0, -68.0)  # N, W, S, E (``grib_fields`` order)
LAT = np.round(np.arange(-41.0, -36.0 + 1e-6, 0.25), 4)  # ascending
LON = np.round(np.arange(-71.5, -68.0 + 1e-6, 0.25), 4)  # ascending, -180..180
MARGIN = 0.5  # extra degrees decoded around AREA so that regridding has neighbours
GEFS_BASE = "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast"
ECMWF_BASE = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
GEFS_MEMBERS = ("c00", "p01", "p02", "p03", "p04")
STATUS_PENDING, STATUS_OK, STATUS_MISSING, STATUS_ERROR = -1, 0, 1, 2

SOURCE_GEFS = "NOAA GEFSv12 reforecast (noaa-gefs-retrospective, AWS NODD), APCP, 00 UTC, 0.25 deg"
SOURCE_ECMWF = "ECMWF open data (AWS mirror ecmwf-forecasts), tp, 00 UTC run"
LICENSE_GEFS = "NOAA NODD: open to the public, attribution requested, no NOAA endorsement implied"
LICENSE_ECMWF = (
    "CC-BY-4.0 + ECMWF Terms of Use (https://www.ecmwf.int/en/forecasts/datasets/open-data)"
)
LEAD_CONVENTION = (
    "lead L = precipitation over forecast hours (24(L-1), 24L] of the 00 UTC run; "
    "valid_date = init_date + L - 1 (UTC day 00-24 h)"
)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    members: tuple[str, ...]
    first_valid: pd.Timestamp
    last_valid: pd.Timestamp  # inclusive
    source: str
    license: str
    notes: str = ""

    @property
    def period(self) -> str:
        return f"valid {self.first_valid:%Y-%m-%d}..{self.last_valid:%Y-%m-%d}"


MODELS = {
    "gefs-reforecast": ModelSpec(
        "gefs-reforecast", GEFS_MEMBERS, pd.Timestamp("2000-01-02"), pd.Timestamp("2019-12-31"),
        SOURCE_GEFS, LICENSE_GEFS,
        "inits 2000-01-01..2019-12-31 only (the 2020 prefix holds a single misplaced 2010-07-01 init)",
    ),
    "ifs": ModelSpec(
        "ifs", ("oper",), pd.Timestamp("2023-01-28"), pd.Timestamp("2025-12-31"),
        SOURCE_ECMWF + ", IFS oper (0.4 deg before 2024-02-29, regridded bilinearly)", LICENSE_ECMWF,
        "single deterministic member",
    ),
    "aifs": ModelSpec(
        "aifs", ("oper",), pd.Timestamp("2024-02-29"), pd.Timestamp("2025-12-31"),
        SOURCE_ECMWF + ", AIFS single (dirs aifs/ until 2025-02, aifs-single/ after)", LICENSE_ECMWF,
        "mirror has no AIFS before 2024-02-29",
    ),
}  # fmt: skip


def eligible_cases(cases: pd.DataFrame, spec: ModelSpec) -> pd.DataFrame:
    """Cases whose valid date lies inside the model period, ordered by (valid_date, case_id)."""
    sel = cases[
        (cases["valid_date"] >= spec.first_valid) & (cases["valid_date"] <= spec.last_valid)
    ]
    return sel.sort_values(["valid_date", "case_id"], kind="stable").reset_index(drop=True)


def split_shard(items: list, shard: int, n_shards: int) -> list:
    """Items of shard ``shard`` (1-based) of ``n_shards``: strided, so shards partition the list."""
    if not 1 <= shard <= n_shards:
        raise ValueError(f"shard must be in 1..{n_shards}, got {shard}")
    return items[shard - 1 :: n_shards]


def parse_shard(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)/(\d+)", text.strip())
    if not m or not 1 <= int(m[1]) <= int(m[2]):
        raise ValueError(f"--shard must look like i/n with 1 <= i <= n, got {text!r}")
    return int(m[1]), int(m[2])


# --- lead / init / step arithmetic (pure) ------------------------------------------------------


def init_date(valid: date | pd.Timestamp, lead: int) -> pd.Timestamp:
    """00 UTC run that forecasts UTC day ``valid`` at ``lead`` (1..10)."""
    return pd.Timestamp(valid).normalize() - pd.Timedelta(days=lead - 1)


def gefs_bucket_steps(lead: int) -> list[tuple[int, int]]:
    """The four 6 h buckets ``(X, X+6)`` (forecast hours) that make up lead day ``lead``."""
    base = 24 * (lead - 1)
    return [(base + x, base + x + 6) for x in (0, 6, 12, 18)]


def ecmwf_steps(lead: int) -> tuple[int, int]:
    """Cumulative ``tp`` steps ``(24 (L-1), 24 L)`` whose difference is lead day ``lead``."""
    return 24 * (lead - 1), 24 * lead


def ecmwf_daily(prev: np.ndarray | None, nxt: np.ndarray) -> np.ndarray:
    """Daily mm from cumulative fields in mm (``prev`` None = step 0); noise below 0 is clipped."""
    return np.maximum(nxt - (0.0 if prev is None else prev), 0.0).astype(np.float32)


@dataclass(frozen=True)
class IdxMessage:
    start: int  # first byte
    end: int | None  # last byte (inclusive); None = to end of file
    start_h: int
    end_h: int


_ACC = re.compile(r"(\d+)-(\d+) hour acc")


def gefs_url(init: date | pd.Timestamp, member: str) -> str:
    d = pd.Timestamp(init)
    tag = f"{d:%Y%m%d}00"
    return f"{GEFS_BASE}/{d:%Y}/{tag}/{member}/Days:1-10/apcp_sfc_{tag}_{member}.grib2"


def parse_apcp_idx(text: str) -> list[IdxMessage]:
    """Surface APCP accumulation messages of a GEFS ``.idx`` with their byte ranges.

    Lines look like ``2:465975:d=2005010100:APCP:surface:0-6 hour acc fcst:ENS=low-res ctl``; the
    byte range of a message runs to the next line's offset - 1 (any variable).
    """
    rows = [ln.split(":") for ln in text.splitlines() if ln.strip()]
    out = []
    for i, parts in enumerate(rows):
        if len(parts) < 6 or parts[3] != "APCP" or parts[4] != "surface":
            continue
        m = _ACC.match(parts[5])
        if not m:
            continue
        end = int(rows[i + 1][1]) - 1 if i + 1 < len(rows) else None
        out.append(IdxMessage(int(parts[1]), end, int(m[1]), int(m[2])))
    return out


def gefs_lead_ranges(messages: list[IdxMessage], lead: int) -> list[IdxMessage]:
    """The four ``X-(X+6)`` messages of lead day ``lead``; ValueError when one is absent."""
    by_span = {(m.start_h, m.end_h): m for m in messages}
    steps = gefs_bucket_steps(lead)
    missing = [s for s in steps if s not in by_span]
    if missing:
        raise ValueError(f"idx has no 6 h buckets {missing} for lead {lead}")
    return [by_span[s] for s in steps]


def ecmwf_dirs(model: str, init: date | pd.Timestamp) -> list[str]:
    """Candidate mirror directories (after ``<date>/00z/``) for a run, most likely first.

    Probed 2026-11-22: IFS ``0p4-beta/oper`` until 2024-02-28 (``0p25/oper`` also exists from
    2024-02-01), ``ifs/0p25/oper`` from 2024-02-29; AIFS ``aifs/0p25/oper`` 2024-02-29..2025-02,
    ``aifs-single/0p25/oper`` from 2025-03.
    """
    d = pd.Timestamp(init)
    if model == "ifs":
        if d >= pd.Timestamp("2024-02-29"):
            return ["ifs/0p25/oper"]
        if d >= pd.Timestamp("2024-02-01"):
            return ["0p25/oper", "0p4-beta/oper"]
        return ["0p4-beta/oper", "0p25/oper"]
    if model == "aifs":
        dirs = ["aifs/0p25/oper", "aifs-single/0p25/oper"]
        return dirs[::-1] if d >= pd.Timestamp("2025-03-01") else dirs
    raise ValueError(f"not an ECMWF model: {model}")


def ecmwf_file(init: date | pd.Timestamp, directory: str, step: int) -> str:
    d = pd.Timestamp(init)
    return f"{ECMWF_BASE}/{d:%Y%m%d}/00z/{directory}/{d:%Y%m%d}000000-{step}h-oper-fc"


def tp_range(index_text: str, step: int) -> tuple[int, int] | None:
    """``(offset, length)`` of the surface ``tp`` message of ``step`` in an ECMWF JSON-lines index."""
    for line in index_text.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("param") == "tp" and rec.get("levtype") == "sfc" and int(rec["step"]) == step:
            return int(rec["_offset"]), int(rec["_length"])
    return None


def to_target_grid(field: xr.DataArray) -> np.ndarray:
    """Values on the fixed (LAT, LON) grid: plain selection if the grid matches, else bilinear."""
    lat, lon = np.round(field["lat"].values, 4), np.round(field["lon"].values, 4)
    if np.isin(LAT, lat).all() and np.isin(LON, lon).all():
        field = field.assign_coords(lat=lat, lon=lon).sel(lat=LAT, lon=LON)
    else:
        field = field.interp(lat=LAT, lon=LON, method="linear")
    return field.values.astype(np.float32)


def _margin_area() -> tuple[float, float, float, float]:
    n, w, s, e = AREA
    return n + MARGIN, w - MARGIN, s - MARGIN, e + MARGIN


# --- network fetcher -----------------------------------------------------------------------------


class FetchError(Exception):
    """A transient failure that survived the retries (the file may exist)."""


class Fetcher(Protocol):
    """``fetch`` returns mm on the (LAT, LON) grid, ``None`` when not published; may raise FetchError."""

    def fetch(
        self, model: str, init: pd.Timestamp, lead: int, member: str
    ) -> np.ndarray | None: ...


class HttpFetcher:
    """Anonymous HTTPS byte-range reads; thread safe; counts requests and bytes."""

    def __init__(
        self, retries: int = 5, backoff: float = 1.0, timeout: float = 60.0, sleep=time.sleep
    ):
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)
        self.retries, self.backoff, self._sleep = retries, backoff, sleep
        self._lock = threading.Lock()
        self.bytes = 0
        self.requests = 0
        self._idx: dict[str, str | None] = {}
        self._dir: dict[tuple[str, str], str] = {}

    def _get(self, url: str, byte_range: tuple[int, int | None] | None = None) -> bytes | None:
        headers = {}
        if byte_range is not None:
            lo, hi = byte_range
            headers["Range"] = f"bytes={lo}-{'' if hi is None else hi}"
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.client.get(url, headers=headers)
                with self._lock:
                    self.requests += 1
                    self.bytes += len(resp.content)
                if resp.status_code == 404:
                    return None
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        str(resp.status_code), request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp.content
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                self._sleep(self.backoff * 2**attempt)
        raise FetchError(f"{url}: {last}") from last

    def _text(self, url: str) -> str | None:
        if url not in self._idx:
            raw = self._get(url)
            self._idx[url] = None if raw is None else raw.decode()
        return self._idx[url]

    def fetch(self, model: str, init: pd.Timestamp, lead: int, member: str) -> np.ndarray | None:
        if model == "gefs-reforecast":
            return self._fetch_gefs(init, lead, member)
        if model in ("ifs", "aifs"):
            return self._fetch_ecmwf(model, init, lead)
        raise ValueError(f"unknown model {model}")

    def _fetch_gefs(self, init: pd.Timestamp, lead: int, member: str) -> np.ndarray | None:
        url = gefs_url(init, member)
        text = self._text(url + ".idx")
        if text is None:
            return None
        total = None
        for msg in gefs_lead_ranges(parse_apcp_idx(text), lead):
            blob = self._get(url, (msg.start, msg.end))
            if blob is None:
                return None
            [(keys, field)] = grib_fields(blob, _margin_area())
            if keys["stepRange"] != f"{msg.start_h}-{msg.end_h}":
                raise RuntimeError(
                    f"{url}: want {msg.start_h}-{msg.end_h}, got {keys['stepRange']}"
                )
            vals = to_target_grid(field)
            total = vals if total is None else total + vals
        return total

    def _tp(self, model: str, init: pd.Timestamp, step: int) -> np.ndarray | None:
        key = (model, f"{init:%Y%m%d}")
        dirs = [self._dir[key]] if key in self._dir else ecmwf_dirs(model, init)
        for directory in dirs:
            base = ecmwf_file(init, directory, step)
            text = self._text(base + ".index")
            if text is None:
                continue
            rng = tp_range(text, step)
            if rng is None:
                raise RuntimeError(f"{base}.index has no surface tp at step {step}")
            self._dir[key] = directory
            blob = self._get(base + ".grib2", (rng[0], rng[0] + rng[1] - 1))
            if blob is None:
                return None
            [(_, field)] = grib_fields(blob, _margin_area())
            return to_target_grid(field * 1000.0)  # m -> mm
        return None

    def _fetch_ecmwf(self, model: str, init: pd.Timestamp, lead: int) -> np.ndarray | None:
        s0, s1 = ecmwf_steps(lead)
        nxt = self._tp(model, init, s1)
        if nxt is None:
            return None
        prev = None if s0 == 0 else self._tp(model, init, s0)
        if s0 != 0 and prev is None:
            return None
        return ecmwf_daily(prev, nxt)

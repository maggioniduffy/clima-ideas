"""NOAA ISD (Integrated Surface Database) hourly/synoptic reports: precipitation accumulation groups AA1-AA4.

Usage (from ``backend/``)::

    from clima_nqn.io import isd
    paths = isd.download_years(range(2000, 2026))
    acc = isd.load_accumulations(paths)

Source: NOAA NCEI Integrated Surface Database, public bucket ``noaa-isd-pds``; station 877150-99999 (Neuquén Aero,
SAZN, -38.949, -68.156). Format: ISD format document, https://www.ncei.noaa.gov/pub/data/noaa/isd-format-document.pdf.
Public domain (NOAA).

Record layout (fixed width, 1-based columns): 1-4 variable-section length; 16-23 date YYYYMMDD (UTC); 24-27 time HHMM
(UTC); 42-46 report type (FM-12, FM-15, SY-MT, ...); the mandatory section ends at column 105; ``ADD`` opens the
additional data, where ``AAn`` + period (2 digits, hours) + depth (4 digits, 0.1 mm, 9999 = missing) + condition
(1 char) + quality (1 char) repeats for n = 1..4; ``REM`` / ``EQD`` open sections that are not parsed.
"""

from __future__ import annotations

import gzip
import re
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

STATION = "877150-99999"
URL = "https://noaa-isd-pds.s3.amazonaws.com/data/{year}/{station}-{year}.gz"
DEFAULT_DIR = Path("data/raw/isd")
# Quality codes kept. 0 = passed gross limits, 1 = passed all checks, 4 / 5 = the same two outcomes for data that
# originate from the NCEI source. Excluded: 2 / 6 suspect, 3 / 7 erroneous, 9 missing, and the letter flags
# (A, B, C, D, I, M, P, R, U) which mark values changed or derived by later processing.
ADMISSIBLE_QC = frozenset("0145")
MISSING_DEPTH = 9999
MISSING_PERIOD = 99
# Condition codes: 1 = measurement impossible or inaccurate (dropped), 2 = trace (depth 0 -> treated as 0.0 mm),
# 3 = begin accumulated period, 0 / 4 / others are kept and reported. Every kept code is counted by the caller.
EXCLUDED_CONDITIONS = frozenset("1")
# Preference when two reports give the same window: SYNOP first.
TYPE_PRIORITY = {"FM-12": 0, "SY-MT": 1, "FM-15": 2, "FM-16": 3}

_ADD_START = 105
_AA = re.compile(r"AA([1-4])(\d{2})(\d{4})([0-9A-Za-z])([0-9A-Za-z])")
_END_MARKERS = ("REM", "EQD")


@dataclass(frozen=True)
class Accumulation:
    """One AAn group of one report. ``depth_mm`` is None when the depth is the missing value 9999."""

    time: pd.Timestamp  # report time, naive UTC
    report_type: str
    slot: int  # n of AAn
    period_h: int
    depth_mm: float | None
    condition: str
    quality: str


def parse_line(line: str) -> list[Accumulation]:
    """Parse the AA1-AA4 groups of one ISD record. Records without a valid date or additional section give []."""
    line = line.rstrip("\r\n")
    if len(line) <= _ADD_START + 3 or line[_ADD_START : _ADD_START + 3] != "ADD":
        return []
    try:
        stamp = pd.Timestamp(
            year=int(line[15:19]),
            month=int(line[19:21]),
            day=int(line[21:23]),
            hour=int(line[23:25]),
            minute=int(line[25:27]),
        )
    except ValueError:
        return []
    body = line[_ADD_START + 3 :]
    for marker in _END_MARKERS:
        pos = body.find(marker)
        if pos >= 0:
            body = body[:pos]
    report_type = line[41:46].strip()
    out = []
    for m in _AA.finditer(body):
        depth_raw = int(m.group(3))
        period = int(m.group(2))
        out.append(
            Accumulation(
                time=stamp,
                report_type=report_type,
                slot=int(m.group(1)),
                period_h=period if period != MISSING_PERIOD else -1,
                depth_mm=None if depth_raw == MISSING_DEPTH else depth_raw / 10.0,
                condition=m.group(4),
                quality=m.group(5),
            )
        )
    return out


def parse_lines(lines: Iterable[str]) -> Iterator[Accumulation]:
    for line in lines:
        yield from parse_line(line)


def download_year(year: int, out_dir: Path = DEFAULT_DIR, station: str = STATION) -> Path:
    """Download one annual file (cached: an existing non-empty file is not fetched again)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{station}-{year}.gz"
    if path.exists() and path.stat().st_size > 0:
        return path
    tmp = path.with_suffix(".gz.part")
    with (
        urllib.request.urlopen(URL.format(year=year, station=station), timeout=120) as resp,
        tmp.open("wb") as fh,
    ):
        fh.write(resp.read())
    tmp.replace(path)
    return path


def download_years(
    years: Iterable[int], out_dir: Path = DEFAULT_DIR, station: str = STATION
) -> list[Path]:
    return [download_year(y, out_dir, station) for y in years]


def read_file(path: Path) -> Iterator[Accumulation]:
    with gzip.open(path, "rt", encoding="ascii", errors="replace") as fh:
        yield from parse_lines(fh)


def load_all_groups(paths: Iterable[Path]) -> pd.DataFrame:
    """Every AA group (any quality) as a DataFrame, for counting codes."""
    rows = [a for p in paths for a in read_file(p)]
    cols = ["time", "report_type", "slot", "period_h", "depth_mm", "condition", "quality"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame({c: [] for c in cols})


def admissible(groups: pd.DataFrame, periods: Iterable[int] = (6, 24)) -> pd.DataFrame:
    """Groups with a depth, admissible QC, a wanted period and a kept condition code."""
    keep = (
        groups["depth_mm"].notna()
        & groups["quality"].isin(ADMISSIBLE_QC)
        & groups["period_h"].isin(list(periods))
        & ~groups["condition"].isin(EXCLUDED_CONDITIONS)
    )
    return groups.loc[keep].copy()


def dedupe_windows(groups: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """One value per (report time, period): SYNOP type first, then file order. Returns (frame, n_disagreeing_windows).

    "Disagreeing" counts windows with duplicate groups whose depths differ by more than 0.05 mm.
    """
    g = groups.copy()
    g["_prio"] = g["report_type"].map(TYPE_PRIORITY).fillna(9)
    g["_order"] = range(len(g))
    g = g.sort_values(["time", "period_h", "_prio", "_order"], kind="stable")
    spread = g.groupby(["time", "period_h"])["depth_mm"].agg(lambda s: s.max() - s.min())
    disagree = int((spread > 0.05).sum())
    first = g.drop_duplicates(["time", "period_h"], keep="first").drop(columns=["_prio", "_order"])
    return first.reset_index(drop=True), disagree

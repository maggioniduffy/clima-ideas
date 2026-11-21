"""Viewer layer ``convection-idf`` (plan/03, F3.5): IMERG-only IDF curve of Neuquén and a replay of April 2014.

Output in ``<out>/`` (default ``data/processed/convection-idf``), kind ``raster-frames``:

- ``manifest.json``       layer manifest; period = the hydrological years used for the IDF (July 1..June 30).
- ``idf.json``            IDF of the cell nearest to Neuquén Aero (GEV by L-moments, 90 % bootstrap CI, Gumbel baseline) for
  ``durations_h`` x ``return_periods``, per scenario: ``main`` (no bias correction) and the sensitivity scenarios where the
  annual maxima are divided by a factor before fitting (``idf_table(..., correction=lambda x: x / f)``, reports/03/F3.3.md).
  Rows: ``d`` (h), ``t`` (years), ``depth_mm``, ``intensity_mm_h``, ``depth_lo``/``depth_hi``, ``intensity_lo``/``intensity_hi``
  (CI 90 %) and ``extrapolated`` (T > 2 x n_years). Scenarios other than ``main`` carry ``gev`` only.
- ``replay.json``         the storm replay: window, grid cell of Neuquén Aero, the IMERG cumulative series at that cell
  from the comparison window start (``cumulative.mm``: value at ``start + k * step_minutes``, 0 at k = 0) and the station
  total over the same 12Z-12Z window as a reference point with its source.
- ``frames/index.json``   same contract as ``ar-events`` (``grid``, ``step_hours``, ``events``) for the half-hourly IMERG rate
  (mm/h) over the whole Zarr box; ``frames/<frame set>.bin`` little-endian Float32 ``[n_frames, ny, nx]``, row 0 = south,
  column 0 = west, NaN = missing. Served by ``GET /layers/convection-idf/frames/<frame set>``.

Time is UTC (naive in the Zarr). Run: ``python -m clima_nqn.layers.convection_idf``.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.layers.manifest import LayerManifest
from clima_nqn.stages.convection import idf

LAYER_ID = "convection-idf"
TITLE = "Convección: curva IDF y temporal de abril de 2014"
SOURCE = "GPM IMERG Final V07 (NASA GES DISC)"
LICENSE = "CC BY 4.0 (IMERG)"
DEFAULT_OUT = idf.REPO_ROOT / "data" / "processed" / LAYER_ID
FRAME_SET = "storm-2014-04"
STEP = pd.Timedelta(minutes=30)

# Replay window: the 6-8/4/2014 storm in IMERG (cell of Neuquén Aero: rain from 6/4 00Z to 8/4 ~18Z), UTC.
STORM_START = pd.Timestamp("2014-04-06 00:00")
STORM_END = pd.Timestamp("2014-04-09 00:00")  # exclusive
# Station accumulation 12Z-12Z of 7/4/2014 (reports/03/F3.0.md, F3.4.md).
COMPARE_START = pd.Timestamp("2014-04-06 12:00")
COMPARE_END = pd.Timestamp("2014-04-07 12:00")
STATION = {
    "name": "Neuquén Aero",
    "id": "877150-99999",
    "lat": -38.949,
    "lon": -68.156,
    "value_mm": 118.0,
    "source": "NOAA ISD (NCEI), estación 877150-99999",
    "window": "12Z–12Z (6/4 12:00 a 7/4 12:00 UTC)",
    "note": "Acumulado de 24 h corroborado con la suma de los cuatro de 6 h (119,0 mm); reports/03/F3.4.md",
}
# Sensitivity of the IDF to the IMERG bias of F3.4 (reports/03/F3.3.md): maxima divided by these factors.
SCENARIOS = (
    {
        "id": "div-0.92",
        "factor": 0.92,
        "label": "÷ 0,92",
        "note": "Razón de totales IMERG/estación a 24 h en los días lluviosos (IC 90 % 0,82–1,02).",
    },
    {
        "id": "div-0.67",
        "factor": 0.67,
        "label": "÷ 0,67",
        "note": (
            "Razón IMERG/estación en 16 eventos de ≥ 20 mm/24 h (entre 0,12 y 1,53 por evento). "
            "Aplicarlo a duraciones menores es un supuesto sin verificar."
        ),
    },
)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(x, nd: int = 2):
    return None if x is None or not math.isfinite(float(x)) else round(float(x), nd)


def _rows(table: pd.DataFrame, method: str) -> list[dict]:
    sub = table[table["method"] == method].sort_values(["return_period_yr", "duration_h"])
    return [
        {
            "d": float(r.duration_h),
            "t": float(r.return_period_yr),
            "depth_mm": _num(r.depth_mm),
            "intensity_mm_h": _num(r.intensity_mm_h, 3),
            "depth_lo": _num(r.ci_low),
            "depth_hi": _num(r.ci_high),
            "intensity_lo": _num(r.ci_low_mm_h, 3),
            "intensity_hi": _num(r.ci_high_mm_h, 3),
            "extrapolated": bool(r.extrapolated),
        }
        for r in sub.itertuples()
    ]


def hydro_label(am: pd.DataFrame) -> str:
    y0, y1 = int(am.index.min()), int(am.index.max())
    return f"{y0}/{str(y0 + 1)[2:]}–{y1}/{str(y1 + 1)[2:]} (años julio–junio)"


def idf_payload(
    am: pd.DataFrame, meta: dict, n_boot: int = idf.N_BOOT, scenarios=SCENARIOS
) -> dict:
    """The ``idf.json`` content from the annual maxima of the main cell."""
    main = idf.idf_table(am, n_boot=n_boot)
    out = [
        {
            "id": "main",
            "label": "Sin corrección de sesgo",
            "factor": None,
            "note": idf.LABEL,
            "gev": _rows(main, "gev_lmom"),
            "gumbel": _rows(main, "gumbel_mom"),
        }
    ]
    for sc in scenarios:
        f = sc["factor"]
        table = idf.idf_table(am, n_boot=n_boot, correction=lambda x, f=f: x / f)
        out.append(
            {
                "id": sc["id"],
                "label": sc["label"],
                "factor": f,
                "note": sc["note"],
                "gev": _rows(table, "gev_lmom"),
            }
        )
    n = len(am)
    return {
        "label": idf.LABEL,
        "source": SOURCE,
        "doi": meta["doi"],
        "license": LICENSE,
        "period": hydro_label(am),
        "n_years": n,
        "fit": "GEV por L-momentos (curva principal); Gumbel por momentos (referencia); IC 90 % por bootstrap",
        "ci_level": 0.9,
        "n_boot": n_boot,
        "extrapolation_above_t": 2 * n,
        "cell": meta["cell"],
        "target": {"name": STATION["name"], "lat": STATION["lat"], "lon": STATION["lon"]},
        "durations_h": [float(d) for d in am.columns],
        "return_periods": [float(t) for t in idf.RETURN_PERIODS],
        "scenarios": out,
    }


def _nearest(values: np.ndarray, target: float) -> int:
    return int(np.abs(values - target).argmin())


def replay_arrays(
    precip, start: pd.Timestamp, end: pd.Timestamp
) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """Half-hourly frames ``[n, ny, nx]`` (mm/h, float32, south-west origin) for ``[start, end)``; raises if incomplete."""
    stamps = pd.date_range(start, end, freq=STEP, inclusive="left")
    sub = precip.sel(time=slice(stamps[0], stamps[-1])).sortby("lat").sortby("lon")
    if sub.sizes["time"] != len(stamps) or not (pd.DatetimeIndex(sub.time.values) == stamps).all():
        raise ValueError(f"IMERG frames incomplete for {start}..{end}")
    return np.ascontiguousarray(sub.values.astype("<f4")), stamps


def build(
    zarr_path: Path | str = idf.ZARR_PATH,
    out_dir: Path | str = DEFAULT_OUT,
    *,
    n_boot: int = idf.N_BOOT,
    storm: tuple[pd.Timestamp, pd.Timestamp] = (STORM_START, STORM_END),
    compare: tuple[pd.Timestamp, pd.Timestamp] = (COMPARE_START, COMPARE_END),
    station: dict | None = None,
    scenarios=SCENARIOS,
) -> Path:
    """Write the layer from the IMERG Zarr and return its directory."""
    import xarray as xr

    out_dir = Path(out_dir)
    station = {**STATION, **(station or {})}
    storm_start, storm_end = (pd.Timestamp(t) for t in storm)
    cmp_start, cmp_end = (pd.Timestamp(t) for t in compare)
    if not storm_start <= cmp_start < cmp_end <= storm_end:
        raise ValueError("comparison window must lie inside the replay window")

    ds = xr.open_zarr(zarr_path, consolidated=False)
    lats, lons = ds.lat.values, ds.lon.values
    i, j = _nearest(lats, station["lat"]), _nearest(lons, station["lon"])
    series = ds.precipitation.isel(lat=i, lon=j).load().to_series()
    series = series * idf.STEP_H  # mm/h -> mm per half hour
    am = idf.annual_maxima(series)
    if len(am) < 3:
        raise ValueError(f"need >= 3 complete hydrological years, got {len(am)}")
    cell = {"lat": round(float(lats[i]), 3), "lon": round(float(lons[j]), 3)}
    meta = {"doi": str(ds.attrs.get("doi", "")), "cell": cell}
    idf_json = idf_payload(am, meta, n_boot=n_boot, scenarios=scenarios)

    frames, stamps = replay_arrays(ds.precipitation, storm_start, storm_end)
    ys, xs = np.sort(lats), np.sort(lons)
    row, col = _nearest(ys, station["lat"]), _nearest(xs, station["lon"])
    grid = {
        "ny": len(ys),
        "nx": len(xs),
        "lat_min": round(float(ys[0]), 4),
        "lat_max": round(float(ys[-1]), 4),
        "lon_min": round(float(xs[0]), 4),
        "lon_max": round(float(xs[-1]), 4),
        "origin": "south-west",
    }
    frames_index = {
        "units": "mm/h",
        "variable": "precipitation",
        "dtype": "float32-le",
        "layout": "[n_frames, ny, nx], row 0 = south, column 0 = west",
        "step_hours": 0.5,
        "grid": grid,
        "events": {
            FRAME_SET: {
                "start": _iso(stamps[0]),
                "n_frames": len(stamps),
                "vmin": _num(np.nanmin(frames), 3),
                "vmax": _num(np.nanmax(frames), 3),
            }
        },
    }

    # Cumulative IMERG at the cell from the comparison start to the end of the replay (value at the end of each step).
    cum_stamps = pd.date_range(cmp_start, storm_end, freq=STEP, inclusive="left")
    cell_mm = series.reindex(cum_stamps)
    if cell_mm.isna().any():
        raise ValueError("IMERG series incomplete in the comparison window")
    cumulative = np.concatenate([[0.0], np.cumsum(cell_mm.to_numpy())])
    k_end = int((cmp_end - cmp_start) / STEP)
    replay = {
        "event": {
            "id": FRAME_SET,
            "name": "Temporal del 6 al 8 de abril de 2014",
            "start": _iso(stamps[0]),
            "end": _iso(storm_end),
            "step_minutes": 30,
            "n_frames": len(stamps),
        },
        "source": SOURCE,
        "doi": meta["doi"],
        "units": "mm/h",
        "cell": {**cell, "row": row, "col": col},
        "compare": {
            "start": _iso(cmp_start),
            "end": _iso(cmp_end),
            "window": station["window"],
            "imerg_mm": _num(cumulative[k_end], 1),
            "station": {
                "name": station["name"],
                "id": station["id"],
                "lat": station["lat"],
                "lon": station["lon"],
                "value_mm": station["value_mm"],
                "source": station["source"],
                "note": station["note"],
            },
        },
        "cumulative": {
            "start": _iso(cmp_start),
            "step_minutes": 30,
            "mm": [_num(v, 2) for v in cumulative],
        },
    }
    y0, y1 = int(am.index.min()), int(am.index.max())
    manifest = LayerManifest(
        id=LAYER_ID,
        title=TITLE,
        kind="raster-frames",
        source=SOURCE,
        period=f"{y0}-07-01/{y1 + 1}-06-30",
        license=LICENSE,
        updated_at=datetime.now(UTC),
        files=["idf.json", "replay.json", "frames/index.json", f"frames/{FRAME_SET}.bin"],
    )

    # Everything is validated and built: only now write files.
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    (frames_dir / f"{FRAME_SET}.bin").write_bytes(frames.tobytes())
    _write_json(frames_dir / "index.json", frames_index)
    _write_json(out_dir / "idf.json", idf_json)
    _write_json(out_dir / "replay.json", replay)
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--zarr", type=Path, default=idf.ZARR_PATH)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--n-boot", type=int, default=idf.N_BOOT)
    a = p.parse_args(argv)
    out = build(a.zarr, a.out, n_boot=a.n_boot)
    print(out)


if __name__ == "__main__":
    main()

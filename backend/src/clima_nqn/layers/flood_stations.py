"""Viewer layer ``flood-stations`` (plan/02, F2.4): SNIH stations with daily flow and GEV return periods.

Output in ``<out>/`` (default ``data/processed/flood-stations``):

- ``manifest.json``     layer manifest (kind ``points``); lists every file below.
- ``stations.json``     one row per station with data: ``id`` (string), ``lon``, ``lat``, ``value``, ``name``,
  ``river``, ``area_km2``, ``has_gev``, ``regulated``. ``value`` is the 100-year return level (m3/s) when
  the station has a GEV fit and the maximum observed daily flow (m3/s) otherwise; the map sizes dots by it.
- ``stations/<id>.json`` station detail: meta, ``source``, ``period``, ``fetched``, ``daily`` (``start`` plus one
  1-decimal value per day, null for gaps), ``annual_maxima``, ``top_floods`` and, with a GEV fit, ``gev``,
  ``return_levels`` and a smooth ``curve`` (T 1.1..200; ``lo``/``hi`` only inside the stored T range).
- ``events/<id>.json``  optional flood-card hindcast of the LSTM (``clima-nqn flow lstm-hindcast``, F2.6); when it
  exists the station detail has ``has_events: true`` and the manifest lists it. A layer without them is valid.
- ``top_floods`` / ``annual_maxima`` entries may carry ``ar_events`` (ids of the AR events that coincide with
  that flood in ``causes.json`` of F2.3, ``clima-nqn flow causes``); the field is absent when there is none or
  when ``causes.json`` is missing. The coincidence is a time window rule, not a cause.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import genextreme

from clima_nqn.io import flow
from clima_nqn.layers.manifest import MANIFEST_NAME, LayerManifest, load_manifest
from clima_nqn.stages.flood import extremes

LAYER_ID = "flood-stations"
TITLE = "Crecidas: caudal y período de retorno"
DEFAULT_OUT = flow.OUT_DIR.parent / "processed" / LAYER_ID
CURVE_T = (1.1, 200.0)
CURVE_POINTS = 40
TOP_N = 5
EVENTS_DIR = "events"
IRREGULAR_XI = extremes.IRREGULAR_XI


def _round(x, nd: int = 1):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def daily_block(df: pd.DataFrame) -> dict:
    """One value per day from the first date (1 decimal, null for gaps)."""
    days = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    q = df.set_index("date")["q_m3s"].reindex(days)
    return {
        "start": days[0].date().isoformat(),
        "q": [_round(v) for v in q.to_numpy(dtype=float)],
    }


def gev_block(gev: dict, n_years: int) -> dict:
    return {
        "loc": gev["loc"],
        "scale": gev["scale"],
        "shape_xi": gev["shape_xi"],
        "n_years": n_years,
        "ks_p": gev["ks_pvalue"],
        "irregular": bool(gev["shape_xi"] >= IRREGULAR_XI),
    }


def return_levels_block(gev: dict) -> list[dict]:
    return [
        {
            "t": r["return_period"],
            "q": _round(r["value"]),
            "lo": _round(r["ci95_low"]),
            "hi": _round(r["ci95_high"]),
        }
        for r in gev["return_levels"]
    ]


def curve_block(gev: dict) -> list[dict]:
    """GEV curve from the stored parameters; the CI is interpolated in log T, null outside the stored range."""
    ts = np.logspace(math.log10(CURVE_T[0]), math.log10(CURVE_T[1]), CURVE_POINTS)
    q = genextreme.isf(1.0 / ts, -gev["shape_xi"], loc=gev["loc"], scale=gev["scale"])
    rl = gev["return_levels"]
    log_t = np.log([r["return_period"] for r in rl])
    lo = np.interp(np.log(ts), log_t, [r["ci95_low"] for r in rl])
    hi = np.interp(np.log(ts), log_t, [r["ci95_high"] for r in rl])
    out = []
    for t, qi, li, hi_ in zip(ts, q, lo, hi, strict=True):
        inside = rl[0]["return_period"] <= t <= rl[-1]["return_period"]
        out.append(
            {
                "t": round(float(t), 3),
                "q": _round(qi),
                "lo": _round(li) if inside else None,
                "hi": _round(hi_) if inside else None,
            }
        )
    return out


def _maxima_from_gev(gev_result: dict) -> list[dict]:
    return [
        {
            "hydro_year": m["hydro_year"],
            "date": m["date"],
            "q": _round(m["q_m3s"]),
            "t_empirical": _round(m["empirical_T"], 2),
            "t_gev": _round(m["gev_T"], 2),
        }
        for m in gev_result["annual_maxima"]
    ]


def _maxima_from_daily(df: pd.DataFrame, start_month: int) -> list[dict]:
    """Annual maxima with empirical T only (stations without a GEV fit)."""
    maxima, _ = extremes.annual_maxima(df, start_month=start_month)
    if maxima.empty:
        return []
    t_emp = extremes.empirical_return_period(maxima["q_m3s"].to_numpy())
    return [
        {
            "hydro_year": int(m.hydro_year),
            "date": m.date.date().isoformat(),
            "q": _round(m.q_m3s),
            "t_empirical": _round(t, 2),
            "t_gev": None,
        }
        for m, t in zip(maxima.itertuples(), t_emp, strict=True)
    ]


def station_detail(meta: dict, df: pd.DataFrame, gev_result: dict | None, fetched: str) -> dict:
    daily = daily_block(df)
    first, last = df["date"].min().date().isoformat(), df["date"].max().date().isoformat()
    has_gev = gev_result is not None
    maxima = (
        _maxima_from_gev(gev_result)
        if has_gev
        else _maxima_from_daily(df, meta.get("hydro_year_start_month") or 4)
    )
    detail = {
        "id": str(meta["id"]),
        "name": meta["name"],
        "river": meta["river"],
        "lon": meta["lon"],
        "lat": meta["lat"],
        "area_km2": meta.get("area_km2"),
        "has_gev": has_gev,
        "regulated": "regulada" in (meta.get("note") or ""),
        "source": flow.SOURCE,
        "period": f"{first}/{last}",
        "fetched": fetched,
        "daily": daily,
        "annual_maxima": maxima,
        "top_floods": sorted(maxima, key=lambda m: -m["q"])[:TOP_N],
    }
    if has_gev:
        gev = gev_result["gev"]
        detail["gev"] = gev_block(gev, gev_result["n_years"])
        detail["return_levels"] = return_levels_block(gev)
        detail["curve"] = curve_block(gev)
    return detail


def station_value(detail: dict, df: pd.DataFrame) -> float:
    """100-year return level when the station has a GEV, else the maximum observed daily flow."""
    if detail["has_gev"]:
        level = max(detail["return_levels"], key=lambda r: r["t"])
        return level["q"]
    return _round(df["q_m3s"].max())


def attach_events(out_dir: Path | str) -> list[str]:
    """Register the ``events/<id>.json`` files of a built layer: flag the station details, list them in the manifest.

    Files of stations without a ``stations/<id>.json`` are ignored. Does nothing without a manifest.
    Returns the registered relative paths.
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return []
    manifest = load_manifest(manifest_path)
    rels = []
    for path in sorted((out_dir / EVENTS_DIR).glob("*.json")):
        detail_path = out_dir / "stations" / path.name
        if not detail_path.is_file():
            continue
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        if not detail.get("has_events"):
            _write_json(detail_path, {**detail, "has_events": True})
        rels.append(f"{EVENTS_DIR}/{path.name}")
    files = [f for f in manifest.files if not f.startswith(f"{EVENTS_DIR}/")] + rels
    if files != manifest.files:
        updated = manifest.model_copy(update={"files": files})
        manifest_path.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    return rels


def load_ar_events(causes_path: Path | str | None) -> dict[str, dict[str, list[str]]]:
    """``{station id: {flood date: [AR event ids]}}`` from ``causes.json`` (empty without the file)."""
    if causes_path is None or not Path(causes_path).is_file():
        return {}
    payload = json.loads(Path(causes_path).read_text(encoding="utf-8"))
    out: dict[str, dict[str, list[str]]] = {}
    for st in payload.get("stations", []):
        dates = {f["date"]: list(f["events"]) for f in st.get("floods", []) if f.get("events")}
        if dates:
            out[str(st["station_id"])] = dates
    return out


def add_ar_events(detail: dict, by_date: dict[str, list[str]]) -> None:
    """Tag the maxima and top floods of ``detail`` whose date has AR events (in place)."""
    for key in ("annual_maxima", "top_floods"):
        detail[key] = [
            {**m, "ar_events": by_date[m["date"]]} if m["date"] in by_date else m
            for m in detail[key]
        ]


def build_layer(
    flow_dir: Path | str = flow.OUT_DIR,
    gev_dir: Path | str | None = None,
    out_dir: Path | str = DEFAULT_OUT,
    causes_path: Path | str | None = None,
) -> Path:
    flow_dir = Path(flow_dir)
    if causes_path is None:
        causes_path = flow_dir / "causes.json"
    ar_by_station = load_ar_events(causes_path)
    gev_dir = Path(gev_dir) if gev_dir is not None else flow_dir / "gev"
    out_dir = Path(out_dir)
    payload = json.loads((flow_dir / "stations.json").read_text(encoding="utf-8"))
    fetched = payload["fetched"]
    rows, files, firsts, lasts = [], ["stations.json"], [], []
    for meta in payload["stations"]:
        parquet = flow_dir / f"{meta['id']}.parquet"
        if not parquet.is_file():
            continue
        df = flow.read_flow(parquet)
        gev_path = gev_dir / f"{meta['id']}.json"
        gev_result = (
            json.loads(gev_path.read_text(encoding="utf-8")) if gev_path.is_file() else None
        )
        detail = station_detail(meta, df, gev_result, fetched)
        add_ar_events(detail, ar_by_station.get(detail["id"], {}))
        rel = f"stations/{detail['id']}.json"
        _write_json(out_dir / rel, detail)
        files.append(rel)
        first, last = detail["period"].split("/")
        firsts.append(first)
        lasts.append(last)
        rows.append(
            {
                "id": detail["id"],
                "lon": detail["lon"],
                "lat": detail["lat"],
                "value": station_value(detail, df),
                "name": detail["name"],
                "river": detail["river"],
                "area_km2": detail["area_km2"],
                "has_gev": detail["has_gev"],
                "regulated": detail["regulated"],
            }
        )
    if not rows:
        raise ValueError(f"no station series in {flow_dir}")
    _write_json(out_dir / "stations.json", rows)
    manifest = LayerManifest(
        id=LAYER_ID,
        title=TITLE,
        kind="points",
        source=flow.SOURCE,
        period=f"{min(firsts)}/{max(lasts)}",
        license=(
            f"Uso libre citando la fuente (términos SNIH/SIPH); datos actualizados al {fetched}"
        ),
        updated_at=datetime.now(UTC),
        files=files,
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    attach_events(out_dir)  # keep the hindcast files of an earlier `flow lstm-hindcast`
    return out_dir

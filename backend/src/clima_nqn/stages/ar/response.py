"""River response to atmospheric rivers: flow before and peak flow after each AR event (viewer S5).

Question: for each AR event of the catalog and each SNIH station, how much did the daily flow rise in the
days after the event, and how many days after its start did it peak?

Rules fixed before looking at results (odd/tasks/ar-viewer-rework.md, S5):
- Days are calendar days, as in ``stages.flood.causes``: the first day of an event is its start
  normalized, the last day is ``end - 1 ns`` normalized (``end`` is exclusive). Flow is local (UTC-3), the
  catalog is UTC; the offset is ignored.
- ``q_before`` is the flow on the day before the first day.
- The peak window is ``[first, last + RESPONSE_DAYS_AFTER]`` with ``RESPONSE_DAYS_AFTER = 10``. The 10 days
  are an assumption, not a verified hydrological lag; it is a named parameter, written into the output.
- ``q_peak`` is the maximum daily flow in the peak window, ``peak_date`` its day and ``lag_days`` the days
  from the first day of the event. ``ratio = q_peak / q_before``, null when ``q_before`` is missing or 0.
- ``daily`` holds the flow from ``CONTEXT_DAYS_BEFORE = 3`` days before the first day to the end of the
  peak window (1 decimal, null for gaps), for the chart.
- A pair (event, station) with no valid flow in the peak window, or outside the flow record, is skipped.
- Regulated stations (``regulada`` in the station note) reflect dam operation, not only the river.
- The flow in the window coincides with the event; this does not show that the river caused it.

Output ``responses.json`` in the ``ar-events`` layer directory, listed in its manifest.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from clima_nqn.io import flow
from clima_nqn.layers.manifest import MANIFEST_NAME, load_manifest
from clima_nqn.stages.ar import catalog as ar_catalog
from clima_nqn.stages.flood import causes

RESPONSE_DAYS_AFTER = 10  # assumption, not a verified hydrological lag
CONTEXT_DAYS_BEFORE = 3
RESPONSES_NAME = "responses.json"
NOTE = (
    "El caudal de la ventana coincide con el evento del río atmosférico; esto no prueba que el río "
    "atmosférico lo haya causado. La ventana de "
    f"{RESPONSE_DAYS_AFTER} días posteriores es un supuesto, no un rezago hidrológico verificado. "
    "Las estaciones reguladas reflejan la operación de las represas."
)


def _round(x, nd: int = 1):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def station_response(series: pd.Series, first: pd.Timestamp, last: pd.Timestamp) -> dict | None:
    """Response of one station (``series``: daily flow indexed by date) to an event on days first..last."""
    end = last + pd.Timedelta(days=RESPONSE_DAYS_AFTER)
    window = series.loc[first:end].dropna()
    if window.empty:
        return None
    peak_date = window.idxmax()
    q_peak = float(window.max())
    before_day = first - pd.Timedelta(days=1)
    q_before = series.get(before_day)
    q_before = None if q_before is None or pd.isna(q_before) else float(q_before)
    ratio = q_peak / q_before if q_before else None
    start = first - pd.Timedelta(days=CONTEXT_DAYS_BEFORE)
    days = pd.date_range(start, end, freq="D")
    q = series.reindex(days)
    return {
        "q_before": _round(q_before),
        "q_peak": _round(q_peak),
        "peak_date": peak_date.date().isoformat(),
        "lag_days": int((peak_date - first).days),
        "ratio": _round(ratio, 2),
        "daily": {
            "start": start.date().isoformat(),
            "q": [_round(float(v)) for v in q.to_numpy(dtype=float)],
        },
    }


def build_responses(events: pd.DataFrame, flow_dir: Path | str, source: str, period: str) -> dict:
    flow_dir = Path(flow_dir)
    payload = json.loads((flow_dir / "stations.json").read_text(encoding="utf-8"))
    stations, series = [], {}
    for meta in payload["stations"]:
        parquet = flow_dir / f"{meta['id']}.parquet"
        if not parquet.is_file():
            continue
        df = flow.read_flow(parquet)
        series[str(meta["id"])] = df.set_index(pd.to_datetime(df["date"]).dt.normalize())["q_m3s"]
        stations.append(
            {
                "id": str(meta["id"]),
                "name": meta["name"],
                "river": meta["river"],
                "regulated": "regulada" in (meta.get("note") or ""),
            }
        )
    firsts, lasts = causes._event_days(events)
    out: dict[str, list[dict]] = {}
    for event_id, first, last in zip(events["event_id"], firsts, lasts, strict=True):
        rows = []
        for st in stations:
            res = station_response(series[st["id"]], first, last)
            if res is not None:
                rows.append({"station_id": st["id"], **res})
        if rows:
            out[str(event_id)] = rows
    return {
        "source": f"{flow.SOURCE} / {source}",
        "period": period,
        "window_days_after": RESPONSE_DAYS_AFTER,
        "context_days_before": CONTEXT_DAYS_BEFORE,
        "note": NOTE,
        "stations": stations,
        "events": out,
    }


def build(catalog_path: Path | str, flow_dir: Path | str, out_dir: Path | str) -> dict:
    """Write ``<out_dir>/responses.json`` and list it in the layer manifest (if there is one)."""
    out_dir = Path(out_dir)
    events, _ = causes.load_catalog(catalog_path)
    meta = ar_catalog.read_metadata(catalog_path)
    result = build_responses(events, flow_dir, meta.get("source", ""), meta.get("period", ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / RESPONSES_NAME).write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    manifest_path = out_dir / MANIFEST_NAME
    if manifest_path.is_file():
        manifest = load_manifest(manifest_path)
        if RESPONSES_NAME not in manifest.files:
            updated = manifest.model_copy(update={"files": [*manifest.files, RESPONSES_NAME]})
            manifest_path.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    return result

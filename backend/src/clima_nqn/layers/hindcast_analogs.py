"""Viewer layer ``hindcast-analogs`` (plan/05, F5.5): ERA5 analog days of every F1.3 event and what happened on them.

Output in ``<out>/`` (default ``data/processed/hindcast-analogs``), kind ``series``:

- ``manifest.json``  layer manifest (source ERA5 via ARCO-ERA5 and IMERG Final V07, period = the analog library).
- ``analogs.json``   ``{id, title, source, license, period, k, regions, units, rain_periods, method, summary, events}``;
  per event ``{event_id, date, ivt_max, ivt_daily_max, analogs: [{rank, date, distance, ar_event_id | null, ivt_max,
  rain: {region: {imerg, era5}}}], analog_summary, baseline}``. ``null`` rain means "sin dato" (outside the product's period).
  ``ivt_max`` of an event is the hourly F1.3 maximum; ``ivt_max`` of an analog is the box maximum of the daily-mean |IVT|.

Input: the ``analogs.json`` written by ``clima-nqn hindcast analogs``. Run: ``clima-nqn hindcast analogs-layer``.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from clima_nqn.layers.manifest import LayerManifest
from clima_nqn.stages.hindcast import analogs as an

LAYER_ID = "hindcast-analogs"
TITLE = "Análogos ERA5 de los eventos de río atmosférico"
SOURCE = an.SOURCE
LICENSE = an.LICENSE
FILE = "analogs.json"
DEFAULT_OUT = Path(__file__).resolve().parents[4] / "data" / "processed" / LAYER_ID

_EVENT_KEYS = ("event_id", "date", "ivt_max", "analogs", "baseline")
_ANALOG_KEYS = ("date", "distance", "ar_event_id", "ivt_max", "rain")


def _check_finite(obj, where: str) -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ValueError(f"non-finite number at {where}")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _check_finite(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_finite(v, f"{where}[{i}]")


def validate(payload: dict) -> None:
    for key in ("period", "events"):
        if key not in payload:
            raise ValueError(f"analogs.json lacks {key!r}")
    _check_finite(payload, "analogs")
    for ev in payload["events"]:
        for key in _EVENT_KEYS:
            if key not in ev:
                raise ValueError(f"event {ev.get('event_id')!r} lacks {key!r} (analogs.json)")
        for a in ev["analogs"]:
            for key in _ANALOG_KEYS:
                if key not in a:
                    raise ValueError(f"event {ev['event_id']!r}: analog lacks {key!r}")


def build(src: Path | str, out_dir: Path | str = DEFAULT_OUT) -> Path:
    """Validate ``analogs.json`` from ``hindcast analogs`` and write the layer directory."""
    payload = json.loads(Path(src).read_text(encoding="utf-8"))
    validate(payload)
    payload = {**payload, "id": LAYER_ID, "title": TITLE, "source": SOURCE, "license": LICENSE}
    manifest = LayerManifest(
        id=LAYER_ID,
        title=TITLE,
        kind="series",
        source=SOURCE,
        period=payload["period"],
        license=LICENSE,
        updated_at=datetime.now(UTC),
        files=[FILE],
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / FILE).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return out_dir

"""Viewer layer ``hindcast-verification`` (plan/05, F5.6): hindcast forecasts of the F1.3 events against ERA5.

Output in ``<out>/`` (default ``data/processed/hindcast-verification``), kind ``series``:

- ``manifest.json``  layer manifest (source: GEFSv12 reforecast, ECMWF IFS and AIFS; observed ERA5; period = event days).
- ``cases.json``     ``{id, title, source, license, period, obs_source, units, leads, models}``; per model
  ``{label, source, license, period, n_members, events: [{event_id, date, obs_mm, mean, min, max}]}`` where ``mean``,
  ``min`` and ``max`` are lists aligned to ``leads`` (1..10): the ensemble mean / minimum / maximum of the cos(lat)-weighted box
  mean of the 24 h precipitation (``verify.box_mean``, same box and definition as F5.2). ``null`` = not published.
  Only event cases (``kind == "event"``); ``obs_mm`` is the ERA5 box mean of the valid day (``reports/05/F5.2-obs.csv``).
- ``skill.json``     ``{models, aifs_vs_ifs, gate}`` from ``F5.2.json`` (event CRPSS vs. climatology with CI, bias, n by lead),
  ``F5.4.json`` (AIFS vs. IFS, events) and ``F5.8.json`` (evidence gate per region and lead).

Run: ``clima-nqn hindcast verification-layer``.
"""

from __future__ import annotations

import json
import math
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.layers.manifest import LayerManifest
from clima_nqn.stages.hindcast import verify as v

LAYER_ID = "hindcast-verification"
TITLE = "Verificación retrospectiva de pronósticos"
SOURCE = "GEFSv12 reforecast (NOAA), ECMWF IFS y AIFS open data; observado ERA5 (Copernicus)"
LICENSE = (
    "GEFS: NODD de NOAA, abierta con atribución. ECMWF open data: CC BY 4.0. "
    "ERA5 (Copernicus): CC BY 4.0."
)
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT = REPO_ROOT / "data" / "processed" / LAYER_ID
DEFAULT_FORECASTS = REPO_ROOT / "data" / "f51-forecasts"
DEFAULT_REPORTS = REPO_ROOT / "reports" / "05"
MODELS = {
    "gefs-reforecast": "GEFSv12 reforecast (5 miembros)",
    "ifs": "ECMWF IFS",
    "aifs": "ECMWF AIFS",
}
OBS_SOURCE = (
    "ERA5 (Copernicus Climate Change Service), media de la caja por cos(lat), mm por día UTC"
)
DEFAULT_OBS_NAME = "F5.2-obs.csv"


def _clean(obj, nd: int = 4):
    """NaN/inf -> None and floats rounded, recursively (strict JSON)."""
    if isinstance(obj, float | np.floating):
        f = float(obj)
        return round(f, nd) if math.isfinite(f) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, dict):
        return {k: _clean(x, nd) for k, x in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(x, nd) for x in obj]
    return obj


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def read_obs(path: Path | str) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    return df["box_mean_mm"].astype("float64")


def model_cases(ds: xr.Dataset, obs: pd.Series) -> dict:
    """Event cases of one F5.1 Zarr dataset: ensemble mean/min/max of the box mean by lead and the ERA5 box mean."""
    prec = ds["precip_mm"].where(ds["status"] == 0)
    members = v.box_mean(prec).transpose("case", "lead", "member").values
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(members, axis=2)
        lo = np.nanmin(members, axis=2)
        hi = np.nanmax(members, axis=2)
    kind = v.str_values(ds["kind"])
    ids = v.str_values(ds["event_id"])
    valid = pd.to_datetime(ds["valid_date"].values)
    obs_v = obs.reindex(valid).to_numpy(dtype="float64")
    events = []
    for i in np.flatnonzero(kind == "event"):
        events.append(
            {
                "event_id": str(ids[i]),
                "date": valid[i].strftime("%Y-%m-%d"),
                "obs_mm": obs_v[i],
                "mean": mean[i].tolist(),
                "min": lo[i].tolist(),
                "max": hi[i].tolist(),
            }
        )
    events.sort(key=lambda e: (e["date"], e["event_id"]))
    return {
        "leads": [int(x) for x in ds["lead"].values],
        "n_members": int(ds.sizes["member"]),
        "events": events,
    }


def skill_curves(f52: dict) -> dict:
    """Per-model event curves (CRPSS vs. climatology with CI, bias, n) from ``F5.2.json`` records."""
    out: dict[str, dict] = {}
    for model in MODELS:
        rows = [r for r in f52["records"] if r["model"] == model and r["kind"] == "event"]
        by = {}
        for metric in ("crpss", "bias", "n"):
            by[metric] = {
                int(r["lead"]): r for r in rows if r["metric"] == metric and r["threshold"] is None
            }
        leads = sorted(by["crpss"])
        out[model] = {
            "leads": leads,
            "crpss": [
                {
                    "lead": k,
                    "value": by["crpss"][k]["value"],
                    "lo": by["crpss"][k]["lo"],
                    "hi": by["crpss"][k]["hi"],
                }
                for k in leads
            ],
            "bias": [
                {
                    "lead": k,
                    "value": by["bias"][k]["value"],
                    "lo": by["bias"][k]["lo"],
                    "hi": by["bias"][k]["hi"],
                }
                for k in leads
                if k in by["bias"]
            ],
            "n": [{"lead": k, "n": int(by["n"][k]["value"])} for k in leads if k in by["n"]],
        }
    return out


def aifs_vs_ifs(f54: dict) -> dict:
    keep = (
        "lead",
        "n",
        "mae_ifs",
        "mae_aifs",
        "diff",
        "lo",
        "hi",
        "bias_ifs",
        "bias_aifs",
        "p_sign",
        "verdict",
    )
    rows = [{k: r[k] for k in keep} for r in f54["summary"] if r["kind"] == "event"]
    meta = f54["meta"]
    return {
        "unit": "mm",
        "first": meta["first"],
        "last": meta["last"],
        "n_event": meta["n_event"],
        "rows": rows,
    }


def gate_table(f58: dict) -> dict:
    """Evidence-gate table of ``F5.8.json``: per region and lead, BSS (CI) vs. climatology and vs. Markov, POD/FAR, status."""
    regions: dict[str, list] = {}
    for region, by_lead in f58["regions"].items():
        rows = []
        for lead in sorted(by_lead, key=int):
            r = by_lead[lead]
            rows.append(
                {
                    "lead": int(lead),
                    "n_events": r["n_events"],
                    "n_events_pooled": r["n_events_pooled"],
                    "base_rate": r["base_rate"],
                    "bss_log_clim": r["bss_log_clim"],
                    "bss_log_markov": r["bss_log_markov"],
                    "status": r["status"],
                    "prob_cap": r["prob_cap"],
                    "pod_far": {
                        k: {
                            f: r["pod_far"][k][f]
                            for f in ("pod", "far", "hits", "false_alarms", "n_risk_days")
                        }
                        for k in r["pod_far"]
                    },
                }
            )
        regions[region] = rows
    return {
        "quantile": f58["quantile"],
        "thresholds_mm": f58["thresholds"],
        "n_events_pooled_test": f58["n_events_pooled_test"],
        "n_events_test": f58["n_events_test"],
        "fc_source": f58["meta"]["fc_source"],
        "fc_period": f58["meta"]["fc_period"],
        "regions": regions,
    }


def build(
    forecasts: Path | str = DEFAULT_FORECASTS,
    reports: Path | str = DEFAULT_REPORTS,
    out_dir: Path | str = DEFAULT_OUT,
    obs_csv: Path | str | None = None,
) -> Path:
    forecasts, reports, out_dir = Path(forecasts), Path(reports), Path(out_dir)
    obs = read_obs(obs_csv or reports / DEFAULT_OBS_NAME)
    f52 = json.loads((reports / "F5.2.json").read_text(encoding="utf-8"))
    f54 = json.loads((reports / "F5.4.json").read_text(encoding="utf-8"))
    f58 = json.loads((reports / "F5.8.json").read_text(encoding="utf-8"))

    models: dict[str, dict] = {}
    leads: list[int] | None = None
    for model, label in MODELS.items():
        ds = xr.open_zarr(forecasts / f"{model}.zarr", consolidated=False)
        res = model_cases(ds, obs)
        if leads is None:
            leads = res["leads"]
        elif res["leads"] != leads:
            raise ValueError(f"{model}: leads {res['leads']} differ from {leads}")
        models[model] = {
            "label": label,
            "source": ds.attrs["source"],
            "license": ds.attrs["license"],
            "period": ds.attrs["period"],
            "n_members": res["n_members"],
            "events": res["events"],
        }
    dates = [e["date"] for m in models.values() for e in m["events"]]
    if not dates:
        raise ValueError("no event cases in the forecast stores")
    missing = [
        e["event_id"]
        for m in models.values()
        for e in m["events"]
        if e["obs_mm"] is None or not math.isfinite(e["obs_mm"])
    ]
    if missing:
        raise ValueError(f"events without an ERA5 observation: {missing[:5]}")
    period = f"{min(dates)}/{max(dates)}"

    cases = {
        "id": LAYER_ID,
        "title": TITLE,
        "source": SOURCE,
        "license": LICENSE,
        "period": period,
        "obs_source": OBS_SOURCE,
        "units": "mm",
        "leads": leads,
        "models": models,
    }
    skill = {
        "id": LAYER_ID,
        "obs_source": OBS_SOURCE,
        "models": skill_curves(f52),
        "aifs_vs_ifs": aifs_vs_ifs(f54),
        "gate": gate_table(f58),
    }
    manifest = LayerManifest(
        id=LAYER_ID,
        title=TITLE,
        kind="series",
        source=SOURCE,
        period=period,
        license=LICENSE,
        updated_at=datetime.now(UTC),
        files=["cases.json", "skill.json"],
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "cases.json", cases)
    _write_json(out_dir / "skill.json", skill)
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return out_dir

"""Viewer layer ``debris-catchments`` (plan/04, F4.3): small catchments ranked by SCS-CN peak discharge.

Output in ``<out>/`` (default ``data/processed/debris-catchments``), kind ``polygons``:

- ``catchments.geojson``  FeatureCollection of catchment polygons (EPSG:4326); properties: ``id``, ``target``
  (road / urban polygon they drain onto), ``area_km2``, ``mean_slope_deg``, ``relief_m``, ``longest_flow_path_m``,
  ``outlet_lon``, ``outlet_lat``.
- ``peaks.json``          per-catchment peak table and the metadata that qualifies it: rain source (IDF table, period,
  caveats), CN scenarios (value, HSG, citation status), catchment source/period, fixed caveats. ``catchments`` maps the
  catchment id to ``{"peak_m3s": {<cn id>: [one value per return period]}, "critical_duration_h": {<cn id>: [...]}}``;
  the order of the values is ``return_periods``. The critical duration is the one that maximises the peak
  (``scs.design_peaks``).

Several catchment Parquets (F4.1 runs: Routes 5/7, urban targets) can be concatenated; ids are renumbered 0..n-1 and
the original ids are kept as ``source_id``/``source_file``. A catchment that appears twice (same target and outlet) is
kept once.

Planar flow (D8 artifact on planar terrain, see ``stages/debris/catchments.py``): ``rectangularity``, ``elongation`` and
``planar_flow`` are read from the Parquet or, for older Parquets, computed here from the polygon. The viewer hides
``planar_flow`` catchments by default and ranks without them.

Overlap: when two catchments of different targets overlap by more than ``OVERLAP_FRACTION`` of the smaller one's area
(both non-planar), both are kept but the smaller gets ``overlaps_id`` (the id of the one it overlaps most). It stays
clickable and is left out of the ranking, so the same ground is not ranked twice.

Not an alert system: values are retrospective design-storm estimates, with no levels or thresholds.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
from shapely import STRtree, wkb
from shapely.geometry import mapping

from clima_nqn.layers.manifest import LayerManifest
from clima_nqn.stages.convection import idf as idf_mod
from clima_nqn.stages.debris import scs
from clima_nqn.stages.debris.catchments import (
    PLANAR_ELONGATION,
    PLANAR_RECTANGULARITY,
    PLANAR_STRIP_ELONGATION,
    is_planar_flow,
    shape_metrics,
)

LAYER_ID = "debris-catchments"
TITLE = "Aluviones: cuencas chicas"
DEFAULT_OUT = idf_mod.REPO_ROOT / "data" / "processed" / LAYER_ID
LICENSE = "Copernicus DEM (licencia Copernicus, términos sin verificar); IMERG CC BY 4.0; TR-55 (USDA, dominio público, sin verificar)"
RAIN_PERIOD = "2000-07-01/2025-06-30"  # hydrological years 2000/01-2024/25 (reports/03/F3.3.md)
RAIN_PERIOD_LABEL = "2000/01–2024/25 (años julio–junio)"

DURATIONS_H = (0.5, 1.0, 2.0, 3.0, 6.0, 12.0, 24.0)
RETURN_PERIODS = (2.0, 5.0, 10.0, 25.0, 50.0, 100.0)
EXTRAPOLATION_ABOVE_T = 50.0  # T > 2 x 25 years of record

# F3.3 IDF, Neuquén capital IMERG cell, GEV by L-moments, rain depth in mm (reports/03/F3.3.md, "Tabla IDF").
# Rows: duration (h); columns: T = 2, 5, 10, 25, 50, 100 (100 = extrapolation).
_IDF_DEPTH_MM = {
    0.5: (6.5, 9.9, 12.5, 16.1, 19.2, 22.4),
    1.0: (10.4, 15.0, 17.9, 21.2, 23.6, 25.9),
    2.0: (15.3, 22.2, 26.8, 32.8, 37.4, 42.0),
    3.0: (18.1, 26.9, 33.4, 42.5, 49.9, 57.8),
    6.0: (22.5, 34.4, 44.2, 59.2, 72.7, 88.4),
    12.0: (28.9, 46.6, 61.0, 83.0, 102.4, 125.0),
    24.0: (35.9, 59.5, 78.7, 108.0, 134.2, 164.4),
}
IDF_PARQUET = (
    idf_mod.OUT_PATH
)  # optional: read instead of the constant when present (method gev_lmom)
IDF_SOURCE = "GPM IMERG Final V07 (NASA GES DISC), IDF de F3.3 (GEV por L-momentos), celda de Neuquén capital"
IDF_NOTE = (
    "IDF solo con IMERG, sin corrección de sesgo: es un piso de la lluvia de diseño. Está ajustada en la celda de "
    "la capital; aplicarla a las cuencas de las Rutas 5 y 7 (cerca de Añelo) es sin verificar."
)

# USDA TR-55 (1986) Table 2-2d, arid and semiarid rangelands, desert shrub, poor hydrologic condition.
CN_SOURCE = "USDA NRCS TR-55 (1986), Tabla 2-2d, pastizal árido y semiárido, matorral desértico, condición pobre"
CN_SCENARIOS = (
    {"id": "hsg-b", "hsg": "B", "cn": 77.0, "central": False},
    {"id": "hsg-c", "hsg": "C", "cn": 85.0, "central": True},
    {"id": "hsg-d", "hsg": "D", "cn": 88.0, "central": False},
)
CN_NOTE = (
    "Escenarios de CN (TR-55), no medidos: no hay mapa de suelos ni de cobertura de las cuencas. Los valores 77, 85 y "
    "88 son los indicados por el usuario para el grupo hidrológico B, C y D; cotejo con la tabla del TR-55: sin verificar."
)
CAVEATS = (
    "IDF solo con IMERG, sin corrección de sesgo: es un piso, no la lluvia de un pluviómetro.",
    "IDF de la celda de la capital aplicada a cuencas lejanas: sin verificar.",
    "CN: escenarios de TR-55, no medidos (matorral desértico, condición pobre; B, C y D).",
    "SCS-CN y el hidrograma triangular no están validados en bardas patagónicas: sin verificar.",
    "T = 100 años es una extrapolación (más de 2 veces el registro de 25 años).",
    "Cuencas en franjas rectas sobre terreno plano (artefacto del D8, criterio propio, sin verificar): ocultas por defecto.",
    "Las cuencas que se superponen con otra cuenca de otro destino se quedan fuera del ranking.",
    "Análisis retrospectivo de lluvias de diseño. No es un sistema de alerta oficial.",
)


def load_idf(parquet: Path | None = None) -> tuple[dict[tuple[float, float], float], str]:
    """Design rains ``{(T, duration_h): depth_mm}`` and where they came from ("parquet" or "constant")."""
    path = Path(parquet) if parquet is not None else IDF_PARQUET
    if path.is_file():
        df = pq.read_table(path).to_pandas()
        df = df[df["method"] == "gev_lmom"]
        rains = {
            (float(r.return_period_yr), float(r.duration_h)): float(r.depth_mm)
            for r in df.itertuples()
        }
        want = {(t, d) for t in RETURN_PERIODS for d in DURATIONS_H}
        if want <= rains.keys():
            return {k: rains[k] for k in sorted(want)}, "parquet"
    return (
        {
            (t, d): v
            for d, row in _IDF_DEPTH_MM.items()
            for t, v in zip(RETURN_PERIODS, row, strict=True)
        },
        "constant",
    )


OVERLAP_FRACTION = 0.5  # of the smaller catchment's area; criterio propio, sin verificar
PLANAR_NOTE = (
    "Cuencas casi rectangulares y alargadas (rectangularidad >= {rect:g} y elongación >= {elong:g}) o franjas muy "
    "alargadas (elongación >= {strip:g}) sobre terreno plano: el D8 traza líneas paralelas que no convergen y cada "
    "línea o banda se vuelve una cuenca falsa. Criterio propio, sin verificar; el conteo cambia poco con otros cortes "
    "(rectangularidad 0,70: 292 contra 252 de 841; franjas con elongación 10 o 20: 86 o 74 contra 81)."
)


def find_overlaps(rows: Sequence[dict], fraction: float = OVERLAP_FRACTION) -> dict[int, int]:
    """``{smaller id: id it overlaps}`` for non-planar catchments of different targets overlapping > ``fraction``."""
    geoms = {r["id"]: wkb.loads(r["geometry"]) for r in rows if not r["planar_flow"]}
    by_id = {r["id"]: r for r in rows}
    ids = list(geoms)
    tree = STRtree([geoms[i] for i in ids])
    out: dict[int, int] = {}
    for i in ids:
        gi = geoms[i]
        best, best_area = None, 0.0
        for j in (ids[k] for k in tree.query(gi)):
            if j == i or by_id[j]["target"] == by_id[i]["target"]:
                continue
            gj = geoms[j]
            smaller = (gi.area, i) <= (gj.area, j)
            if not smaller:
                continue  # only the smaller of the pair is marked
            inter = gi.intersection(gj).area
            if gi.area > 0 and inter / gi.area > fraction and gj.area > best_area:
                best, best_area = j, gj.area
        if best is not None:
            out[i] = best
    return out


def read_catchments(paths: Sequence[Path | str]) -> tuple[list[dict], dict]:
    """Concatenate catchment Parquets; returns (rows with a WKB ``geometry``, sources metadata)."""
    rows: list[dict] = []
    seen: set[tuple[str, float, float]] = set()
    sources: list[dict] = []
    for p in paths:
        p = Path(p)
        table = pq.read_table(p)
        meta = {k.decode(): v.decode() for k, v in (table.schema.metadata or {}).items()}
        n = 0
        for r in table.to_pylist():
            key = (str(r["target"]), round(r["outlet_lon"], 6), round(r["outlet_lat"], 6))
            if key in seen:
                continue
            seen.add(key)
            row = {**r, "source_id": int(r["id"]), "source_file": p.name}
            if row.get("rectangularity") is None or row.get("elongation") is None:
                row["rectangularity"], row["elongation"] = shape_metrics(wkb.loads(r["geometry"]))
            # always re-apply the current rule, so older Parquets follow threshold changes
            row["planar_flow"] = is_planar_flow(row["rectangularity"], row["elongation"])
            rows.append(row)
            n += 1
        sources.append(
            {
                "file": p.name,
                "n": n,
                "source": meta.get("source", ""),
                "period": meta.get("period", ""),
            }
        )
    for i, r in enumerate(rows):
        r["id"] = i
    if not rows:
        raise ValueError("no catchments in the input Parquets")
    overlaps = find_overlaps(rows)
    for r in rows:
        r["overlaps_id"] = overlaps.get(r["id"])
    return rows, {"files": sources}


def _slope_pct(mean_slope_deg: float) -> float:
    return max(
        math.tan(math.radians(mean_slope_deg)) * 100.0, 0.1
    )  # floor: scs_lag_h needs slope > 0


def peaks_for(row: dict, rains: dict[tuple[float, float], float]) -> dict:
    """Peak (m3/s) and critical duration (h) per CN scenario and return period for one catchment row."""
    peak: dict[str, list[float]] = {}
    crit: dict[str, list[float]] = {}
    for sc in CN_SCENARIOS:
        dps = scs.design_peaks(
            row["area_km2"],
            sc["cn"],
            row["longest_flow_path_m"],
            _slope_pct(row["mean_slope_deg"]),
            rains,
        )
        by_t = {dp.return_period: dp for dp in dps}
        peak[sc["id"]] = [round(by_t[t].peak_m3s, 3) for t in RETURN_PERIODS]
        crit[sc["id"]] = [by_t[t].critical_duration_h for t in RETURN_PERIODS]
    return {"peak_m3s": peak, "critical_duration_h": crit}


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def _round_coords(obj, nd: int = 5):
    if isinstance(obj, (list, tuple)):
        return [_round_coords(x, nd) for x in obj]
    return round(obj, nd)


def build(
    catchment_paths: Sequence[Path | str],
    out_dir: Path | str = DEFAULT_OUT,
    *,
    idf_parquet: Path | None = None,
) -> Path:
    """Write the layer from one or more catchment Parquets and return its directory."""
    out_dir = Path(out_dir)
    rows, cmeta = read_catchments(catchment_paths)
    rains, idf_origin = load_idf(idf_parquet)

    features, table = [], {}
    for r in rows:
        geom = mapping(wkb.loads(r["geometry"]))
        geom = {"type": geom["type"], "coordinates": _round_coords(geom["coordinates"])}
        features.append(
            {
                "type": "Feature",
                "id": r["id"],
                "geometry": geom,
                "properties": {
                    "id": r["id"],
                    "target": r["target"],
                    "area_km2": round(r["area_km2"], 4),
                    "mean_slope_deg": round(r["mean_slope_deg"], 3),
                    "relief_m": round(r["relief_m"], 1),
                    "longest_flow_path_m": round(r["longest_flow_path_m"], 1),
                    "outlet_lon": round(r["outlet_lon"], 5),
                    "outlet_lat": round(r["outlet_lat"], 5),
                    "rectangularity": round(r["rectangularity"], 3),
                    "elongation": round(r["elongation"], 2),
                    "planar_flow": bool(r["planar_flow"]),
                    "overlaps_id": r["overlaps_id"],
                    "source_id": r["source_id"],
                    "source_file": r["source_file"],
                },
            }
        )
        table[str(r["id"])] = peaks_for(r, rains)

    n_planar = sum(bool(r["planar_flow"]) for r in rows)
    n_overlap = sum(r["overlaps_id"] is not None for r in rows)
    dem_periods = sorted({f["period"] for f in cmeta["files"] if f["period"]})
    dem_sources = sorted({f["source"] for f in cmeta["files"] if f["source"]})
    peaks = {
        "units": {"peak": "m3/s", "depth": "mm", "duration": "h", "area": "km2"},
        "return_periods": list(RETURN_PERIODS),
        "extrapolation_above_t": EXTRAPOLATION_ABOVE_T,
        "durations_h": list(DURATIONS_H),
        "rain": {
            "source": IDF_SOURCE,
            "period": RAIN_PERIOD_LABEL,
            "license": "CC BY 4.0 (IMERG)",
            "origin": idf_origin,
            "cell": "Neuquén capital (celda IMERG más cercana a Neuquén Aero)",
            "bias_correction": "ninguna (piso)",
            "note": IDF_NOTE,
            "depth_mm": {
                f"{t:g}": {f"{d:g}": rains[(t, d)] for d in DURATIONS_H} for t in RETURN_PERIODS
            },
        },
        "cn": {
            "label": "Escenarios de CN (TR-55), no medidos",
            "source": CN_SOURCE,
            "citation": "sin verificar",
            "note": CN_NOTE,
            "scenarios": [dict(sc) for sc in CN_SCENARIOS],
        },
        "method": scs.SOURCE,
        "catchments_source": {"sources": dem_sources, "periods": dem_periods, **cmeta},
        "caveats": list(CAVEATS),
        "n_catchments": len(rows),
        "n_ranked": len(rows) - n_planar - n_overlap,
        "planar_flow": {
            "min_rectangularity": PLANAR_RECTANGULARITY,
            "min_elongation": PLANAR_ELONGATION,
            "min_strip_elongation": PLANAR_STRIP_ELONGATION,
            "n_excluded": n_planar,
            "citation": "sin verificar",
            "note": PLANAR_NOTE.format(
                rect=PLANAR_RECTANGULARITY, elong=PLANAR_ELONGATION, strip=PLANAR_STRIP_ELONGATION
            ),
        },
        "overlap": {
            "min_fraction": OVERLAP_FRACTION,
            "n_excluded": n_overlap,
            "citation": "sin verificar",
            "note": (
                "Cuenca que se superpone en más de la mitad de su área con otra de otro destino (ruta o barrio): "
                "queda en el mapa pero fuera del ranking, para no contar dos veces el mismo terreno."
            ),
        },
        "catchments": table,
    }
    manifest = LayerManifest(
        id=LAYER_ID,
        title=TITLE,
        kind="polygons",
        source="Copernicus DEM GLO-30 (cuencas, F4.1); IMERG Final V07 (IDF, F3.3); escenarios de CN de TR-55",
        period=RAIN_PERIOD,
        license=LICENSE,
        updated_at=datetime.now(UTC),
        files=["catchments.geojson", "peaks.json"],
    )
    _write_json(out_dir / "catchments.geojson", {"type": "FeatureCollection", "features": features})
    _write_json(out_dir / "peaks.json", peaks)
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "catchments", nargs="+", type=Path, help="catchment Parquet(s) from `debris catchments`"
    )
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = p.parse_args(argv)
    print(build(a.catchments, a.out))


if __name__ == "__main__":
    main()

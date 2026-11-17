"""Gauge basins delineated from HydroBASINS level 12 (F2.5).

Usage (from ``backend/``)::

    uv run clima-nqn flow basins --hybas ../data/raw/hydrobasins/hybas_l12_nqn.parquet

For every gauge the level-12 polygon that contains the gauge point is found, every polygon upstream
of it is collected through ``NEXT_DOWN`` (the polygon itself included) and the set is dissolved.
Polygons whose ``NEXT_SINK`` differs from the gauge polygon's (endorheic depressions that HydroBASINS
links to the river but excludes from ``UP_AREA``) are left out together with what drains into them;
without that rule the Neuquen basin would be 5 % larger than its ``UP_AREA``.
Caveat: the polygon holding the gauge extends past the gauge point (the gauge sits somewhere inside
it, not at its outlet), so the delineated basin is slightly larger than the true gauge basin.

Area: the dissolved polygon is projected to a cylindrical equal-area projection on a sphere of
radius 6371.0088 km with the standard parallel at the polygon centroid latitude
(``x = R lon cos(lat0)``, ``y = R sin(lat) / cos(lat0)``), which preserves area exactly on the
sphere; the difference to the ellipsoid is at most about 0.5 %. No pyproj needed.

Source: HydroBASINS v1c level 12 (Lehner & Grill 2013, Hydrol. Process. 27, 2171-2186), HydroSHEDS
licence (free use with citation, https://www.hydrosheds.org).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import mapping, shape

EARTH_RADIUS_KM = 6371.0088
COORD_DECIMALS = 5
DEFAULT_GEOJSON = Path(__file__).with_name("gauge_basins.geojson")
SOURCE = (
    "HydroBASINS v1c level 12 (Lehner & Grill 2013, Hydrol. Process. 27, 2171-2186; HydroSHEDS "
    "licence: free use with citation, https://www.hydrosheds.org)"
)
NOTE = (
    "delineated upstream of the level-12 polygon holding the gauge: the polygon extends past the "
    "gauge point; "
    "upstream polygons with a different NEXT_SINK (endorheic, excluded from UP_AREA) are left out"
)
AREA_NOTE = (
    "area_km2: cylindrical equal-area projection on a sphere (R = 6371.0088 km, standard parallel at "
    "the centroid latitude); up_area_km2: HydroBASINS UP_AREA of the gauge polygon"
)

Station = tuple[float, float]  # (lon, lat)


def area_km2(geom) -> float:
    """Area (km2) of a lon/lat geometry on a sphere (exact cylindrical equal-area projection)."""
    lat0 = math.radians(geom.centroid.y)
    k = math.cos(lat0)
    r = EARTH_RADIUS_KM

    def project(xy: np.ndarray) -> np.ndarray:
        lon, lat = np.radians(xy[:, 0]), np.radians(xy[:, 1])
        return np.column_stack([r * lon * k, r * np.sin(lat) / k])

    return float(shapely.transform(geom, project).area)


def upstream_ids(
    next_down: dict[int, int], outlet: int, next_sink: dict[int, int] | None = None
) -> set[int]:
    """``outlet`` and every id that drains into it (through ``next_down``).

    With ``next_sink``, ids whose sink differs from the outlet's (endorheic) are not followed.
    """
    children: dict[int, list[int]] = {}
    for hid, nxt in next_down.items():
        children.setdefault(nxt, []).append(hid)
    found, stack = {outlet}, [outlet]
    while stack:
        for c in children.get(stack.pop(), ()):
            if next_sink is not None and next_sink[c] != next_sink[outlet]:
                continue
            if c not in found:
                found.add(c)
                stack.append(c)
    return found


def _load(hybas) -> pd.DataFrame:
    df = pd.read_parquet(hybas) if not isinstance(hybas, pd.DataFrame) else hybas
    df = df.copy()
    if df["geom"].dtype == object and len(df) and isinstance(df["geom"].iloc[0], bytes | bytearray):
        df["geom"] = shapely.from_wkb(df["geom"].to_numpy())
    return df


def delineate_with_info(
    hybas, stations: dict[int, Station]
) -> tuple[dict[int, object], dict[int, dict]]:
    """Basins and a per-station report ``{gauge_hybas_id, up_area_km2, n_polygons, area_km2}``.

    ``hybas`` is the GeoParquet path (``geom`` as WKB) or an equivalent DataFrame; ``stations`` maps
    id to ``(lon, lat)``. A gauge inside no polygon raises ``ValueError``.
    """
    df = _load(hybas)
    geoms = df["geom"].to_numpy()
    ids = df["HYBAS_ID"].to_numpy()
    tree = shapely.STRtree(geoms)
    next_down = dict(zip(ids.tolist(), df["NEXT_DOWN"].to_numpy().tolist(), strict=True))
    up_area = dict(zip(ids.tolist(), df["UP_AREA"].to_numpy().tolist(), strict=True))
    sinks = (
        dict(zip(ids.tolist(), df["NEXT_SINK"].to_numpy().tolist(), strict=True))
        if "NEXT_SINK" in df
        else None
    )
    index = {int(h): i for i, h in enumerate(ids)}
    basins: dict[int, object] = {}
    info: dict[int, dict] = {}
    for sid, (lon, lat) in sorted(stations.items()):
        point = shapely.Point(lon, lat)
        hits = [int(i) for i in tree.query(point, predicate="intersects")]
        if not hits:
            raise ValueError(f"station {sid} ({lon}, {lat}) is inside no HydroBASINS polygon")
        gauge = int(ids[min(hits)])  # on a shared edge the lowest row wins (deterministic)
        all_up = upstream_ids(next_down, gauge)
        members = sorted(upstream_ids(next_down, gauge, sinks))
        merged = shapely.union_all([geoms[index[m]] for m in members])
        basins[sid] = merged
        info[sid] = {
            "gauge_hybas_id": gauge,
            "up_area_km2": float(up_area[gauge]),
            "n_polygons": len(members),
            "n_endorheic_excluded": len(all_up) - len(members),
            "area_km2": area_km2(merged),
        }
    return basins, info


def delineate(hybas, stations: dict[int, Station]) -> dict[int, object]:
    """Upstream basin (dissolved shapely geometry) of every gauge, see :func:`delineate_with_info`."""
    return delineate_with_info(hybas, stations)[0]


def _round(geom, decimals: int = COORD_DECIMALS):
    out = shapely.transform(geom, lambda c: np.round(c, decimals))
    return out if out.is_valid else shapely.make_valid(out)


def write_geojson(
    basins: dict[int, object],
    info: dict[int, dict],
    path: Path | str,
    names: dict[int, str] | None = None,
    simplify: float | None = None,
) -> Path:
    """Write the basins as a GeoJSON FeatureCollection (coordinates rounded to 5 decimals).

    ``info`` is the report of :func:`delineate_with_info`. ``simplify`` (degrees, at most 0.002) is
    only for keeping the file small and is recorded in the file when used.
    """
    if simplify is not None and not 0 < simplify <= 0.002:
        raise ValueError("simplify tolerance must be in (0, 0.002] degrees")
    features = []
    for sid in sorted(basins):
        geom = basins[sid]
        if simplify:
            geom = geom.simplify(simplify, preserve_topology=True)
        geom = _round(geom)
        props = {
            "station_id": int(sid),
            "name": (names or {}).get(sid),
            "area_km2": round(area_km2(geom), 1),
            "up_area_km2": round(info[sid]["up_area_km2"], 1),
            "n_polygons": int(info[sid]["n_polygons"]),
            "n_endorheic_excluded": int(info[sid].get("n_endorheic_excluded", 0)),
            "gauge_hybas_id": int(info[sid]["gauge_hybas_id"]),
        }
        features.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
    doc = {
        "type": "FeatureCollection",
        "title": "Upstream basins of the F2.5 gauges",
        "source": SOURCE,
        "license": SOURCE,
        "note": NOTE,
        "area_note": AREA_NOTE,
        "coordinate_decimals": COORD_DECIMALS,
        "simplify_tolerance_deg": simplify,
        "features": features,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return path


def read_geojson(path: Path | str = DEFAULT_GEOJSON) -> dict[int, object]:
    """``{station_id: geometry}`` from a file written by :func:`write_geojson`."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(f["properties"]["station_id"]): shape(f["geometry"]) for f in doc["features"]}


def read_geojson_meta(path: Path | str = DEFAULT_GEOJSON) -> dict:
    """Top-level ``source``, ``license``, ``note`` and the per-station properties."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "source": doc.get("source"),
        "license": doc.get("license"),
        "note": doc.get("note"),
        "stations": {int(f["properties"]["station_id"]): f["properties"] for f in doc["features"]},
    }


def stations_from_json(
    path: Path | str,
) -> tuple[dict[int, Station], dict[int, str], dict[int, float]]:
    """``stations.json`` of F2.1 -> ``({id: (lon, lat)}, {id: name}, {id: SNIH area_km2})``."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["stations"]
    coords = {int(r["id"]): (float(r["lon"]), float(r["lat"])) for r in rows}
    names = {int(r["id"]): r.get("name") for r in rows}
    areas = {int(r["id"]): float(r["area_km2"]) for r in rows if r.get("area_km2") is not None}
    return coords, names, areas


def build(
    hybas: Path | str,
    stations_json: Path | str,
    out: Path | str = DEFAULT_GEOJSON,
    progress: Callable[[str], None] = print,
    max_bytes: int = 1_500_000,
) -> Path:
    """Delineate the gauges of ``stations_json`` and write the GeoJSON (simplified only if too big)."""
    coords, names, snih = stations_from_json(stations_json)
    basins, info = delineate_with_info(hybas, coords)
    path = write_geojson(basins, info, out, names)
    if path.stat().st_size > max_bytes:
        path = write_geojson(basins, info, out, names, simplify=0.001)
        progress(f"simplified with tolerance 0.001 degrees (file was over {max_bytes} bytes)")
    for sid in sorted(basins):
        i = info[sid]
        ref = f"SNIH {snih[sid]:.0f}" if sid in snih else "SNIH n/a"
        progress(
            f"{sid} {names.get(sid)}: area {i['area_km2']:.0f} km2 ({ref}); HydroBASINS UP_AREA "
            f"{i['up_area_km2']:.0f}; {i['n_polygons']} polygons "
            f"({i['n_endorheic_excluded']} endorheic excluded); gauge polygon {i['gauge_hybas_id']}"
        )
    return path

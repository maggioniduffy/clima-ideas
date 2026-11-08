"""Extreme daily rain over the Neuquén cordillera vs atmospheric rivers (plan/01, F1.4).

Question: what fraction of extreme-rain days coincides with an AR event of the F1.3 catalog?

Conventions:
- Days are UTC days. ERA5 ``tp`` is an hourly accumulation ending at its stamp, so the total of day D
  is the sum of the stamps D 01:00 .. D+1 00:00 (24 stamps). The D+1 00:00 stamp of Dec 31 lives in
  the next year's store; days with fewer than 24 stamps (the end of the record) are dropped.
- A day is an AR day when some catalog event interval [start, end) overlaps [D 00:00, D+1 00:00);
  with tolerance k days, overlap with [D-k, D+1+k).
- Extreme thresholds use ``numpy.quantile`` (linear interpolation) and days are extreme when
  ``precip >= threshold``.
- ``ratio`` is ``frac_extreme_with_ar / base_rate``; ``base_rate`` is the share of all days that are AR.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.stages.ar import catalog

SEASONS = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}
Z95 = 1.959964
WET_DAY_MM = 1.0
DEFINITIONS = {
    "main": "MAIN: precipitación media diaria del polígono ≥ su p99 (todos los días).",
    "p95": "Variante: precipitación media diaria del polígono ≥ su p95 (todos los días).",
    "per_cell": (
        "Por celda: para cada celda, días ≥ el p99 de sus días húmedos (≥ 1 mm); "
        "se agrupan los pares celda-día."
    ),
    "main_tol1": "MAIN con tolerancia ±1 día para el día con río atmosférico.",
}


# --- daily precipitation -------------------------------------------------------------------


def _year_of(path: Path) -> int:
    return int(Path(path).name.split(".")[0])


def _read_tp(
    path: Path, mask: np.ndarray | None
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    """Hourly ``tp`` in mm of the polygon cells of one store: (times, values (time, cell), mask)."""
    ds = xr.open_zarr(path, consolidated=False, chunks=None)
    try:
        if mask is None:
            mask = catalog.polygon_mask(ds["lat"].values, ds["lon"].values).values.astype(bool)
            if not mask.any():
                raise ValueError("no grid cell falls inside the polygon")
        tp = ds["tp"].transpose("time", "lat", "lon").values[:, mask].astype("float64") * 1000.0
        return pd.DatetimeIndex(ds["time"].values), tp, mask
    finally:
        ds.close()


def daily_precip(
    era5_paths: Sequence[Path],
    polygon: Sequence[tuple[float, float]] = catalog.CORDILLERA_POLYGON,
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily precipitation (mm) per UTC day: polygon mean and per-cell (day × cell) table.

    One year at a time (plus the first stamp of the next year's store). Days with fewer than 24
    stamps are dropped. ``polygon`` is (lon, lat) vertices.
    """
    by_year = {_year_of(Path(p)): Path(p) for p in era5_paths}
    if not by_year:
        raise ValueError("no ERA5 stores")
    masks: dict[tuple, np.ndarray] = {}

    def mask_for(path: Path) -> np.ndarray:
        ds = xr.open_zarr(path, consolidated=False, chunks=None)
        try:
            lat, lon = ds["lat"].values, ds["lon"].values
        finally:
            ds.close()
        key = (lat.tobytes(), lon.tobytes())
        if key not in masks:
            m = catalog.polygon_mask(lat, lon, polygon).values.astype(bool)
            if not m.any():
                raise ValueError("no grid cell falls inside the polygon")
            masks[key] = m
        return masks[key]

    parts: list[pd.DataFrame] = []
    for year in sorted(by_year):
        mask = mask_for(by_year[year])
        times, tp, _ = _read_tp(by_year[year], mask)
        jan1 = pd.Timestamp(year, 1, 1)
        keep = times > jan1  # the Jan 1 00:00 stamp closes Dec 31 of the previous year
        times, tp = times[keep], tp[keep]
        nxt = by_year.get(year + 1)
        if nxt is not None:
            n_times, n_tp, _ = _read_tp(nxt, mask_for(nxt))
            first = n_times == pd.Timestamp(year + 1, 1, 1)
            if first.any() and n_tp.shape[1] == tp.shape[1]:
                times = times.append(n_times[first])
                tp = np.vstack([tp, n_tp[first]])
        day = (times - pd.Timedelta(hours=1)).floor("D")
        frame = pd.DataFrame(tp, index=day)
        grouped = frame.groupby(level=0)
        totals = grouped.sum()
        totals = totals[grouped.size() == 24]
        totals = totals[(totals.index >= jan1) & (totals.index < pd.Timestamp(year + 1, 1, 1))]
        parts.append(totals)
    cells = pd.concat(parts).sort_index()
    cells.index.name = "day"
    cells.columns = range(cells.shape[1])
    mean = cells.mean(axis=1)
    mean.name = "precip_mm"
    return mean, cells


# --- AR days -------------------------------------------------------------------------------


def ar_days(events: pd.DataFrame, days: pd.DatetimeIndex, tolerance_days: int = 0) -> pd.Series:
    """Boolean per day: an event [start, end) overlaps [D - k, D + 1 + k) (days, k = tolerance)."""
    days = pd.DatetimeIndex(days)
    flags = np.zeros(len(days), dtype=bool)
    order = np.argsort(days.values)
    sdays = days[order]
    k = pd.Timedelta(days=tolerance_days)
    one = pd.Timedelta(days=1)
    for start, end in zip(events["start"], events["end"], strict=True):
        i0 = sdays.searchsorted(start - one - k, side="right")  # D + 1 + k > start
        i1 = sdays.searchsorted(end + k, side="left")  # D - k < end
        if i1 > i0:
            flags[order[i0:i1]] = True
    return pd.Series(flags, index=days, name="is_ar")


# --- statistics ----------------------------------------------------------------------------


def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a proportion ``k / n`` (95 % by default)."""
    if n <= 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _frac(num: float, den: float) -> float:
    return num / den if den > 0 else math.nan


def _stats(precip: np.ndarray, is_ar: np.ndarray, is_ext: np.ndarray, threshold: float) -> dict:
    n_days = len(precip)
    n_ext = int(is_ext.sum())
    n_both = int((is_ext & is_ar).sum())
    frac = _frac(n_both, n_ext)
    base = _frac(int(is_ar.sum()), n_days)
    lo, hi = wilson_interval(n_both, n_ext)
    volume = float(precip[is_ext].sum())
    return {
        "n_days": n_days,
        "n_extreme": n_ext,
        "threshold_mm": float(threshold),
        "n_extreme_with_ar": n_both,
        "frac_extreme_with_ar": frac,
        "ci95_low": lo,
        "ci95_high": hi,
        "base_rate": base,
        "ratio": frac / base if base > 0 and not math.isnan(frac) else math.nan,
        "frac_extreme_precip_volume_with_ar": _frac(float(precip[is_ext & is_ar].sum()), volume),
    }


def coincidence_stats(
    precip: np.ndarray,
    is_ar: np.ndarray,
    is_extreme: np.ndarray,
    threshold_mm: float,
    months: np.ndarray | None = None,
) -> dict:
    """Coincidence of extreme days with AR days; with ``months`` also split by season.

    Seasons reuse the same extreme flags and ``threshold_mm`` (the global one); ``base_rate`` of a
    season is the AR share of that season's days.
    """
    precip = np.asarray(precip, dtype=float)
    is_ar = np.asarray(is_ar, dtype=bool)
    is_extreme = np.asarray(is_extreme, dtype=bool)
    out = _stats(precip, is_ar, is_extreme, threshold_mm)
    if months is not None:
        months = np.asarray(months)
        out["seasons"] = {}
        for name, ms in SEASONS.items():
            sel = np.isin(months, ms)
            out["seasons"][name] = _stats(precip[sel], is_ar[sel], is_extreme[sel], threshold_mm)
    return out


def per_cell_stats(
    cells: pd.DataFrame, ar: pd.Series, q: float = 0.99, wet_mm: float = WET_DAY_MM
) -> dict:
    """Pool cell-days that reach each cell's ``q`` quantile of its wet days (>= ``wet_mm``).

    Cells without wet days are skipped. ``threshold_mm`` is the median over cells (min and max too).
    """
    ar_vals = ar.reindex(cells.index).to_numpy(dtype=bool)
    months = cells.index.month.to_numpy()
    precip, flags, ars, mons, thr = [], [], [], [], []
    for col in cells.columns:
        v = cells[col].to_numpy(dtype=float)
        wet = v[v >= wet_mm]
        if not len(wet):
            continue
        t = float(np.quantile(wet, q))
        thr.append(t)
        precip.append(v)
        flags.append(v >= t)
        ars.append(ar_vals)
        mons.append(months)
    if not thr:
        raise ValueError("no cell has wet days")
    out = coincidence_stats(
        np.concatenate(precip),
        np.concatenate(ars),
        np.concatenate(flags),
        float(np.median(thr)),
        np.concatenate(mons),
    )
    out.update(n_cells=len(thr), threshold_mm_min=min(thr), threshold_mm_max=max(thr))
    return out


def compute_results(mean: pd.Series, cells: pd.DataFrame, events: pd.DataFrame) -> dict:
    """All F1.4 definitions: ``main``, ``p95``, ``per_cell`` and ``main_tol1``."""
    days = pd.DatetimeIndex(mean.index)
    ar0 = ar_days(events, days, 0)
    ar1 = ar_days(events, days, 1)
    precip = mean.to_numpy(dtype=float)
    months = days.month.to_numpy()

    def by_quantile(q: float, ar: pd.Series) -> dict:
        thr = float(np.quantile(precip, q))
        return coincidence_stats(precip, ar.to_numpy(), precip >= thr, thr, months)

    return {
        "main": by_quantile(0.99, ar0),
        "p95": by_quantile(0.95, ar0),
        "per_cell": per_cell_stats(cells, ar0),
        "main_tol1": by_quantile(0.99, ar1),
    }


# --- report --------------------------------------------------------------------------------


def _pct(x: float) -> str:
    return "n/d" if x is None or math.isnan(x) else f"{x * 100:.1f} %"


def _num(x: float, nd: int = 2) -> str:
    return "n/d" if x is None or math.isnan(x) else f"{x:.{nd}f}"


def _ci(s: dict) -> str:
    return f"{_pct(s['ci95_low'])} – {_pct(s['ci95_high'])}"


def headline(results: dict) -> str:
    s = results["main"]
    return (
        f"MAIN (p99 polygon-mean, {_num(s['threshold_mm'])} mm/day): "
        f"{s['n_extreme_with_ar']}/{s['n_extreme']} extreme days with AR = "
        f"{_pct(s['frac_extreme_with_ar'])} (95% CI {_ci(s)}), "
        f"base rate {_pct(s['base_rate'])}, ratio {_num(s['ratio'])}"
    )


def _definition_table(s: dict) -> list[str]:
    rows = [
        ("Días analizados", f"{s['n_days']}"),
        ("Días extremos", f"{s['n_extreme']}"),
        ("Umbral (mm/día)", _num(s["threshold_mm"])),
    ]
    if "n_cells" in s:
        rows.append(
            (
                "Celdas / rango de umbrales (mm/día)",
                f"{s['n_cells']} / {_num(s['threshold_mm_min'])} – {_num(s['threshold_mm_max'])}",
            )
        )
    rows += [
        ("Extremos con río atmosférico", f"{s['n_extreme_with_ar']}"),
        ("Fracción de extremos con RA", _pct(s["frac_extreme_with_ar"])),
        ("IC 95 % (Wilson)", _ci(s)),
        ("Tasa base (todos los días con RA)", _pct(s["base_rate"])),
        ("Razón (fracción / tasa base)", _num(s["ratio"])),
        (
            "Lluvia de días extremos que cae en días con RA",
            _pct(s["frac_extreme_precip_volume_with_ar"]),
        ),
    ]
    return ["| Métrica | Valor |", "|---|---|", *[f"| {a} | {b} |" for a, b in rows]]


def _season_table(s: dict) -> list[str]:
    lines = [
        (
            "| Estación | Días | Extremos | Umbral (mm/día) | Extremos con RA | Fracción | IC 95 % | "
            "Tasa base | Razón |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, v in s["seasons"].items():
        lines.append(
            f"| {name} | {v['n_days']} | {v['n_extreme']} | {_num(v['threshold_mm'])} | "
            f"{v['n_extreme_with_ar']} | {_pct(v['frac_extreme_with_ar'])} | {_ci(v)} | "
            f"{_pct(v['base_rate'])} | {_num(v['ratio'])} |"
        )
    return lines


def _clean(obj):
    """JSON-safe copy: NaN -> None, numpy scalars -> Python."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def write_report(results: dict, path: Path | str, meta: dict) -> Path:
    """Write the Spanish Markdown report to ``path`` and the numbers to the same name with ``.json``.

    ``meta`` keys: ``period``, ``n_events``, ``bard_threshold``, ``polygon`` (lon, lat vertices).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    main = results["main"]
    lines = [
        "# F1.4 — Lluvia extrema y ríos atmosféricos (cordillera neuquina)",
        "",
        (
            "Pregunta: ¿qué fracción de los días de lluvia extrema sobre la cordillera neuquina coincide "
            "con un evento de río atmosférico (RA)?"
        ),
        "",
        "## Fuente y alcance",
        "",
        (
            "- Fuente: ERA5 (Copernicus Climate Change Service) via ARCO-ERA5, CC-BY 4.0; "
            "detecciones TECA BARD 6.0.0 (catálogo de eventos F1.3)."
        ),
        f"- Período: {meta.get('period', 'sin verificar')}.",
        f"- Eventos RA en el catálogo: {meta.get('n_events', 'sin verificar')}.",
        f"- Umbral BARD de `ar_probability`: {meta.get('bard_threshold', 'sin verificar')}.",
        f"- Polígono (lon, lat): {json.dumps(meta.get('polygon'))} — aproximación, sin verificar.",
        "- Precipitación: `tp` horaria de ERA5, suma diaria en día UTC D = estampas D 01:00 .. D+1 00:00.",
        "",
        "## Definiciones",
        "",
        *[f"- {text}" for text in DEFINITIONS.values()],
        (
            "- Día con RA: algún evento [inicio, fin) se solapa con [D 00:00, D+1 00:00); "
            "con tolerancia k, con [D−k, D+1+k)."
        ),
        "- Tasa base: fracción de todos los días con río atmosférico.",
        "- Razón: fracción de extremos con RA dividida por la tasa base (1 = sin asociación).",
        "",
        "## Resultado principal",
        "",
        (
            f"{_pct(main['frac_extreme_with_ar'])} de los {main['n_extreme']} días extremos (MAIN) "
            f"coinciden con un RA (IC 95 % {_ci(main)}); tasa base {_pct(main['base_rate'])}, "
            f"razón {_num(main['ratio'])}."
        ),
        "",
    ]
    titles = {
        "main": "MAIN: media del polígono ≥ p99",
        "p95": "Media del polígono ≥ p95",
        "per_cell": "Por celda: ≥ p99 de días húmedos (≥ 1 mm)",
        "main_tol1": "MAIN con tolerancia ±1 día",
    }
    for key, title in titles.items():
        if key in results:
            lines += [f"## {title}", "", *_definition_table(results[key]), ""]
    lines += [
        "## Estaciones (MAIN)",
        "",
        "Umbral global del MAIN en todas las estaciones; la tasa base es la de cada estación.",
        "",
        *_season_table(main),
        "",
        "## Salvedades",
        "",
        "- Días UTC, no días locales (Argentina está en UTC−3).",
        (
            "- ERA5 es un reanálisis, no datos de estaciones: la lluvia extrema puede estar subestimada "
            "en terreno complejo."
        ),
        "- La detección depende del umbral BARD (0.67 por defecto); otros umbrales cambian los números.",
        "- El polígono es una aproximación sin verificar.",
        "- Es un análisis retrospectivo de coincidencia, no prueba causalidad ni es un sistema de alerta.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(_clean({"meta": meta, "results": results}), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# --- entry point ---------------------------------------------------------------------------


def run(events_path: Path | str, era5_paths: Sequence[Path], out_dir: Path | str) -> dict:
    """Read the F1.3 catalog, compute every definition and write ``F1.4.md`` / ``F1.4.json``."""
    events = pd.read_parquet(events_path)
    cat_meta = catalog.read_metadata(events_path)
    polygon = [tuple(v) for v in json.loads(cat_meta["polygon"])] if "polygon" in cat_meta else None
    polygon = polygon or catalog.CORDILLERA_POLYGON
    mean, cells = daily_precip(era5_paths, polygon)
    results = compute_results(mean, cells, events)
    meta = {
        "period": f"{mean.index[0]:%Y-%m-%d}/{mean.index[-1]:%Y-%m-%d}",
        "catalog_period": cat_meta.get("period"),
        "n_events": len(events),
        "bard_threshold": float(cat_meta["threshold"]) if "threshold" in cat_meta else None,
        "polygon": [list(v) for v in polygon],
        "source": "ERA5 via ARCO-ERA5 (CC-BY 4.0) + TECA BARD 6.0.0",
    }
    write_report(results, Path(out_dir) / "F1.4.md", meta)
    return results

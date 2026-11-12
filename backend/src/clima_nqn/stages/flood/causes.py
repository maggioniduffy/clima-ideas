"""Probable cause of the major floods: atmospheric river and rain on snow (plan/02, F2.3).

Question: how many of the annual floods coincide with an atmospheric river (AR) of the F1.3 catalog,
how many would coincide by chance, and in how many did the river fall on a snowpack that then shrank?

Rules fixed before looking at results (odd/tasks/floods.md, S8):
- Floods: the annual maxima of complete hydrological years (``extremes.annual_maxima``, same rule as
  F2.2) whose peak lies inside the period covered by the AR catalog; the window of the sensitivity
  analysis must also fit in it (peak - 7 days >= catalog start). Each flood carries its GEV return
  period from F2.2 (``data/flow/gev/<id>.json``; refitted without the bootstrap if the file is absent).
- AR label: at least one catalog event active on any day of ``[peak - w, peak]``; primary ``w = 3``.
  A day is active for an event from the day of its start to the day of its last AR step (``end`` is
  exclusive). Days are calendar days as stored (flow is local, UTC-3; the catalog is UTC).
- Sensitivity ``w = 0..7``: share of floods with an AR and the share expected by chance: for each flood
  a random date in the same calendar month of a random year of the catalog period (10 000 draws, fixed
  seed), same window rule; the p-value is the share of draws with a share >= the observed one.
- Snow, over the station's upstream box (``io.snow.UPSTREAM_BOXES``, approximate rectangles): snow-covered
  fraction = share of cells with >= 10 mm of water equivalent at the window start (``peak - w``);
  area-mean SWE at the window start and at the peak.
- Labels (primary ``w = 3``): AR + snow-covered fraction >= 0.2 + mean SWE lower at the peak ->
  "río atmosférico + lluvia sobre nieve probable"; AR otherwise -> "río atmosférico"; no AR with the
  same snow conditions -> "deshielo sin río atmosférico"; the rest -> "sin causa identificada". The
  event's 0 degC level is reported, not thresholded. Without snow data the snow part is "sin dato" and
  the label uses the AR part only (flagged).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.io import era5, flow, snow
from clima_nqn.stages.ar import catalog as ar_catalog
from clima_nqn.stages.ar import enso as ar_enso
from clima_nqn.stages.flood import extremes

W_PRIMARY = 3
W_RANGE = tuple(range(8))
N_PERM = 10000
SEED = 20260513
SWE_COVER_MIN_M = 0.010  # 10 mm w.e.
COVER_FRAC_MIN = 0.2
SHORT_RECORD_YEARS = 30
DEFAULT_STATIONS = extremes.DEFAULT_STATIONS
OUT_PATH = flow.OUT_DIR / "causes.json"
DEFAULT_CATALOG = flow.OUT_DIR.parent / "processed" / "ar-events" / "events.parquet"
REPORT_PATH = Path(__file__).resolve().parents[5] / "reports" / "02" / "F2.3.md"
L_AR_SNOW = "río atmosférico + lluvia sobre nieve probable"
L_AR = "río atmosférico"
L_SNOW = "deshielo sin río atmosférico"
L_NONE = "sin causa identificada"
LABELS = (L_AR_SNOW, L_AR, L_SNOW, L_NONE)
SHORT_NOTE = "registro corto (unos 25 años completos): período de retorno y conteos poco confiables"
SNOW_SOURCE_NOTE = (
    "ERA5 a 0,25° (vía ARCO-ERA5, Copernicus Climate Change Service, CC-BY 4.0), NO ERA5-Land; "
    "las celdas de 0,25° son gruesas para estas cuencas"
)


# --- catalog and AR window -----------------------------------------------------------------------


def load_catalog(path: Path | str) -> tuple[pd.DataFrame, tuple[pd.Timestamp, pd.Timestamp]]:
    """Events and the ``(first, last)`` day of the catalog period."""
    events = pd.read_parquet(path)
    period = ar_catalog.read_metadata(path).get("period")
    if not period:
        raise ValueError(f"{path} has no catalog period in its metadata")
    first, _, last = period.partition("/")
    return events, (pd.Timestamp(first), pd.Timestamp(last))


def _event_days(events: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    first = events["start"].dt.normalize()
    last = (events["end"] - pd.Timedelta(nanoseconds=1)).dt.normalize()  # ``end`` is exclusive
    return first, last


def matching_events(events: pd.DataFrame, peak: pd.Timestamp, w: int) -> pd.DataFrame:
    """Events active on any day of ``[peak - w, peak]``."""
    if events.empty:
        return events
    peak = pd.Timestamp(peak).normalize()
    first, last = _event_days(events)
    return events[(first <= peak) & (last >= peak - pd.Timedelta(days=w))]


def active_days(events: pd.DataFrame, period: tuple[pd.Timestamp, pd.Timestamp]) -> np.ndarray:
    """Boolean per day of the catalog period: is any event active that day?"""
    start, end = (p.normalize() for p in period)
    n = (end - start).days + 1
    active = np.zeros(n, dtype=bool)
    if events.empty:
        return active
    first, last = _event_days(events)
    for a, b in zip(first, last, strict=True):
        lo, hi = max((a - start).days, 0), min((b - start).days, n - 1)
        if hi >= lo:
            active[lo : hi + 1] = True
    return active


# --- floods ---------------------------------------------------------------------------------------


def select_floods(
    df: pd.DataFrame, start_month: int, period: tuple[pd.Timestamp, pd.Timestamp]
) -> pd.DataFrame:
    """Annual maxima of complete years whose peak and widest window fit in the catalog period."""
    maxima, _ = extremes.annual_maxima(df, start_month)
    lo = period[0].normalize() + pd.Timedelta(days=max(W_RANGE))
    hi = period[1].normalize()
    keep = (maxima["date"] >= lo) & (maxima["date"] <= hi)
    return maxima[keep].reset_index(drop=True)


def _station_meta(flow_dir: Path) -> dict[int, dict]:
    stations = json.loads((flow_dir / "stations.json").read_text(encoding="utf-8"))["stations"]
    return {s["id"]: s for s in stations}


def collect_floods(
    flow_dir: Path | str,
    stations: Sequence[int] | None,
    period: tuple[pd.Timestamp, pd.Timestamp],
) -> dict[int, pd.DataFrame]:
    """Floods of every station (default: the natural ones) by station id."""
    flow_dir = Path(flow_dir)
    meta = _station_meta(flow_dir)
    out = {}
    for sid in stations or DEFAULT_STATIONS:
        df = flow.read_flow(flow_dir / f"{sid}.parquet")
        out[sid] = select_floods(df, meta[sid].get("hydro_year_start_month", 4), period)
    return out


def _gev_fit(sid: int, df: pd.DataFrame, meta: dict, gev_dir: Path) -> tuple[dict, str]:
    path = gev_dir / f"{sid}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))["gev"], f"F2.2 ({path.name})"
    maxima, _ = extremes.annual_maxima(df, meta.get("hydro_year_start_month", 4))
    series = pd.Series(maxima["q_m3s"].to_numpy(), index=maxima["date"])
    return extremes.fit_gev(series, n_samples=10), "reajustada aquí (sin JSON de F2.2)"


# --- sensitivity and chance baseline ---------------------------------------------------------------


def _random_dates(
    months: np.ndarray, years: tuple[int, int], rng: np.random.Generator, n_perm: int
) -> np.ndarray:
    """``n_perm x n_floods`` random days: same calendar month, random year of the catalog."""
    shape = (n_perm, len(months))
    year = rng.integers(years[0], years[1] + 1, size=shape)
    first = ((year - 1970) * 12 + (months[None, :] - 1)).astype("datetime64[M]")
    length = (
        (first + np.timedelta64(1, "M")).astype("datetime64[D]") - first.astype("datetime64[D]")
    ).astype(int)
    day = (rng.random(shape) * length).astype(int)
    return first.astype("datetime64[D]") + day.astype("timedelta64[D]")


def sensitivity(
    peaks: Sequence[pd.Timestamp],
    events: pd.DataFrame,
    period: tuple[pd.Timestamp, pd.Timestamp],
    ws: Sequence[int] = W_RANGE,
    n_perm: int = N_PERM,
    seed: int = SEED,
) -> list[dict]:
    """Share of floods with an AR for each window ``w`` against the share expected by chance."""
    start, end = period[0].normalize(), period[1].normalize()
    active = active_days(events, period)
    csum = np.concatenate([[0], np.cumsum(active)])
    peaks = [pd.Timestamp(p).normalize() for p in peaks]
    wmax = max(ws)
    idx = np.array([(p - start).days for p in peaks])
    n_days = (end - start).days + 1
    rows = [{"w": w, "n": len(peaks)} for w in ws]
    if not peaks:
        for r in rows:
            r.update(n_ar=0, share=None, chance=None, p=None)
        return rows

    def hit(day_idx: np.ndarray, w: int) -> np.ndarray:
        return csum[day_idx + 1] - csum[np.maximum(day_idx - w, 0)] > 0

    rng = np.random.default_rng(seed)
    months = np.array([p.month for p in peaks])
    start64 = np.datetime64(start.date())
    draws = _random_dates(months, (start.year, end.year), rng, n_perm)
    d_idx = (draws - start64).astype(int)
    bad = (d_idx - wmax < 0) | (d_idx > n_days - 1)  # window must lie inside the catalog period
    while bad.any():  # rejection sampling: redraw only the invalid cells
        again = _random_dates(months, (start.year, end.year), rng, n_perm)
        again_idx = (again - start64).astype(int)
        d_idx = np.where(bad, again_idx, d_idx)
        bad = (d_idx - wmax < 0) | (d_idx > n_days - 1)
    for r in rows:
        w = r["w"]
        n_ar = int(hit(idx, w).sum())
        sim = hit(d_idx, w).mean(axis=1)  # share of floods with an AR in each draw
        obs = n_ar / len(peaks)
        r.update(
            n_ar=n_ar,
            share=obs,
            chance=float(sim.mean()),
            p=float((np.sum(sim >= obs - 1e-12) + 1) / (n_perm + 1)),
        )
    return rows


# --- snow and labels -------------------------------------------------------------------------------


def snow_metrics(cells: pd.DataFrame | None, sid: int, peak: pd.Timestamp, w: int) -> dict:
    """Snow-covered fraction and area-mean SWE (mm w.e.) at the window start and at the peak."""
    missing = {"status": "sin dato"}
    if cells is None or cells.empty:
        return missing
    peak = pd.Timestamp(peak).normalize()
    sub = cells[(cells["station_id"] == sid) & (cells["peak"] == peak)]
    at = lambda d: sub.loc[sub["date"] == d, "swe_m"].dropna()
    start, end = at(peak - pd.Timedelta(days=w)), at(peak)
    if start.empty or end.empty:
        return missing
    return {
        "status": "ok",
        "cover_frac": float((start >= SWE_COVER_MIN_M - 1e-9).mean()),
        "swe_start_mm": float(start.mean() * 1000.0),
        "swe_peak_mm": float(end.mean() * 1000.0),
        "n_cells": len(start),
    }


def classify(ar: bool, snow_m: dict) -> tuple[str, bool]:
    """``(label, snow_missing)`` from the AR part and the snow part."""
    if snow_m.get("status") != "ok":
        return (L_AR if ar else L_NONE), True
    melting = (
        snow_m["cover_frac"] >= COVER_FRAC_MIN and snow_m["swe_peak_mm"] < snow_m["swe_start_mm"]
    )
    if ar:
        return (L_AR_SNOW if melting else L_AR), False
    return (L_SNOW if melting else L_NONE), False


# --- station -----------------------------------------------------------------------------------------


def station_result(
    df: pd.DataFrame,
    meta: dict,
    events: pd.DataFrame,
    period: tuple[pd.Timestamp, pd.Timestamp],
    cells: pd.DataFrame | None,
    gev_dir: Path,
    n_perm: int = N_PERM,
    seed: int = SEED,
) -> dict:
    sid = int(meta["id"])
    start_month = meta.get("hydro_year_start_month", 4)
    floods = select_floods(df, start_month, period)
    maxima, _ = extremes.annual_maxima(df, start_month)
    fit, fit_src = _gev_fit(sid, df, meta, gev_dir)
    rows = []
    for f in floods.itertuples(index=False):
        peak = pd.Timestamp(f.date).normalize()
        match = matching_events(events, peak, W_PRIMARY)
        sn = snow_metrics(cells, sid, peak, W_PRIMARY)
        label, missing = classify(len(match) > 0, sn)
        rows.append(
            {
                "hydro_year": int(f.hydro_year),
                "date": f"{peak:%Y-%m-%d}",
                "q_m3s": float(f.q_m3s),
                "gev_T": extremes.gev_return_period(float(f.q_m3s), fit),
                "ar": len(match) > 0,
                "events": [str(e) for e in match["event_id"]],
                "deg0l_mean_m": float(match["deg0l_mean"].mean()) if len(match) else None,
                "deg0l_max_m": float(match["deg0l_max"].max()) if len(match) else None,
                "snow": sn,
                "label": label,
                "snow_missing": missing,
            }
        )
    rows.sort(key=lambda r: -r["q_m3s"])
    counts = {lab: sum(r["label"] == lab for r in rows) for lab in LABELS}
    sens = sensitivity(
        [pd.Timestamp(r["date"]) for r in rows], events, period, n_perm=n_perm, seed=seed + sid
    )
    return {
        "station_id": sid,
        "name": meta.get("name"),
        "river": meta.get("river"),
        "box": dict(
            zip(
                ("lat_south", "lat_north", "lon_west", "lon_east"),
                snow.UPSTREAM_BOXES.get(sid, ()),
                strict=False,
            )
        ),
        "box_note": snow.BOX_NOTE,
        "n_years_complete": len(maxima),
        "n_floods": len(rows),
        "short_record": len(maxima) < SHORT_RECORD_YEARS,
        "gev_source": fit_src,
        "gev_shape_xi": fit["shape_xi"] if "shape_xi" in fit else -fit["shape_c_scipy"],
        "floods": rows,
        "label_counts": counts,
        "n_snow_missing": sum(r["snow_missing"] for r in rows),
        "sensitivity": sens,
    }


# --- report ------------------------------------------------------------------------------------------


def _n(x, nd: int = 0) -> str:
    return extremes._n(x, nd)


def _pc(x) -> str:
    return "n/d" if x is None else f"{100 * x:.0f} %".replace(".", ",")


def _p(x) -> str:
    return "n/d" if x is None else (f"{x:.3f}".replace(".", ",") if x >= 0.001 else "< 0,001")


def build_report(results: list[dict], meta: dict) -> str:
    L = [
        "# F2.3 — Crecidas mayores y su causa probable",
        "",
        (
            "Retrospectivo: etiqueta cada máximo anual según el catálogo de ríos atmosféricos (F1.3) y la nieve; "
            "no es un pronóstico ni un sistema de alerta. Una etiqueta es una coincidencia, no una prueba de causa."
        ),
        "",
        "## Fuente y método",
        "",
        f"- Caudal: {flow.SOURCE} ({flow.SNIH_URL}); caudal medio diario (m³/s). Citar al SIPH/SNIH. Períodos de retorno de la GEV de F2.2.",
        f"- Catálogo de ríos atmosféricos: {meta['catalog_source']}, período {meta['catalog_period']}, {meta['n_events']} eventos (F1.3).",
        f"- Nieve: {meta['snow_source_note']}. Variable `snow_depth` (m de agua equivalente), un valor por día a las 00 UTC; período leído: {meta['snow_period']}.",
        (
            "- Crecidas: máximo anual de los años hidrológicos completos (como F2.2: inicio en abril, al menos "
            f"{flow.MIN_VALID_DAYS} días válidos) cuyo pico cae dentro del período del catálogo; además se exige "
            "que pico − 7 días no quede antes del inicio del catálogo, para que la ventana más ancha esté cubierta."
        ),
        (
            f"- Río atmosférico en la ventana: al menos un evento activo en algún día de [pico − w, pico]; w primario = {W_PRIMARY} días. "
            "Un evento está activo desde el día de su inicio hasta el día de su último paso (el fin del catálogo es exclusivo). "
            "Los días son calendario tal como están guardados (el caudal es hora local UTC−3, el catálogo UTC)."
        ),
        (
            f"- Línea base por azar: para cada crecida se sortea una fecha del mismo mes calendario de un año al azar del período del catálogo y se aplica la misma regla de ventana; "
            f"{meta['n_perm']} sorteos, semilla {meta['seed']} (más el número de la estación). Valor p = proporción de sorteos con una proporción de crecidas con río atmosférico mayor o igual que la observada "
            "(con corrección +1). Los valores p son por estación y por w, sin ajuste por comparaciones múltiples."
        ),
        (
            "- Nieve sobre la cuenca aproximada: fracción cubierta = proporción de celdas con al menos 10 mm de agua equivalente al inicio de la ventana (pico − w); "
            "EAN medio (mm) al inicio de la ventana y en el pico."
        ),
        (
            f"- Etiquetas (w = {W_PRIMARY}): «{L_AR_SNOW}» = río atmosférico + fracción cubierta ≥ 0,2 al inicio + EAN medio menor en el pico que al inicio; "
            f"«{L_AR}» = río atmosférico en el resto; «{L_SNOW}» = sin río atmosférico pero con las mismas dos condiciones de nieve; «{L_NONE}» = el resto. "
            "La isoterma de 0 °C del evento (media y máximo del catálogo, en m) se informa al lado, sin umbral."
        ),
        "- Sin dato de nieve para una crecida: la parte de nieve queda «sin dato» y la etiqueta usa solo la parte del río atmosférico (marcada con †).",
        "",
        "## Supuestos y salvedades (sin verificar)",
        "",
        f"- Cuencas: {snow.BOX_NOTE}. Rectángulos escritos de memoria (lat S, lat N, lon O, lon E): "
        + "; ".join(
            f"{sid}: {b[0]}, {b[1]}, {b[2]}, {b[3]}" for sid, b in snow.UPSTREAM_BOXES.items()
        )
        + ".",
        f"- Nieve: {meta['snow_source_note']}. El agua equivalente de ERA5 no se contrastó con observaciones de nieve en estas cuencas (sin verificar).",
        "- Los umbrales (10 mm, fracción 0,2, EAN menor en el pico) se fijaron antes de ver los resultados; no están calibrados ni validados.",
        "- «EAN medio menor en el pico» no distingue deshielo de sublimación o de redistribución por viento; es una condición necesaria, no una medición del deshielo.",
        "- El caudal diario es un promedio de 24 h; el pico real puede haber ocurrido otro día y el catálogo es de pasos de 6 h.",
        "- El catálogo detecta ríos atmosféricos con un polígono sobre la cordillera (F1.3); la relación entre ese polígono y cada cuenca es sin verificar.",
        "- La proporción por azar depende de la frecuencia de eventos en el mes de la crecida; los años no son independientes entre sí (persistencia interanual).",
        "",
    ]
    for r in results:
        L += [
            f"## {r['station_id']} {r['name']} ({r['river']})",
            "",
            f"- Cuenca: {r['box_note']} ({r['box']['lat_south']} a {r['box']['lat_north']} lat, {r['box']['lon_west']} a {r['box']['lon_east']} lon).",
            f"- Crecidas dentro del catálogo: {r['n_floods']} (años completos del registro: {r['n_years_complete']}). Período de retorno: GEV {r['gev_source']}.",
        ]
        if r["short_record"]:
            L.append(f"- Atención: {SHORT_NOTE}.")
        if r["n_snow_missing"]:
            L.append(
                f"- Sin dato de nieve en {r['n_snow_missing']} de {r['n_floods']} crecidas (†)."
            )
        L += [
            "",
            "### Sensibilidad a la ventana w y línea base por azar",
            "",
            "| w (días) | Con río atmosférico | Proporción | Esperada por azar | p |",
            "|---|---|---|---|---|",
        ]
        for s in r["sensitivity"]:
            L.append(
                f"| {s['w']} | {s['n_ar']} de {s['n']} | {_pc(s['share'])} | {_pc(s['chance'])} | {_p(s['p'])} |"
            )
        L += ["", f"### Etiquetas (w = {W_PRIMARY})", "", "| Etiqueta | Crecidas |", "|---|---|"]
        for lab in LABELS:
            L.append(f"| {lab} | {r['label_counts'][lab]} |")
        L += [
            "",
            "### Crecidas (de mayor a menor caudal)",
            "",
            "| Fecha | Q (m³/s) | T GEV (años) | Eventos | 0 °C media / máx. (m) | Fracción con nieve | EAN inicio → pico (mm) | Etiqueta |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for f in r["floods"]:
            sn = f["snow"]
            if sn["status"] == "ok":
                cover = _n(sn["cover_frac"], 2).replace(".", ",")
                swe = f"{_n(sn['swe_start_mm'], 1)} → {_n(sn['swe_peak_mm'], 1)}"
            else:
                cover = swe = "sin dato"
            iso = f"{_n(f['deg0l_mean_m'])} / {_n(f['deg0l_max_m'])}" if f["ar"] else "—"
            L.append(
                f"| {f['date']} | {_n(f['q_m3s'])} | {extremes._t(f['gev_T'])} | {', '.join(f['events']) or '—'} | {iso} | {cover} | {swe} | {f['label']}{' †' if f['snow_missing'] else ''} |"
            )
        L.append("")
    return "\n".join(L)


# --- entry point ---------------------------------------------------------------------------------------


def write_outputs(results: list[dict], meta: dict, out: Path | str, report: Path | str) -> None:
    out, report = Path(out), Path(report)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "stations": results}
    out.write_text(
        json.dumps(ar_enso._clean(payload), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(build_report(results, meta), encoding="utf-8")


def run(
    flow_dir: Path | str = flow.OUT_DIR,
    gev_dir: Path | str = extremes.GEV_DIR,
    catalog: Path | str = DEFAULT_CATALOG,
    snow_path: Path | str = snow.DEFAULT_OUT,
    out: Path | str = OUT_PATH,
    report: Path | str = REPORT_PATH,
    stations: Sequence[int] | None = None,
    n_perm: int = N_PERM,
    seed: int = SEED,
) -> dict:
    """Label the floods and write the JSON and the Markdown report."""
    flow_dir, gev_dir, snow_path = Path(flow_dir), Path(gev_dir), Path(snow_path)
    events, period = load_catalog(catalog)
    cells = snow.read_snow(snow_path) if snow_path.is_file() else None
    meta_all = _station_meta(flow_dir)
    results = []
    for sid in stations or DEFAULT_STATIONS:
        df = flow.read_flow(flow_dir / f"{sid}.parquet")
        results.append(
            station_result(
                df, meta_all[sid], events, period, cells, gev_dir, n_perm=n_perm, seed=seed
            )
        )
    snow_meta = snow.read_metadata(snow_path) if cells is not None else {}
    meta = {
        "catalog_source": ar_catalog.read_metadata(catalog).get("source", ar_catalog.SOURCE),
        "catalog_period": f"{period[0]:%Y-%m-%d}/{period[1]:%Y-%m-%d}",
        "n_events": len(events),
        "w_primary": W_PRIMARY,
        "w_range": list(W_RANGE),
        "n_perm": n_perm,
        "seed": seed,
        "snow_source": f"{era5.SOURCE}; {snow_meta.get('variable', 'snow_depth')}"
        if cells is not None
        else None,
        "snow_source_note": SNOW_SOURCE_NOTE,
        "snow_period": snow_meta.get("period", "sin dato (no hay archivo de nieve)"),
        "snow_license": era5.LICENSE,
        "snow_grid": "0.25 degrees",
        "box_note": snow.BOX_NOTE,
        "rule_swe_cover_min_mm": SWE_COVER_MIN_M * 1000,
        "rule_cover_frac_min": COVER_FRAC_MIN,
        "short_record_years": SHORT_RECORD_YEARS,
        "not_an_alert": "retrospectivo; no es un sistema de alerta",
    }
    write_outputs(results, meta, out, report)
    return {"meta": meta, "stations": results}

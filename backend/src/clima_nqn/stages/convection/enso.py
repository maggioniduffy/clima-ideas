"""Extreme convective days by ENSO phase, spring (SON) and summer (DJF), Neuquén (F3.6, plan/03).

Rule fixed before running (see ``reports/03/F3.6.md``):

- Seasons: spring = SON, summer = DJF labelled by the December year (DJF 2000 = Dec 2000 + Jan/Feb 2001).
  Study seasons: SON 2000-2024 and DJF 2000/01-2024/25 (25 each); a season with any missing local day is dropped.
- Day = local day (UTC-3, Argentina, no DST in the period). Daily metric: max 1 h intensity (max rolling mean of
  two consecutive half-hours, windows inside the local day) in mm/h; daily total in mm.
- Extreme convective day: max 1 h >= quantile q of that metric over the SON+DJF days of the study seasons with
  daily total >= 1 mm. Main: q = 0.99 at the Neuquén Aero cell. Sensitivities: q = 0.95 and a regional version
  (any cell of the Confluencia sub-box above that cell's own p99).
- Per season-year: count of extreme days; phase from the mean ONI of the season (``ar.enso.seasonal_oni``).
- Tests per season: permutation (10 000, seed 0, two-sided) of the difference in mean count Niño-Niña and
  Niño-Neutral; Benjamini-Hochberg over the four tests of each variant. Baseline: pooled climatological frequency.
- Signal only if BH p < 0.05 in all three variants with the same sign and every group has n >= 5.

Run: ``uv run python -m clima_nqn.stages.convection.enso``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from clima_nqn.io import enso as io_enso
from clima_nqn.stages.ar import enso as ar_enso

SEASONS = ("SON", "DJF")
SEASON_NOUN = {"SON": "primaveras", "DJF": "veranos"}
PHASE_NAME = {"nino": "Niño", "neutral": "Neutro", "nina": "Niña"}
YEAR_MIN, YEAR_MAX = 2000, 2024
UTC_OFFSET_H = -3
STEPS_PER_DAY = 48
WET_DAY_MM = 1.0
ALPHA = 0.05
MIN_N = 5
N_PERM = 10000
SEED = 0
NEUQUEN_AERO = (-38.949, -68.156)
CONFLUENCIA = {"lon": (-68.4, -67.8), "lat": (-39.2, -38.7)}
TESTS = (("nino", "nina"), ("nino", "neutral"))
VARIANTS = {
    "main": {"label": "p99, Neuquén Aero", "quantile": 0.99, "regional": False},
    "p95": {"label": "p95, Neuquén Aero", "quantile": 0.95, "regional": False},
    "regional": {
        "label": "p99 por celda, Confluencia (≥1 celda)",
        "quantile": 0.99,
        "regional": True,
    },
    "seas_p99": {
        "label": "p99 por estación (SON y DJF por separado)",
        "quantile": 0.99,
        "per_season": True,
    },
    "seas_p95": {
        "label": "p95 por estación (SON y DJF por separado)",
        "quantile": 0.95,
        "per_season": True,
    },
}
SPOT_CHECKS = (("DJF", 2015, "nino"), ("DJF", 2010, "nina"))  # DJF 2015/16 Niño, DJF 2010/11 Niña
REPO_ROOT = Path(__file__).resolve().parents[5]
ZARR_PATH = REPO_ROOT / "backend/data/raw/imerg/neuquen.zarr"
REPORT_PATH = REPO_ROOT / "reports/03/F3.6.md"
SOURCE = (
    "NASA GES DISC IMERG V07 Final semihorario (GPM_3IMERGHH), recorte Neuquén; "
    f"ONI de {io_enso.SOURCE}"
)


# --- daily aggregation -----------------------------------------------------------------------


def local_daily(
    precip_mmh: np.ndarray, times: pd.DatetimeIndex
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    """Aggregate half-hourly rain rate (mm/h, shape (time, cells), naive UTC step start) to local days.

    Returns (days, total_mm, max_1h_mmh); the last two have shape (days, cells). Only complete days (48
    consecutive steps, no NaN) are kept. A 1 h window is two consecutive half-hours inside the same local day.
    """
    x = np.asarray(precip_mmh, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    t = pd.DatetimeIndex(times)
    order = np.argsort(t.values)
    t, x = t[order], x[order]
    local = t + pd.Timedelta(hours=UTC_OFFSET_H)
    day = local.floor("D")
    frame = pd.DataFrame({"day": day, "bad": np.isnan(x).any(axis=1)})
    grp = frame.groupby("day")
    complete = (grp.size() == STEPS_PER_DAY) & (grp["bad"].sum() == 0)
    keep_days = complete.index[complete.to_numpy()]
    mask = day.isin(keep_days)
    xs = x[mask]
    n_days = len(keep_days)
    cube = xs.reshape(n_days, STEPS_PER_DAY, x.shape[1])
    total = cube.sum(axis=1) * 0.5
    max1h = ((cube[:, :-1] + cube[:, 1:]) / 2).max(axis=1)
    return pd.DatetimeIndex(keep_days), total, max1h


def season_of(days: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """(season, season year) per day for SON/DJF; DJF is labelled by the December year.

    Dec year Y -> DJF Y; Jan/Feb year Y -> DJF Y-1. Other months get season ``""``.
    """
    d = pd.DatetimeIndex(days)
    m = d.month.to_numpy()
    y = d.year.to_numpy()
    season = np.where(np.isin(m, (9, 10, 11)), "SON", np.where(np.isin(m, (12, 1, 2)), "DJF", ""))
    year = np.where(np.isin(m, (1, 2)), y - 1, y)
    return season.astype(object), year


def expected_days(season: str, year: int) -> int:
    start = pd.Timestamp(year, 9 if season == "SON" else 12, 1)
    return int((start + pd.DateOffset(months=3) - start).days)


def oni_year(season: str, year: int) -> int:
    """Year argument of ``ar.enso.seasonal_oni`` (that module labels DJF by the January year)."""
    return year + 1 if season == "DJF" else year


# --- extreme days ----------------------------------------------------------------------------


def wet_quantile(max1h: np.ndarray, total: np.ndarray, q: float) -> tuple[float, int]:
    """Quantile q of ``max1h`` over days with total >= 1 mm, and the number of such days."""
    wet = total >= WET_DAY_MM
    return float(np.quantile(max1h[wet], q)), int(wet.sum())


def season_counts(
    days: pd.DatetimeIndex,
    extreme: np.ndarray,
    enso: pd.DataFrame,
    year_min: int = YEAR_MIN,
    year_max: int = YEAR_MAX,
) -> tuple[pd.DataFrame, list[str]]:
    """One row per complete study season: extreme-day count, mean ONI and phase; plus dropped seasons."""
    season, year = season_of(days)
    frame = pd.DataFrame({"season": season, "year": year, "extreme": extreme.astype(bool)})
    frame = frame[frame["season"] != ""]
    rows, dropped = [], []
    for s in SEASONS:
        for y in range(year_min, year_max + 1):
            g = frame[(frame["season"] == s) & (frame["year"] == y)]
            if len(g) != expected_days(s, y):
                dropped.append(f"{s} {y}")
                continue
            oni, phase = ar_enso.seasonal_oni(enso, s, oni_year(s, y))
            if phase is None:
                dropped.append(f"{s} {y} (sin ONI)")
                continue
            n = int(g["extreme"].sum())
            rows.append(
                {"season": s, "year": y, "oni_mean": oni, "phase": phase, "n_extreme_days": n}
            )
    return pd.DataFrame(
        rows, columns=["season", "year", "oni_mean", "phase", "n_extreme_days"]
    ), dropped


def phase_spotcheck(enso: pd.DataFrame) -> list[dict]:
    """Phase assigned by the code to known DJF seasons (2015/16 Niño, 2010/11 Niña)."""
    out = []
    for s, y, expected in SPOT_CHECKS:
        oni, phase = ar_enso.seasonal_oni(enso, s, oni_year(s, y))
        out.append(
            {
                "season": f"{s} {label_year(s, y)}",
                "oni_mean": oni,
                "phase": phase,
                "expected": expected,
            }
        )
    return out


def label_year(season: str, year: int) -> str:
    return f"{year}/{str(year + 1)[-2:]}" if season == "DJF" else str(year)


# --- tests -----------------------------------------------------------------------------------


def compare_phases(table: pd.DataFrame, n_perm: int = N_PERM, seed: int = SEED) -> list[dict]:
    """Per season: group stats, pooled baseline, permutation tests of Niño vs Niña / Neutro, BH over all."""
    out = []
    for s in SEASONS:
        sub = table[table["season"] == s]
        v = sub["n_extreme_days"].to_numpy(float)
        lab = sub["phase"].to_numpy(object)
        groups = {}
        for p in ("nino", "neutral", "nina"):
            m = lab == p
            groups[p] = {
                "n": int(m.sum()),
                "total_days": int(v[m].sum()),
                "mean_days": float(v[m].mean()) if m.any() else math.nan,
                "seasons_with_extreme": int((v[m] > 0).sum()),
            }
        base = {
            "n": len(v),
            "mean_days": float(v.mean()) if len(v) else math.nan,
            "seasons_with_extreme": int((v > 0).sum()),
        }
        for a, b in TESTS:
            t = ar_enso.permutation_test(v, lab, a, b, n_perm, seed)
            out.append(
                {
                    "season": s,
                    "pair": f"{a}-{b}",
                    "a": a,
                    "b": b,
                    "diff": t["diff"],
                    "p": t["p"],
                    "n_a": t["n_a"],
                    "n_b": t["n_b"],
                    "small_n": min(t["n_a"], t["n_b"]) < MIN_N,
                    "groups": groups,
                    "baseline": base,
                }
            )
    for r, adj in zip(out, ar_enso.bh_adjust([r["p"] for r in out]), strict=True):
        r["p_bh"] = adj
    return out


def build_variant(
    days: pd.DatetimeIndex,
    total: np.ndarray,
    max1h: np.ndarray,
    aero: int,
    enso: pd.DataFrame,
    spec: dict,
    n_perm: int = N_PERM,
    seed: int = SEED,
) -> dict:
    """One variant: thresholds, extreme-day flags, season table and tests."""
    season, year = season_of(days)
    study = (season != "") & (year >= YEAR_MIN) & (year <= YEAR_MAX)
    q = spec["quantile"]
    if spec.get("per_season"):
        threshold, extreme = {}, np.zeros(len(days), bool)
        for sname in SEASONS:
            k = study & (season == sname)
            thr_s, _ = wet_quantile(max1h[k, aero], total[k, aero], q)
            threshold[sname] = thr_s
            extreme |= k & (max1h[:, aero] >= thr_s)
        n_wet = int((total[study, aero] >= WET_DAY_MM).sum())
    elif spec.get("regional"):
        thr = np.array(
            [wet_quantile(max1h[study, c], total[study, c], q)[0] for c in range(max1h.shape[1])]
        )
        extreme = (max1h >= thr[None, :]).any(axis=1) & study
        threshold = {
            "per_cell_min": float(thr.min()),
            "per_cell_max": float(thr.max()),
            "aero": float(thr[aero]),
        }
        n_wet = int((total[study, aero] >= WET_DAY_MM).sum())
    else:
        thr_v, n_wet = wet_quantile(max1h[study, aero], total[study, aero], q)
        extreme = (max1h[:, aero] >= thr_v) & study
        threshold = {"aero": thr_v}
    table, dropped = season_counts(days[study], extreme[study], enso)
    return {
        "label": spec["label"],
        "quantile": q,
        "regional": bool(spec.get("regional")),
        "per_season": bool(spec.get("per_season")),
        "threshold_mmh": threshold,
        "n_wet_days_pool": n_wet,
        "n_extreme_days_pool": int(extreme.sum()),
        "n_extreme_days_by_season": {
            sname: int(extreme[season == sname].sum()) for sname in SEASONS
        },
        "dropped_seasons": dropped,
        "rows": compare_phases(table, n_perm, seed),
        "season_years": table.to_dict(orient="records"),
    }


def verdict_flags(variants: dict) -> dict[str, dict]:
    """Per season and pair: signal only if BH p < alpha in every variant (main and all sensitivities),
    same sign, all n >= MIN_N. A hit in only some variants is a ``hint`` ("indicio, sin verificar")."""
    flags = {}
    for s in SEASONS:
        for a, b in TESTS:
            key = f"{s}:{a}-{b}"
            rows = [
                next(r for r in v["rows"] if r["season"] == s and r["pair"] == f"{a}-{b}")
                for v in variants.values()
            ]
            sig = [
                r["p_bh"] is not None and not math.isnan(r["p_bh"]) and r["p_bh"] < ALPHA
                for r in rows
            ]
            signs = {int(np.sign(r["diff"])) for r in rows if not math.isnan(r["diff"])}
            small = any(r["small_n"] for r in rows)
            hint = any(sig) and not (all(sig) and len(signs) == 1 and not small)
            flags[key] = {
                "hint": hint,
                "main_sig": sig[0],
                "bh_below_alpha": sig,
                "same_sign": len(signs) == 1,
                "small_n": small,
                "signal": all(sig) and len(signs) == 1 and not small,
            }
    return flags


# --- run -------------------------------------------------------------------------------------


def load_box(zarr_path: Path = ZARR_PATH):
    """Load the Confluencia sub-box; returns (times, precip (time, cells), lat, lon, aero index)."""
    import xarray as xr

    ds = xr.open_zarr(zarr_path, consolidated=False)
    lat = ds.lat.values
    lon = ds.lon.values
    li = np.where((lat >= CONFLUENCIA["lat"][0]) & (lat <= CONFLUENCIA["lat"][1]))[0]
    lj = np.where((lon >= CONFLUENCIA["lon"][0]) & (lon <= CONFLUENCIA["lon"][1]))[0]
    block = ds.precipitation.isel(lat=li, lon=lj).load().values  # (time, lat, lon)
    la, lo = np.meshgrid(lat[li], lon[lj], indexing="ij")
    cells = block.reshape(block.shape[0], -1)
    la, lo = la.ravel(), lo.ravel()
    # nearest cell to Neuquén Aero (must lie inside the box)
    aero = int(np.argmin((la - NEUQUEN_AERO[0]) ** 2 + (lo - NEUQUEN_AERO[1]) ** 2))
    return pd.DatetimeIndex(ds.time.values), cells, la, lo, aero


def build_payload(
    times, cells, aero: int, enso: pd.DataFrame, n_perm: int = N_PERM, seed: int = SEED
) -> dict:
    days, total, max1h = local_daily(cells, times)
    variants = {
        name: build_variant(days, total, max1h, aero, enso, spec, n_perm, seed)
        for name, spec in VARIANTS.items()
    }
    return {
        "meta": {
            "source": SOURCE,
            "period_data": f"{pd.Timestamp(times.min()):%Y-%m-%d}/{pd.Timestamp(times.max()):%Y-%m-%d}",
            "seasons": "SON 2000-2024; DJF 2000/01-2024/25",
            "n_cells_regional": int(cells.shape[1]),
            "n_perm": n_perm,
            "seed": seed,
            "alpha": ALPHA,
            "min_n": MIN_N,
        },
        "spot_check": phase_spotcheck(enso),
        "variants": variants,
        "flags": verdict_flags(variants),
    }


def _c(x, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/d"
    return f"{x:.{nd}f}".replace(".", ",")


def _row(v: dict, s: str, pair: str) -> dict:
    return next(r for r in v["rows"] if r["season"] == s and r["pair"] == pair)


def _kn(g: dict) -> str:
    return f"{g['seasons_with_extreme']} de {g['n']}"


def verdict_lines(payload: dict) -> list[str]:
    main, flags = payload["variants"]["main"], payload["flags"]
    lines = []
    any_signal = any(f["signal"] for f in flags.values())
    lines.append(
        "No hay señal ENSO sostenida en la frecuencia de días convectivos extremos."
        if not any_signal
        else "Hay al menos una diferencia que pasa todas las variantes (ver abajo); leerla como exploratoria."
    )
    for s in SEASONS:
        r = _row(main, s, "nino-nina")
        g = r["groups"]
        rs = _row(payload["variants"]["seas_p99"], s, "nino-nina")["groups"]
        extra = (
            f" Con p99 por estación: {_kn(rs['nino'])} Niño, {_kn(rs['neutral'])} neutras, "
            f"{_kn(rs['nina'])} Niña."
        )
        noun = SEASON_NOUN[s]
        lines.append(
            f"- {s}: {_kn(g['nino'])} {noun} Niño, {_kn(g['neutral'])} {noun} neutras y {_kn(g['nina'])} {noun} Niña "
            f"tuvieron ≥1 día extremo; media {_c(g['nino']['mean_days'])} / {_c(g['neutral']['mean_days'])} / "
            f"{_c(g['nina']['mean_days'])} días por estación (Niño / Neutro / Niña); climatología "
            f"{_c(r['baseline']['mean_days'])}.{extra}"
        )
        for pair, name in (("nino-nina", "Niño − Niña"), ("nino-neutral", "Niño − Neutro")):
            rr = [_row(v, s, pair) for v in payload["variants"].values()]
            f = flags[f"{s}:{pair}"]
            tag = (
                "señal"
                if f["signal"]
                else "indicio, sin verificar (no pasa todas las variantes)"
                if f["hint"]
                else "sin señal sostenida"
            )
            if f["small_n"]:
                tag += "; n < 5 en algún grupo: sin verificar"
            lines.append(
                f"  - {name}: dif. {_c(rr[0]['diff'])} días/estación, p {_c(rr[0]['p'], 3)}, p BH "
                f"{_c(rr[0]['p_bh'], 3)} (p95: {_c(rr[1]['p_bh'], 3)}; regional: {_c(rr[2]['p_bh'], 3)}; "
                f"p99 por estación: {_c(rr[3]['p_bh'], 3)}; p95 por estación: {_c(rr[4]['p_bh'], 3)}): {tag}."
            )
    return lines


def write_report(payload: dict, path: Path | str = REPORT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta, variants = payload["meta"], payload["variants"]
    m = variants["main"]
    lines = [
        "# F3.6 — Días convectivos extremos por fase ENSO (Neuquén, primavera y verano)",
        "",
        "## Veredicto",
        "",
        *verdict_lines(payload),
        "",
        (
            f"Potencia: el p99 principal deja solo {m['n_extreme_days_pool']} días extremos en 50 estaciones "
            f"(p95: {variants['p95']['n_extreme_days_pool']}; regional: {variants['regional']['n_extreme_days_pool']}), "
            "así que ninguna prueba puede detectar un efecto moderado; ausencia de señal no prueba ausencia de efecto. "
            f"Con umbral pooled SON+DJF, DJF queda con {m['n_extreme_days_by_season']['DJF']} días extremos "
            "(comparación vacía); por eso se añadieron umbrales por estación como sensibilidad. "
            "Regla: señal solo si pasa BH < 0,05 en la variante principal y en todas las sensibilidades; si solo "
            "aparece en alguna, es «indicio, sin verificar». "
            "Grupos con menos de 5 estaciones quedan «sin verificar». ENSO se informa como contexto, no como predictor."
        ),
        "",
        "## Fuente y alcance",
        "",
        f"- Fuente: {meta['source']}. Datos {meta['period_data']}; estaciones {meta['seasons']}.",
        (
            "- Celda de Neuquén Aero (más cercana a −38,949; −68,156). Región: sub-caja Confluencia "
            f"(−68,4…−67,8 lon; −39,2…−38,7 lat), {meta['n_cells_regional']} celdas."
        ),
        (
            "- IMERG subestima la lluvia puntual intensa (F3.4: razón IMERG/estación 0,67 en 16 extremos, IC 90 % por "
            "evento muy ancho). Esto mueve los umbrales y los conteos absolutos; la comparación entre fases usa el "
            "mismo umbral y el mismo sensor en todas las estaciones, así que el sesgo sólo la distorsiona si depende "
            "de la fase ENSO (no verificado)."
        ),
        "",
        "## Regla fijada antes de correr",
        "",
        (
            "- Estaciones: primavera = SON; verano = DJF con el año de diciembre (DJF 2000 = dic 2000 + ene/feb 2001). "
            "Se descartan las estaciones con algún día local faltante."
        ),
        (
            "- Día = día local (UTC−3, sin horario de verano). Métrica diaria: máxima intensidad a 1 h (máximo de la media "
            "móvil de 2 medias horas dentro del día, mm/h)."
        ),
        (
            "- Día extremo: máx. 1 h ≥ percentil q de esa métrica en todos los días SON+DJF de las estaciones del estudio con "
            "total diario ≥ 1 mm. Principal q = 0,99; sensibilidades q = 0,95 y regional (≥ 1 celda de Confluencia sobre su "
            "propio p99)."
        ),
        (
            f"- Fase: media del ONI ({io_enso.SOURCE}) de los tres meses; Niño ≥ +{io_enso.NINO_THRESHOLD}, "
            f"Niña ≤ {io_enso.NINA_THRESHOLD}, si no Neutro."
        ),
        (
            f"- Prueba: permutación de etiquetas ({meta['n_perm']}, semilla {meta['seed']}, bilateral) de la diferencia de "
            "medias de días extremos, Niño−Niña y Niño−Neutro por estación; BH sobre las 4 pruebas de cada variante. "
            "Línea de base: frecuencia climatológica con todas las estaciones juntas."
        ),
        (
            f"- Señal solo si p BH < {meta['alpha']} en las tres variantes con el mismo signo y todos los grupos con "
            f"n ≥ {meta['min_n']}."
        ),
        "",
        "## Comprobación de fases (DJF)",
        "",
        *[
            f"- {c['season']}: ONI medio {_c(c['oni_mean'])} → {PHASE_NAME[c['phase']]} "
            f"(esperado {PHASE_NAME[c['expected']]}): {'ok' if c['phase'] == c['expected'] else 'DISCREPA'}."
            for c in payload["spot_check"]
        ],
        "",
        "## Umbrales",
        "",
        "| Variante | Umbral Neuquén Aero (mm/h) | Días húmedos (≥ 1 mm) en el conjunto | Días extremos | Estaciones descartadas |",
        "|---|---|---|---|---|",
    ]
    for v in variants.values():
        t = v["threshold_mmh"]
        thr = _c(t["aero"], 2) if "aero" in t else f"SON {_c(t['SON'])} / DJF {_c(t['DJF'])}"
        if v["regional"]:
            thr += f" (celdas {_c(t['per_cell_min'])}–{_c(t['per_cell_max'])})"
        lines.append(
            f"| {v['label']} | {thr} | {v['n_wet_days_pool']} | {v['n_extreme_days_pool']} (SON {v['n_extreme_days_by_season']['SON']}, DJF {v['n_extreme_days_by_season']['DJF']}) | "
            f"{', '.join(v['dropped_seasons']) or 'ninguna'} |"
        )
    lines += [
        "",
        "## Estaciones por fase",
        "",
        "| Estación | Niño | Neutro | Niña | Total |",
        "|---|---|---|---|---|",
    ]
    for s in SEASONS:
        g = _row(m, s, "nino-nina")["groups"]
        lines.append(
            f"| {s} | {g['nino']['n']} | {g['neutral']['n']} | {g['nina']['n']} | {_row(m, s, 'nino-nina')['baseline']['n']} |"
        )
    for v in variants.values():
        lines += [
            "",
            f"## Tabla — {v['label']}",
            "",
            (
                "| Estación | Niño: estaciones con ≥1; días; media | Neutro | Niña | Climatología: con ≥1; media | "
                "Prueba | Dif. (días/estación) | p | p BH | n pequeño |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in SEASONS:
            for pair, name in (("nino-nina", "Niño − Niña"), ("nino-neutral", "Niño − Neutro")):
                r = _row(v, s, pair)
                g = r["groups"]
                cells = [
                    f"{_kn(g[p])}; {g[p]['total_days']} d; {_c(g[p]['mean_days'])}"
                    for p in ("nino", "neutral", "nina")
                ]
                b = r["baseline"]
                lines.append(
                    f"| {s} | {' | '.join(cells)} | {b['seasons_with_extreme']} de {b['n']}; {_c(b['mean_days'])} | "
                    f"{name} | {_c(r['diff'])} | {_c(r['p'], 4)} | {_c(r['p_bh'], 4)} | "
                    f"{'sí (sin verificar)' if r['small_n'] else 'no'} |"
                )
    lines += [
        "",
        "## Conteos por estación-año (principal)",
        "",
        "| Estación | Año | ONI | Fase | Días extremos |",
        "|---|---|---|---|---|",
    ]
    for r in m["season_years"]:
        lines.append(
            f"| {r['season']} | {label_year(r['season'], r['year'])} | {_c(r['oni_mean'])} | "
            f"{PHASE_NAME[r['phase']]} | {r['n_extreme_days']} |"
        )
    lines += [
        "",
        "## Sensibilidad",
        "",
        "| Estación | Prueba | p BH principal / p95 / regional / p99 por estación / p95 por estación | Señal |",
        "|---|---|---|---|",
    ]
    for s in SEASONS:
        for pair, name in (("nino-nina", "Niño − Niña"), ("nino-neutral", "Niño − Neutro")):
            rr = [_row(v, s, pair) for v in variants.values()]
            f = payload["flags"][f"{s}:{pair}"]
            lines.append(
                f"| {s} | {name} | {_c(rr[0]['p_bh'], 3)} / {_c(rr[1]['p_bh'], 3)} / {_c(rr[2]['p_bh'], 3)} / "
                f"{_c(rr[3]['p_bh'], 3)} / {_c(rr[4]['p_bh'], 3)} | "
                f"{'sí' if f['signal'] else 'indicio, sin verificar' if f['hint'] else 'no'} |"
            )
    lines += [
        "",
        "## Salvedades",
        "",
        "- Una celda IMERG de ~0,1° (≈ 10 km) no es un pluviómetro: la «intensidad a 1 h» es un promedio de área.",
        (
            "- Los conteos son por estación (25 por estación); con pocas estaciones por fase la potencia es baja: "
            "ausencia de señal no prueba ausencia de efecto."
        ),
        "- Comandos: `uv run python -m clima_nqn.stages.convection.enso`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(payload, indent=2, default=float, ensure_ascii=False), encoding="utf-8"
    )
    return path


def run(zarr_path: Path = ZARR_PATH, report_path: Path = REPORT_PATH) -> dict:
    enso = io_enso.read_enso()
    times, cells, _la, _lo, aero = load_box(zarr_path)
    payload = build_payload(times, cells, aero, enso)
    write_report(payload, report_path)
    return payload


if __name__ == "__main__":
    res = run()
    print("\n".join(verdict_lines(res)))
    for k, v in res["variants"].items():
        print(
            k,
            v["threshold_mmh"],
            v["n_wet_days_pool"],
            v["n_extreme_days_pool"],
            v["dropped_seasons"],
        )

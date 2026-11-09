"""Daily mean streamflow (QMD) from SNIH/SIPH for stations upstream of the dams."""

import json
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

SOURCE = "SNIH (SIPH) — Red Hidrológica Nacional"
SNIH_URL = "https://snih.hidricosargentina.gob.ar"
STATIONS_URL = f"{SNIH_URL}/Filtros.aspx/LeerEstaciones"
DATA_URL = f"{SNIH_URL}/MuestraDatos.aspx/LeerDatosHistoricos"
QMD_CODE = 101  # "Caudal Medio Diario" (m3/s)
LOCAL_UTC_OFFSET = timedelta(hours=-3)  # FechaHora is local midnight, UTC-3
WINDOW_YEARS = 10
MIN_VALID_DAYS = 330  # complete hydrological year (assumption S5, not from SNIH)
REGULATED_NOTE = "regulada aguas arriba (Alicurá, 1984); natural solo antes — sin verificar"

STATIONS = [
    {"id": 12004, "name": "Paso de Indios", "river": "Neuquén", "note": ""},
    {"id": 12013, "name": "Chos Malal", "river": "Neuquén", "note": ""},
    {"id": 12010, "name": "Bajada del Agrio", "river": "Agrio", "note": ""},
    {"id": 12012, "name": "Los Maitenes", "river": "Curí Leuvú", "note": ""},
    {"id": 11804, "name": "Paso Limay", "river": "Limay", "note": REGULATED_NOTE},
    {"id": 11803, "name": "Paso Flores", "river": "Limay", "note": REGULATED_NOTE},
]  # fmt: skip
_BY_ID = {s["id"]: s for s in STATIONS}

# backend/src/clima_nqn/io/flow.py -> repo root is parents[4]
_DATA = Path(__file__).resolve().parents[4] / "data"
RAW_DIR = _DATA / "raw" / "flow"
OUT_DIR = _DATA / "flow"
REPORT_PATH = Path(__file__).resolve().parents[4] / "reports" / "02" / "F2.1.md"


def parse_snih_date(value: str) -> date:
    """`/Date(ms)/` (epoch ms at local midnight UTC-3) -> local calendar date."""
    ms = int(value.removeprefix("/Date(").removesuffix(")/"))
    return (datetime(1970, 1, 1) + timedelta(milliseconds=ms) + LOCAL_UTC_OFFSET).date()


def area_or_none(area) -> float | None:
    """SNIH uses -999 (and sometimes 0) for unknown catchment area."""
    if area is None or area <= 0:
        return None
    return float(area)


def parse_stations(rows: list[dict]) -> dict[int, dict]:
    """Keep our stations; SNIH sends lat/lon as positive south/west, store them negated."""
    meta = {}
    for row in rows:
        if row["Codigo"] not in _BY_ID:
            continue
        base = _BY_ID[row["Codigo"]]
        meta[row["Codigo"]] = {
            "id": row["Codigo"],
            "name": base["name"],
            "river": base["river"],
            "lat": -float(row["Latitud"]),
            "lon": -float(row["Longitud"]),
            "area_km2": area_or_none(row.get("Area")),
            "hydro_year_start_month": int(row["MesHidrologico"]),
            "alta_year": parse_snih_date(row["Alta"]).year if row.get("Alta") else None,
            "note": base["note"],
        }
    return meta


def year_windows(start_year: int, end: date, years: int = WINDOW_YEARS) -> list[tuple[date, date]]:
    """Consecutive non-overlapping windows from Jan 1 of `start_year` to `end`."""
    windows = []
    start = date(start_year, 1, 1)
    while start <= end:
        stop = min(date(start.year + years, 1, 1) - timedelta(days=1), end)
        windows.append((start, stop))
        start = stop + timedelta(days=1)
    return windows


def fetch_stations(client: httpx.Client) -> list[dict]:
    response = client.post(
        STATIONS_URL, content=b"", headers={"Content-Type": "application/json; charset=utf-8"}
    )
    response.raise_for_status()
    return response.json()["d"]


def fetch_window(
    client: httpx.Client,
    station: int,
    start: date,
    stop: date,
    retries: int = 3,
    sleep: float = 1.0,
) -> list[dict]:
    """POST one window; retry on failure, then raise naming the window."""
    body = {
        "fechaDesde": start.isoformat(),
        "fechaHasta": stop.isoformat(),
        "estacion": station,
        "codigo": QMD_CODE,
        "validados": True,
    }
    label = f"station {station} window {start}..{stop}"
    last: Exception | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(sleep)
        try:
            response = client.post(DATA_URL, json=body)
            response.raise_for_status()
            d = response.json()["d"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            last = exc
            continue
        if d.get("RespuestaOK") != "True":
            last = RuntimeError(f"{label}: SNIH error: {d.get('MsgErr')}")
            continue
        return d["Mediciones"] or []
    raise RuntimeError(f"{label} failed after {retries} attempts: {last}") from last


def fetch_station_series(
    client: httpx.Client,
    station: int,
    alta_year: int,
    end: date,
    sleep: float = 1.0,
    progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """All QMD measurements from the station's Alta year to `end`, ~1 s between requests."""
    rows: list[dict] = []
    for i, (start, stop) in enumerate(year_windows(alta_year, end)):
        if i:
            time.sleep(sleep)
        got = fetch_window(client, station, start, stop, sleep=sleep)
        if progress:
            progress(f"{station} {start}..{stop}: {len(got)} rows")
        rows.extend(got)
    return rows


def fetch_flow(
    raw_dir: Path | str = RAW_DIR,
    stations: list[int] | None = None,
    today: date | None = None,
    sleep: float = 1.0,
    progress: Callable[[str], None] | None = None,
    timeout: float = 60.0,
) -> Path:
    """Fetch station metadata and daily series; write raw JSON under `raw_dir`."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    today = today or date.today()
    wanted = stations or [s["id"] for s in STATIONS]
    unknown = sorted(set(wanted) - set(_BY_ID))
    if unknown:
        raise ValueError(f"unknown stations: {unknown}")
    with httpx.Client(timeout=timeout) as client:
        raw_meta = [r for r in fetch_stations(client) if r["Codigo"] in wanted]
        meta = parse_stations(raw_meta)
        missing = sorted(set(wanted) - set(meta))
        if missing:
            raise RuntimeError(f"stations not in SNIH LeerEstaciones: {missing}")
        for sid in wanted:
            time.sleep(sleep)
            rows = fetch_station_series(client, sid, meta[sid]["alta_year"], today, sleep, progress)
            (raw_dir / f"{sid}.json").write_text(json.dumps(rows), encoding="utf-8")
    # merge with the previous metadata so a partial fetch keeps the other stations
    meta_path = raw_dir / "stations.json"
    previous = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    rows = {r["Codigo"]: r for r in previous.get("stations", [])}
    fetched_by = dict(previous.get("fetched_by_station", {}))
    fetched_by.update({str(c): previous["fetched"] for c in rows if str(c) not in fetched_by})
    for r in raw_meta:
        rows[r["Codigo"]] = r
        fetched_by[str(r["Codigo"])] = today.isoformat()
    payload = {
        "fetched": today.isoformat(),
        "fetched_by_station": {k: fetched_by[k] for k in sorted(fetched_by)},
        "stations": list(rows.values()),
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return raw_dir


def build_flow(raw: list[dict], station: dict, fetched: date) -> pd.DataFrame:
    """Raw Mediciones -> full daily frame (`date`, `q_m3s`, `qualifier`, `validated`)."""
    df = pd.DataFrame(
        {
            "date": [parse_snih_date(r["FechaHora"]) for r in raw],
            "q_m3s": [r["Medicion"] for r in raw],
            "qualifier": [r.get("Calificador") or "" for r in raw],
            "validated": [bool(r.get("Validado")) for r in raw],
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    n_before = len(df)
    df = df.drop_duplicates("date", keep="first")
    duplicates = n_before - len(df)
    q = pd.to_numeric(df["q_m3s"], errors="coerce").astype(float)
    df["q_m3s"] = q.where(q >= 0)
    df["qualifier"] = df["qualifier"].astype(str).str.strip()
    df = df.set_index("date").sort_index()
    full = pd.date_range(df.index.min(), df.index.max(), freq="D", name="date")
    df = df.reindex(full)
    df["q_m3s"] = df["q_m3s"].astype(float)
    df["qualifier"] = df["qualifier"].fillna("").astype(str)
    df["validated"] = df["validated"].fillna(False).astype(bool)
    df = df.reset_index()
    df.attrs.update(
        {
            "source": SOURCE,
            "url": SNIH_URL,
            "station_id": station["id"],
            "station_name": station["name"],
            "river": station["river"],
            "fetched": fetched.isoformat(),
            "duplicates_dropped": duplicates,
        }
    )
    return df


def write_flow(df: pd.DataFrame, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)  # pandas stores df.attrs in the parquet metadata
    return path


def read_flow(path: Path | str) -> pd.DataFrame:
    return pd.read_parquet(path)


def gap_stats(df: pd.DataFrame) -> dict:
    """Valid-day share and the longest run of missing days."""
    missing = df["q_m3s"].isna().to_numpy()
    longest, best_end, run = 0, -1, 0
    for i, m in enumerate(missing):
        run = run + 1 if m else 0
        if run > longest:
            longest, best_end = run, i
    dates = df["date"].dt.date.to_numpy()
    valid = int((~missing).sum())
    return {
        "total_days": len(df),
        "valid_days": valid,
        "valid_pct": 100.0 * valid / len(df) if len(df) else 0.0,
        "longest_gap_days": longest,
        "longest_gap_start": dates[best_end - longest + 1] if longest else None,
        "longest_gap_end": dates[best_end] if longest else None,
    }


def hydro_year_completeness(
    df: pd.DataFrame, start_month: int = 4, min_valid: int = MIN_VALID_DAYS
) -> pd.DataFrame:
    """Valid days per hydrological year (labelled by start year) and complete flag.

    Reused by F2.2 to pick the years that enter the annual maxima.
    """
    d = df["date"]
    year = np.where(d.dt.month >= start_month, d.dt.year, d.dt.year - 1)
    counts = df["q_m3s"].notna().groupby(year).sum()
    return pd.DataFrame(
        {
            "hydro_year": counts.index.astype(int),
            "valid_days": counts.to_numpy().astype(int),
            "complete": (counts >= min_valid).to_numpy(),
        }
    )


def ingest_flow(
    raw_dir: Path | str = RAW_DIR, out_dir: Path | str = OUT_DIR
) -> tuple[dict[int, pd.DataFrame], dict[int, dict]]:
    """Raw JSON -> `<out_dir>/<id>.parquet` and `stations.json`. No network."""
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    payload = json.loads((raw_dir / "stations.json").read_text(encoding="utf-8"))
    fetched = date.fromisoformat(payload["fetched"])
    meta = parse_stations(payload["stations"])
    frames: dict[int, pd.DataFrame] = {}
    for sid, m in meta.items():
        path = raw_dir / f"{sid}.json"
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not raw:
            m.update(first_date=None, last_date=None, first_valid_date=None, last_valid_date=None)
            continue
        station_fetched = payload.get("fetched_by_station", {}).get(str(sid))
        df = build_flow(
            raw, _BY_ID[sid], date.fromisoformat(station_fetched) if station_fetched else fetched
        )
        write_flow(df, out_dir / f"{sid}.parquet")
        frames[sid] = df
        valid = df.loc[df["q_m3s"].notna(), "date"]
        m["first_date"] = df["date"].iloc[0].date().isoformat()
        m["last_date"] = df["date"].iloc[-1].date().isoformat()
        m["first_valid_date"] = valid.iloc[0].date().isoformat() if len(valid) else None
        m["last_valid_date"] = valid.iloc[-1].date().isoformat() if len(valid) else None
    order = [s["id"] for s in STATIONS]
    meta = {sid: meta[sid] for sid in order if sid in meta and "first_date" in meta[sid]}
    frames = {sid: frames[sid] for sid in order if sid in frames}
    out_dir.mkdir(parents=True, exist_ok=True)
    stations_out = {
        "source": SOURCE,
        "url": SNIH_URL,
        "fetched": fetched.isoformat(),
        "stations": list(meta.values()),
    }
    (out_dir / "stations.json").write_text(
        json.dumps(stations_out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return frames, meta


def _fmt(n: float, decimals: int = 0) -> str:
    return (
        f"{n:,.{decimals}f}".replace(",", " ").replace(".", ",")
        if decimals
        else f"{n:,.0f}".replace(",", " ")
    )


def build_report(frames: dict[int, pd.DataFrame], meta: dict[int, dict]) -> str:
    """Spanish gap report (F2.1) for the ingested stations."""
    fetched = next(iter(frames.values())).attrs["fetched"]
    lines = [
        "# F2.1 — Caudales diarios del SNIH y control de huecos",
        "",
        f"Fecha de consulta (última actualización de los datos): {fetched} · Tarea: `plan/02-floods.md`, F2.1",
        "",
        "## Fuente y método",
        "",
        (f"- Fuente: {SOURCE}, Subsecretaría de Recursos Hídricos de la Nación ({SNIH_URL}). "
         "Parámetro 101, caudal medio diario (m³/s), valores validados."),
        ("- Términos del SNIH (`/Terminos.aspx`, §7): uso libre; hay que mantener el sentido original, citar al SIPH/SNIH "
         f"(y a la red aportante) como fuente y declarar la fecha de última actualización ({fetched})."),
        ("- Ingesta: se descartan fechas duplicadas exactas (se conserva la primera), los valores no numéricos o "
         "negativos pasan a NaN y la serie se reindexa a días consecutivos, de modo que cada hueco es una fila NaN."),
        ("- Año hidrológico: empieza en el mes `MesHidrologico` del SNIH (abril para estas estaciones) y se rotula con "
         "el año de inicio (2023 = 2023-04-01 a 2024-03-31)."),
        f"- Regla de año completo: ≥ {MIN_VALID_DAYS} días válidos. Es un supuesto del proyecto (S5), no viene del SNIH.",
        "",
        "## Estaciones",
        "",
        "| ID | Estación | Río | Período | Área (km²) | Días válidos | Hueco más largo | Duplicados |",
        "|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for sid, df in frames.items():
        m, s = meta[sid], gap_stats(df)
        period = f"{m['first_date']} a {m['last_date']}"
        area = _fmt(m["area_km2"]) if m["area_km2"] else "sin verificar"
        gap = (
            f"{_fmt(s['longest_gap_days'])} d ({s['longest_gap_start']} a {s['longest_gap_end']})"
            if s["longest_gap_days"]
            else "ninguno"
        )
        lines.append(
            f"| {sid} | {m['name']} | {m['river']} | {period} | {area} | "
            f"{_fmt(s['valid_pct'], 1)} % | {gap} | {df.attrs['duplicates_dropped']} |"
        )
    empty = [m for m in meta.values() if m["first_date"] is None]
    if empty:
        lines += [
            "",
            "Sin datos en el SNIH (parámetro 101, con y sin validar; serie vacía desde el alta de la estación hasta la fecha de consulta):",
            "",
        ]
        lines += [f"- {m['id']} {m['name']} ({m['river']})." for m in empty]
    notes = [(sid, m["note"]) for sid, m in meta.items() if m["note"]]
    if notes:
        lines += ["", "Notas:", ""]
        lines += [f"- {sid} {meta[sid]['name']}: {note}." for sid, note in notes]
    lines += [
        "",
        "## Años hidrológicos",
        "",
        (
            "Días válidos por año hidrológico; ✓ marca los años completos "
            f"(≥ {MIN_VALID_DAYS} días, supuesto S5). Los años extremos pueden ser parciales."
        ),
        "",
    ]
    tables = {
        sid: hydro_year_completeness(df, meta[sid]["hydro_year_start_month"])
        for sid, df in frames.items()
    }
    ids = list(frames)
    lines.append("| Año | " + " | ".join(str(i) for i in ids) + " |")
    lines.append("|---|" + "---|" * len(ids))
    all_years = sorted({y for t in tables.values() for y in t["hydro_year"]})
    for y in all_years:
        cells = []
        for sid in ids:
            t = tables[sid].set_index("hydro_year")
            cells.append(
                ""
                if y not in t.index
                else f"{t.loc[y, 'valid_days']}{' ✓' if t.loc[y, 'complete'] else ''}"
            )
        lines.append(f"| {y} | " + " | ".join(cells) + " |")
    lines += ["", "Años completos por estación:", ""]
    for sid in ids:
        t = tables[sid]
        lines.append(f"- {sid} {meta[sid]['name']}: {int(t['complete'].sum())} de {len(t)}")
    lines.append("")
    return "\n".join(lines)


def write_report(text: str, path: Path | str = REPORT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path

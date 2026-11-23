# ruff: noqa: B008
"""`clima-nqn forecast` commands (wired in the main CLI with ``app.add_typer(forecast_app, name="forecast")``)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import typer

from clima_nqn.forecast import baselines, riskday_model, scoring
from clima_nqn.forecast.registry import (
    InputSource,
    PredictionRegistry,
    RegistryError,
)
from clima_nqn.io.flow import SOURCE, read_flow

forecast_app = typer.Typer(help="Predicciones congeladas y verificación prospectiva (fase 6).")


def _stations(flow_dir: Path) -> dict[str, pd.DataFrame]:
    return {p.stem: read_flow(p) for p in sorted(flow_dir.glob("*.parquet")) if p.stem.isdigit()}


@forecast_app.command("emit")
def emit_cmd(
    flow_dir: Path = typer.Option(..., help="Carpeta con un Parquet de caudal por estación."),
    registry: Path = typer.Option(..., help="Archivo JSONL del registro."),
    issue_date: str = typer.Option(None, help="AAAA-MM-DD; por defecto hoy (UTC)."),
    model_version: str = typer.Option("v1", help="Versión de los baselines."),
    models: str = typer.Option(
        "climatologia", help="Modelos separados por coma: climatologia, persistencia."
    ),
    station: list[str] = typer.Option(None, help="Estación (repetible); por defecto todas."),
) -> None:
    """Emite baselines a 1-10 días por estación y los agrega al registro (idempotente por día)."""
    wanted = tuple(m.strip() for m in models.split(",") if m.strip())
    bad = set(wanted) - set(baselines.MODELS)
    if bad or not wanted:
        typer.echo(f"Modelos no válidos: {sorted(bad)}", err=True)
        raise typer.Exit(2)
    day = date.fromisoformat(issue_date) if issue_date else datetime.now(UTC).date()
    reg = PredictionRegistry(registry)
    total = 0
    done = {(r.model_version, r.region, r.issued_at.date()) for r in reg.read()}  # already emitted
    for sid, flow in _stations(flow_dir).items():
        if station and sid not in station:
            continue
        todo = tuple(m for m in wanted if (f"{m}-{model_version}", sid, day) not in done)
        if not todo:
            typer.echo(f"{sid}: ya emitido para {day} ({model_version}), se omite")
            continue
        valid = flow.dropna(subset=["q_m3s"])
        valid = valid[valid["date"] <= pd.Timestamp(day)]
        if valid.empty:
            typer.echo(f"{sid}: sin datos, se omite")
            continue
        first, last = valid["date"].iloc[0].date(), valid["date"].iloc[-1].date()
        latency = float((day - last).days * 24)
        inputs = [
            InputSource(name=f"{SOURCE} (caudal diario, estación {sid})", latency_hours=latency)
        ]
        try:
            recs = baselines.emit(reg, sid, flow, day, model_version, (first, last), inputs, todo)
        except RegistryError as e:
            typer.echo(f"{sid}: {e}", err=True)
            raise typer.Exit(1) from e
        total += len(recs)
        typer.echo(
            f"{sid}: {len(recs)} predicciones (entrenamiento {first}/{last}, rezago {int(latency / 24)} d)"
        )
    typer.echo(f"Total agregado: {total}. Cabeza del registro: {reg.verify()}")


@forecast_app.command("score")
def score_cmd(
    registry: Path = typer.Option(..., help="Archivo JSONL del registro."),
    out: Path = typer.Option(..., help="Prefijo de salida: escribe <out>.json y <out>.md."),
    flow_dir: Path = typer.Option(None, help="Carpeta con un Parquet de caudal por estación."),
    era5t_regions: Path = typer.Option(
        None, help="Carpeta con <fecha>.parquet de lluvia regional ERA5T (para p_dia_riesgo)."
    ),
    n_boot: int = typer.Option(2000),
    seed: int = typer.Option(0),
) -> None:
    """Puntúa las predicciones del registro con lo observado y escribe la tabla de skill."""
    reg = PredictionRegistry(registry)
    reg.verify()
    records = reg.read()
    stations = _stations(flow_dir) if flow_dir else {}
    regional = scoring.read_regional_observations(era5t_regions) if era5t_regions else {}
    risk = riskday_model.VAR_RISK
    frames = []
    for sid in sorted({r.region for r in records if r.variable != risk}):
        flow = stations.get(sid)
        obs = {} if flow is None else flow.dropna(subset=["q_m3s"]).set_index("date")["q_m3s"]
        frames.append(
            scoring.score([r for r in records if r.region == sid and r.variable != risk], obs)
        )
    for rid in sorted({r.region for r in records if r.variable == risk}):
        frames.append(
            scoring.score(
                [r for r in records if r.region == rid and r.variable == risk],
                regional.get(rid, {}),
            )
        )
    scores = (
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=scoring.COLUMNS)
    )
    table = scoring.skill_table(scores, n_boot=n_boot, seed=seed)
    today = datetime.now(UTC).date()
    seasons, events_pooled = scoring.season_table(scores, today, n_boot=n_boot, seed=seed)
    pending = int((scores["status"] == "pending").sum())
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Registro de predicciones F6.4 + " + SOURCE + " + ERA5T regional (p_dia_riesgo)",
        "records": len(records),
        "pending": pending,
        "n_boot": n_boot,
        "seed": seed,
        "table": json.loads(table.to_json(orient="records")),
        "scored_on": today.isoformat(),
        "seasons": json.loads(seasons.to_json(orient="records")),
        "events_pooled": events_pooled,
    }
    Path(f"{out}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    Path(f"{out}.md").write_text(scoring.to_markdown(table, pending), encoding="utf-8")
    typer.echo(
        f"{len(records)} registros, {pending} pendientes, {len(table)} filas de skill -> {out}.json/.md"
    )


@forecast_app.command("riskday-fit")
def riskday_fit_cmd(
    fc: Path = typer.Option(..., help="gefs-reforecast.zarr con casos de todos los días (F5.3)."),
    obs: Path = typer.Option(
        ..., help="reports/05/F5.3-obs.csv o zarr ERA5 con precip_mm y cp_mm."
    ),
    events: Path = typer.Option(..., help="events.parquet del catálogo F1.3."),
    out: Path = typer.Option(..., help="JSON del modelo congelado."),
    n_boot: int = typer.Option(riskday_model.N_BOOT, help="Conjuntos de coeficientes bootstrap."),
    seed: int = typer.Option(riskday_model.SEED),
) -> None:
    """Ajusta y congela la logística F5.3 (2000-2014) para el día de riesgo y la escribe como JSON."""
    from clima_nqn.stages.hindcast import riskday as rd

    model = riskday_model.fit_frozen(rd.load_inputs(fc, obs, events), n_boot=n_boot, seed=seed)
    sha = riskday_model.write_model(model, out)
    typer.echo(f"{out}: sha256 {sha}; versión {riskday_model.model_version(sha)}")


@forecast_app.command("riskday-set-cap")
def riskday_set_cap_cmd(
    gate: Path = typer.Option(..., help="reports/05/F5.8.json (campo prob_cap_vigente)."),
    model: Path = typer.Option(
        ..., help="JSON del modelo congelado; se escribe <modelo>.caps.json."
    ),
) -> None:
    """Escribe los topes de probabilidad vigentes junto al modelo, sin tocar el JSON del modelo."""
    out = riskday_model.write_caps(gate, model)
    typer.echo(f"{out}: topes desde {gate.name}; el modelo no se modifica")


@forecast_app.command("emit-riskday")
def emit_riskday_cmd(
    gefs_regions: Path = typer.Option(..., help="Carpeta con <fecha>.parquet de GEFS por región."),
    model: Path = typer.Option(..., help="JSON del modelo congelado (riskday-fit)."),
    registry: Path = typer.Option(..., help="Archivo JSONL del registro."),
    issue_date: str = typer.Option(None, help="AAAA-MM-DD; por defecto hoy (UTC)."),
    models: str = typer.Option(
        "logistica,climatologia", help="Modelos separados por coma: logistica, climatologia."
    ),
) -> None:
    """Emite p_dia_riesgo a 1-10 días por región (logística y climatología); idempotente por día."""
    wanted = tuple(m.strip() for m in models.split(",") if m.strip())
    bad = set(wanted) - set(riskday_model.MODELS)
    if bad or not wanted:
        typer.echo(f"Modelos no válidos: {sorted(bad)}", err=True)
        raise typer.Exit(2)
    day = date.fromisoformat(issue_date) if issue_date else datetime.now(UTC).date()
    mdl, sha = riskday_model.load_model(model)
    reg = PredictionRegistry(registry)
    versions = {
        "logistica": riskday_model.model_version(sha, "log"),
        "climatologia": riskday_model.model_version(sha, "clim"),
    }
    done = {(r.model_version, r.issued_at.date()) for r in reg.read()}
    todo = tuple(m for m in wanted if (versions[m], day) not in done)
    if not todo:
        typer.echo(f"p_dia_riesgo: ya emitido para {day}, se omite")
        return
    try:
        snap = riskday_model.latest_snapshot(gefs_regions, day)
        recs = riskday_model.emit(reg, mdl, sha, snap, day, todo, riskday_model.load_caps(model))
    except (RegistryError, FileNotFoundError, ValueError) as e:
        typer.echo(f"p_dia_riesgo: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"p_dia_riesgo: {len(recs)} predicciones desde {snap.name}")
    typer.echo(f"Cabeza del registro: {reg.verify()}")


@forecast_app.command("emit-seasonal")
def emit_seasonal_cmd(
    registry: Path = typer.Option(..., help="Archivo JSONL del registro."),
    oni: Path = typer.Option(
        ..., help="Carpeta con <fecha>.parquet de ONI (ops ingest) o un Parquet date/oni."
    ),
    issue_date: str = typer.Option(None, help="AAAA-MM-01; por defecto hoy (UTC). Solo día 1."),
    models_dir: Path = typer.Option(Path("models/seasonal-v1"), help="Modelos y referencia."),
    f62: Path = typer.Option(Path("../reports/06/F6.2.json"), help="Veredicto del hindcast F6.2."),
) -> None:
    """Emite la perspectiva estacional mensual «Experimental» (terciles, anticipaciones 1-6 meses)."""
    from clima_nqn.stages.seasonal import emit as se

    day = date.fromisoformat(issue_date) if issue_date else datetime.now(UTC).date()
    path = max(oni.glob("*.parquet")) if oni.is_dir() else oni
    fetchers = se.arco_fetchers(lambda: pd.read_parquet(path))
    reg = PredictionRegistry(registry)
    try:
        res = se.emit_seasonal(reg, day, fetchers, models_dir, f62)
    except (se.SeasonalEmitError, RegistryError, OSError, ValueError) as e:
        typer.echo(f"estacional: {e}", err=True)
        raise typer.Exit(1) from e
    for what, why in res.skipped.items():
        typer.echo(f"omitido {what}: {why}")
    typer.echo(f"ARCO-ERA5T, última hora disponible: {res.arco_latest}")
    typer.echo(f"estacional: {len(res.records)} predicciones nuevas")
    typer.echo(f"Cabeza del registro: {reg.verify()}")


@forecast_app.command("promote")
def promote_cmd(
    status: Path = typer.Option(..., help="Registro de estados JSONL (status/outlook.jsonl)."),
    region: str = typer.Option(..., help="Región."),
    lead: list[int] = typer.Option(..., help="Anticipación GEFS (repetible, contiguas desde 1)."),
    model_version: str = typer.Option(..., help="Versión congelada del modelo."),
    approved_by: str = typer.Option(..., help="Quién aprueba la promoción (obligatorio)."),
    approved_on: str = typer.Option(..., help="Fecha de aprobación AAAA-MM-DD (obligatorio)."),
    scores: Path = typer.Option(..., help="scores/latest.json (forecast score)."),
    season: int = typer.Option(..., help="Año de la temporada húmeda mayo–septiembre completada."),
    f58: Path = typer.Option(Path("reports/05/F5.8.json"), help="Veredicto del hindcast."),
    n_events_pooled: int = typer.Option(
        None, help="Anula los eventos agrupados de scores (queda registrado como override)."
    ),
    variable: str = typer.Option(riskday_model.VAR_RISK),
    model: str = typer.Option("logistica", help="Nombre del modelo en la tabla de skill."),
) -> None:
    """Promueve a «Perspectiva de riesgo» si pasa la compuerta. Solo manual: nunca corre en el workflow."""
    import hashlib

    from clima_nqn.forecast import status as st

    payload = json.loads(scores.read_text(encoding="utf-8"))
    raw = f58.read_bytes()
    try:
        done = st.promote(
            st.StatusLog(status),
            variable=variable,
            region=region,
            leads=lead,
            model_version=model_version,
            approved_by=approved_by,
            approved_on=date.fromisoformat(approved_on),
            f58=json.loads(raw),
            f58_sha=hashlib.sha256(raw).hexdigest(),
            season_rows=payload.get("seasons", []),
            n_events_pooled_override=n_events_pooled,
            season=season,
            model=model,
        )
    except st.PromotionRefused as e:
        for r in e.reasons:
            typer.echo(f"No se promueve: {r}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"{len(done)} anticipaciones promovidas en {region}: {[r['lead'] for r in done]}")


@forecast_app.command("demote-auto")
def demote_auto_cmd(
    status: Path = typer.Option(..., help="Registro de estados JSONL."),
    scores: Path = typer.Option(..., help="scores/latest.json (forecast score)."),
    model_version: list[str] = typer.Option(..., help="Versión en uso (repetible)."),
) -> None:
    """Desciende a «Experimental» por BSS prospectivo < 0 o cambio de versión (arrastra las más largas)."""
    from clima_nqn.forecast import status as st

    payload = json.loads(scores.read_text(encoding="utf-8")) if scores.exists() else {}
    done = st.demote_auto(st.StatusLog(status), payload.get("seasons", []), set(model_version))
    for r in done:
        typer.echo(f"{r['region']} anticipación {r['lead']}: {r['reason']}")
    typer.echo(f"{len(done)} descensos")


@forecast_app.command("outlook-layer")
def outlook_layer_cmd(
    registry: Path = typer.Option(..., help="Archivo JSONL del registro."),
    out: Path = typer.Option(
        Path("data/processed/forecast-outlook"), help="Carpeta de la capa forecast-outlook."
    ),
    scores: Path = typer.Option(
        None, help="scores/latest.json (opcional; sin él, historial vacío)."
    ),
    status: Path = typer.Option(
        None, help="status/outlook.jsonl (opcional; sin él, todo Experimental)."
    ),
    gate: Path = typer.Option(
        Path("../reports/05/F5.8.json"), help="Veredicto del hindcast (F5.8)."
    ),
    f62: Path = typer.Option(
        Path("../reports/06/F6.2.json"), help="Hindcast estacional (F6.2); si falta, sin skill."
    ),
    f67: Path = typer.Option(
        Path("../reports/06/F6.7.json"),
        help="Prueba de caudal alto (F6.7); si falta, no disponible.",
    ),
    f69: Path = typer.Option(
        Path("../reports/06/F6.9.json"),
        help="Climatología condicional (F6.9); si falta, no disponible.",
    ),
) -> None:
    """Escribe la capa del visor: día de riesgo (F6.6), perspectiva estacional y evidencia de caudal alto."""
    from clima_nqn.forecast.registry import RegistryTamperError
    from clima_nqn.layers import forecast_outlook as fo

    if not gate.is_file():
        typer.echo(f"No existe el veredicto del hindcast: {gate}", err=True)
        raise typer.Exit(1)
    try:
        fo.build(registry, out, scores, status, gate, f62, f67, f69, extras_blocks=True)
    except (fo.OutlookError, RegistryTamperError) as e:
        typer.echo(f"forecast-outlook: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"forecast-outlook -> {out}")

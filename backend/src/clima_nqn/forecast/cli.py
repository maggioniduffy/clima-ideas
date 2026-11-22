# ruff: noqa: B008
"""`clima-nqn forecast` commands (wired in the main CLI with ``app.add_typer(forecast_app, name="forecast")``)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import typer

from clima_nqn.forecast import baselines, scoring
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
) -> None:
    """Emite climatología y persistencia a 1-10 días para cada estación y las agrega al registro."""
    day = date.fromisoformat(issue_date) if issue_date else datetime.now(UTC).date()
    reg = PredictionRegistry(registry)
    total = 0
    for sid, flow in _stations(flow_dir).items():
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
            recs = baselines.emit(reg, sid, flow, day, model_version, (first, last), inputs)
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
    flow_dir: Path = typer.Option(..., help="Carpeta con un Parquet de caudal por estación."),
    registry: Path = typer.Option(..., help="Archivo JSONL del registro."),
    out: Path = typer.Option(..., help="Prefijo de salida: escribe <out>.json y <out>.md."),
    n_boot: int = typer.Option(2000),
    seed: int = typer.Option(0),
) -> None:
    """Puntúa las predicciones del registro con lo observado y escribe la tabla de skill."""
    reg = PredictionRegistry(registry)
    reg.verify()
    records = reg.read()
    stations = _stations(flow_dir)
    frames = []
    for sid in sorted({r.region for r in records}):
        flow = stations.get(sid)
        obs = {} if flow is None else flow.dropna(subset=["q_m3s"]).set_index("date")["q_m3s"]
        frames.append(scoring.score([r for r in records if r.region == sid], obs))
    scores = (
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=scoring.COLUMNS)
    )
    table = scoring.skill_table(scores, n_boot=n_boot, seed=seed)
    pending = int((scores["status"] == "pending").sum())
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Registro de predicciones F6.4 + " + SOURCE,
        "records": len(records),
        "pending": pending,
        "n_boot": n_boot,
        "seed": seed,
        "table": json.loads(table.to_json(orient="records")),
    }
    Path(f"{out}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    Path(f"{out}.md").write_text(scoring.to_markdown(table, pending), encoding="utf-8")
    typer.echo(
        f"{len(records)} registros, {pending} pendientes, {len(table)} filas de skill -> {out}.json/.md"
    )

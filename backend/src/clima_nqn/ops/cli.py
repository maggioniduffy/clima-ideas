"""``clima-nqn ops`` commands."""

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.ops import ingest

ops_app = typer.Typer(help="Operational data for the forecast phase (F6.1).")


@ops_app.callback()
def main() -> None:
    """Operational data for the forecast phase (F6.1)."""


@ops_app.command("ingest")
def ops_ingest(
    run_date: Annotated[
        datetime | None,
        typer.Option("--date", formats=["%Y-%m-%d"], help="Ingest date, default today."),
    ] = None,
    root: Annotated[Path, typer.Option(help="Output root.")] = ingest.DEFAULT_ROOT,
    sources: Annotated[
        str | None, typer.Option(help=f"Comma-separated subset of {','.join(ingest.SOURCES)}.")
    ] = None,
    force: Annotated[bool, typer.Option(help="Refetch and rewrite existing snapshots.")] = False,
) -> None:
    """Idempotent ingest of flow, ONI, ERA5T, ECMWF, GEFS and the regional GEFS/ERA5T inputs; exit 1 only if all fail."""
    day = run_date.date() if run_date else date.today()
    names = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    try:
        results = ingest.run_ingest(day, root, names, force)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    for name, e in results.items():
        detail = e["error"] or (
            f"newest {e['newest_value_date']}, lag {e['lag_days']} d, {e['rows']} rows"
        )
        typer.echo(f"{name}: {e['status']} ({detail})")
    if all(e["status"] == "failed" for e in results.values()):
        raise typer.Exit(1)

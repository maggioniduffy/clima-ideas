from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.io.enso import DEFAULT_PATH, build_enso, fetch_oni, write_enso

app = typer.Typer(help="clima-nqn command line interface.")


@app.callback()
def main() -> None:
    """clima-nqn command line interface."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo("0.1.0")


enso_app = typer.Typer(help="Shared ENSO index (NOAA CPC ONI).")
app.add_typer(enso_app, name="enso")


@enso_app.command("fetch")
def enso_fetch(
    out: Annotated[Path, typer.Option(help="Output Parquet path.")] = DEFAULT_PATH,
) -> None:
    """Fetch ONI, classify phases and write the monthly Parquet."""
    df = build_enso(fetch_oni())
    path = write_enso(df, out)
    typer.echo(f"{len(df)} rows, {df['date'].min():%Y-%m} to {df['date'].max():%Y-%m} -> {path}")

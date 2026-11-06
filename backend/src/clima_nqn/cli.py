from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.io import dem
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


dem_app = typer.Typer(help="Relief layer (Copernicus DEM GLO-30).")
app.add_typer(dem_app, name="dem")


@dem_app.command("fetch")
def dem_fetch(
    dest: Annotated[Path, typer.Option(help="Raw tile directory.")] = dem.RAW_DIR,
) -> None:
    """Download the GLO-30 tiles covering Neuquén (existing files are skipped)."""
    paths = dem.fetch_tiles(dest=dest)
    size = sum(p.stat().st_size for p in paths) / 1e6
    typer.echo(f"{len(paths)} tiles, {size:.0f} MB in {dest}")


@dem_app.command("build")
def dem_build(
    raw: Annotated[Path, typer.Option(help="Raw tile directory.")] = dem.RAW_DIR,
    out: Annotated[Path, typer.Option(help="Output layer directory.")] = dem.OUT_DIR,
    step: Annotated[float, typer.Option(help="Grid step in degrees.")] = dem.DEFAULT_STEP,
) -> None:
    """Decimate tiles to relief.bin (Float32 [lon, lat, elev_m]) with its manifest."""
    path = dem.build_relief(raw, out, step=step)
    typer.echo(f"{path.stat().st_size / 1e6:.2f} MB -> {path}")

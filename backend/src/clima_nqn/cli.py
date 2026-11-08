from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.io import dem, era5
from clima_nqn.io.enso import DEFAULT_PATH, build_enso, fetch_oni, read_enso, write_enso
from clima_nqn.stages.ar import catalog as ar_catalog
from clima_nqn.stages.ar import extremes as ar_extremes

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


era5_app = typer.Typer(help="Regional ERA5 for Neuquén (ARCO-ERA5 Zarr, no CDS account).")
app.add_typer(era5_app, name="era5")


@era5_app.command("fetch")
def era5_fetch(
    year: Annotated[int | None, typer.Option(help="Calendar year.")] = None,
    years: Annotated[
        str | None, typer.Option(help='Several years, e.g. "1980-2025" or "1980-1985,1990".')
    ] = None,
    months: Annotated[str, typer.Option(help='Months, e.g. "1-12", "3", "1,2,5-7".')] = "1-12",
    hours: Annotated[str, typer.Option(help='UTC hours, e.g. "0-23", "0,12".')] = "0-23",
    area: Annotated[
        str, typer.Option("--area", help="N,W,S,E (use --area=N,W,S,E for negatives).")
    ] = ",".join(f"{x:g}" for x in era5.NEUQUEN_BOX),
    out: Annotated[Path, typer.Option(help="Per-year store directory.")] = era5.DEFAULT_OUT,
    workers: Annotated[
        int, typer.Option(help="Concurrent hour-chunk reads.")
    ] = era5.DEFAULT_WORKERS,
    retries: Annotated[int, typer.Option(help="Attempts per read.")] = 3,
) -> None:
    """Fetch one or more years to <out>/<year>.zarr (complete years skipped, incomplete rebuilt)."""
    if (year is None) == (years is None):
        raise typer.BadParameter("give exactly one of --year or --years")
    try:
        box = era5.parse_area(area)
        month_list, hour_list = era5.parse_months(months), era5.parse_hours(hours)
        year_list = [year] if year is not None else era5.parse_years(years or "")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    failed: list[int] = []
    for y in year_list:
        try:
            era5.fetch_year(y, month_list, hour_list, box, out, workers=workers, retries=retries)
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            typer.echo(f"year {y} failed: {exc}", err=True)
            failed.append(y)
    if failed:
        typer.echo(f"years failed: {failed}", err=True)
        raise typer.Exit(1)


@era5_app.command("combine")
def era5_combine(
    src: Annotated[Path, typer.Option(help="Per-year store directory.")] = era5.DEFAULT_OUT,
    out: Annotated[Path, typer.Option(help="Combined store.")] = era5.COMBINED,
) -> None:
    """Concatenate all per-year stores into one time-series store."""
    era5.combine(src, out)


ar_app = typer.Typer(help="Atmospheric rivers in the Neuquén cordillera (phase 1).")
app.add_typer(ar_app, name="ar")


@ar_app.command("catalog")
def ar_catalog_cmd(
    bard_dir: Annotated[Path, typer.Option(help="Directory searched for bard_neuquen_*.nc.")],
    era5_dir: Annotated[Path, typer.Option(help="Directory with the <year>.zarr stores.")],
    threshold: Annotated[float, typer.Option(help="BARD probability threshold.")] = 0.67,
    max_gap_steps: Annotated[
        int, typer.Option(help="Non-AR 6-hourly steps allowed inside one event.")
    ] = 0,
    out: Annotated[Path, typer.Option(help="Output Parquet path.")] = ar_catalog.DEFAULT_OUT,
    enso: Annotated[
        Path, typer.Option(help="ENSO Parquet (clima-nqn enso fetch); skipped if missing.")
    ] = DEFAULT_PATH,
) -> None:
    """Build the AR event catalog (BARD events + ERA5 statistics over the cordillera polygon)."""
    bard = sorted(bard_dir.rglob("bard_neuquen_*.nc"))
    era5_stores = sorted(p for p in era5_dir.glob("[0-9][0-9][0-9][0-9].zarr") if p.is_dir())
    if not bard:
        raise typer.BadParameter(f"no bard_neuquen_*.nc under {bard_dir}")
    if not era5_stores:
        raise typer.BadParameter(f"no <year>.zarr stores in {era5_dir}")
    enso_df = read_enso(enso) if enso.exists() else None
    if enso_df is None:
        typer.echo(f"ENSO table not found at {enso}: enso_phase left empty", err=True)
    df = ar_catalog.build_catalog(bard, era5_stores, threshold, max_gap_steps, enso=enso_df)
    path = ar_catalog.write_catalog(df, out)
    period = df.attrs["period"]
    first, last = (int(x[:4]) for x in period.split("/"))
    years = last - first + 1
    typer.echo(
        f"{len(df)} events, {period}, {len(df) / years:.1f} events/year "
        f"(threshold {threshold}, max_gap_steps {max_gap_steps}) -> {path}"
    )


@ar_app.command("extremes")
def ar_extremes_cmd(
    events: Annotated[Path, typer.Option(help="Catalog Parquet (clima-nqn ar catalog).")] = (
        ar_catalog.DEFAULT_OUT
    ),
    era5_dir: Annotated[Path, typer.Option(help="Directory with the <year>.zarr stores.")] = (
        era5.DEFAULT_OUT
    ),
    out_dir: Annotated[Path, typer.Option(help="Directory for F1.4.md and F1.4.json.")] = (
        ar_catalog.DEFAULT_OUT.parent
    ),
) -> None:
    """Coincidence of extreme daily rain over the cordillera with AR events (F1.4)."""
    if not events.exists():
        raise typer.BadParameter(f"catalog not found: {events}")
    era5_stores = sorted(p for p in era5_dir.glob("[0-9][0-9][0-9][0-9].zarr") if p.is_dir())
    if not era5_stores:
        raise typer.BadParameter(f"no <year>.zarr stores in {era5_dir}")
    results = ar_extremes.run(events, era5_stores, out_dir)
    typer.echo(ar_extremes.headline(results))
    typer.echo(f"-> {out_dir / 'F1.4.md'}, {out_dir / 'F1.4.json'}")

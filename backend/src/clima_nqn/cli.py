import json
from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.io import dem, era5, flow
from clima_nqn.io.enso import DEFAULT_PATH, build_enso, fetch_oni, read_enso, write_enso
from clima_nqn.layers import flood_stations
from clima_nqn.stages.ar import catalog as ar_catalog
from clima_nqn.stages.ar import enso as ar_enso
from clima_nqn.stages.ar import extremes as ar_extremes
from clima_nqn.stages.ar import layer as ar_layer
from clima_nqn.stages.flood import extremes as flood_extremes

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


flow_app = typer.Typer(help="Daily streamflow from SNIH (phase 2).")
app.add_typer(flow_app, name="flow")


@flow_app.command("fetch")
def flow_fetch(
    raw: Annotated[Path, typer.Option(help="Raw JSON directory.")] = flow.RAW_DIR,
    station: Annotated[
        list[int] | None, typer.Option(help="Station ID (repeatable); default all.")
    ] = None,
) -> None:
    """Download daily mean flow (SNIH, ~1 s between requests) to raw JSON."""
    path = flow.fetch_flow(raw, stations=station, progress=typer.echo)
    typer.echo(f"raw flow -> {path}")


@flow_app.command("ingest")
def flow_ingest(
    raw: Annotated[Path, typer.Option(help="Raw JSON directory.")] = flow.RAW_DIR,
    out: Annotated[Path, typer.Option(help="Output Parquet directory.")] = flow.OUT_DIR,
    report: Annotated[Path, typer.Option(help="Gap report path.")] = flow.REPORT_PATH,
) -> None:
    """Build per-station Parquet files and the gap report from raw JSON (no network)."""
    frames, meta = flow.ingest_flow(raw, out)
    if not frames:
        raise typer.BadParameter(f"no raw series in {raw} (run clima-nqn flow fetch)")
    flow.write_report(flow.build_report(frames, meta), report)
    typer.echo(f"{len(frames)} stations -> {out}; report -> {report}")


@flow_app.command("gev")
def flow_gev(
    flow_dir: Annotated[Path, typer.Option(help="Parquet directory of F2.1.")] = flow.OUT_DIR,
    out: Annotated[
        Path, typer.Option(help="Output directory for <id>.json.")
    ] = flood_extremes.GEV_DIR,
    report: Annotated[Path, typer.Option(help="Report path.")] = flood_extremes.REPORT_PATH,
    station: Annotated[
        list[int] | None, typer.Option(help="Station ID (repeatable); default 12004, 12010, 12012.")
    ] = None,
) -> None:
    """Annual maxima and GEV return levels with 95 % CI (pyextremes) per natural station."""
    results = flood_extremes.run(flow_dir, out, report, stations=station)
    typer.echo(f"{len(results)} stations -> {out}; report -> {report}")


@flow_app.command("layer")
def flow_layer(
    flow_dir: Annotated[Path, typer.Option(help="Parquet directory of F2.1.")] = flow.OUT_DIR,
    gev_dir: Annotated[
        Path, typer.Option(help="GEV JSON directory of F2.2.")
    ] = flood_extremes.GEV_DIR,
    out: Annotated[
        Path, typer.Option(help="Layer directory (manifest.json, stations.json, stations/).")
    ] = flood_stations.DEFAULT_OUT,
) -> None:
    """Publish the flood-stations viewer layer: stations, daily flow and GEV return periods (F2.4)."""
    if not (flow_dir / "stations.json").is_file():
        raise typer.BadParameter(f"no stations.json in {flow_dir} (run clima-nqn flow ingest)")
    layer_dir = flood_stations.build_layer(flow_dir, gev_dir, out)
    stations = json.loads((layer_dir / "stations.json").read_text(encoding="utf-8"))
    typer.echo(f"{len(stations)} stations -> {layer_dir}")


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


@ar_app.command("enso")
def ar_enso_cmd(
    events: Annotated[Path, typer.Option(help="Catalog Parquet (clima-nqn ar catalog).")] = (
        ar_catalog.DEFAULT_OUT
    ),
    era5_dir: Annotated[Path, typer.Option(help="Directory with the <year>.zarr stores.")] = (
        era5.DEFAULT_OUT
    ),
    enso: Annotated[Path, typer.Option(help="ENSO Parquet (clima-nqn enso fetch).")] = DEFAULT_PATH,
    out_dir: Annotated[Path, typer.Option(help="Directory for F1.8.md and F1.8.json.")] = (
        ar_catalog.DEFAULT_OUT.parent
    ),
    n_perm: Annotated[int, typer.Option(help="Permutations per test.")] = 10000,
) -> None:
    """ARs by ENSO phase and season: permutation tests, BH-adjusted (F1.8)."""
    if not events.exists():
        raise typer.BadParameter(f"catalog not found: {events}")
    if not enso.exists():
        raise typer.BadParameter(f"ENSO table not found: {enso} (run clima-nqn enso fetch)")
    era5_stores = sorted(p for p in era5_dir.glob("[0-9][0-9][0-9][0-9].zarr") if p.is_dir())
    if not era5_stores:
        raise typer.BadParameter(f"no <year>.zarr stores in {era5_dir}")
    results = ar_enso.run(events, era5_stores, enso, out_dir, n_perm=n_perm)
    rows = results["rows"]
    typer.echo(
        f"{len(rows)} tests, {sum(r['sustained'] for r in rows)} with p<0.05, "
        f"{sum(r['sustained_bh'] for r in rows)} after BH"
    )
    typer.echo(f"-> {out_dir / 'F1.8.md'}, {out_dir / 'F1.8.json'}")


@ar_app.command("layer")
def ar_layer_cmd(
    events: Annotated[Path, typer.Option(help="Catalog Parquet (clima-nqn ar catalog).")] = (
        ar_catalog.DEFAULT_OUT
    ),
    era5_dir: Annotated[Path, typer.Option(help="Directory with the <year>.zarr stores.")] = (
        era5.DEFAULT_OUT
    ),
    out: Annotated[Path, typer.Option(help="Processed root; writes <out>/ar-events/.")] = (
        ar_layer.DEFAULT_OUT
    ),
    enso_report: Annotated[
        Path,
        typer.Option(
            help="F1.8 JSON (clima-nqn ar enso); published as enso.json when it exists, else skipped."
        ),
    ] = ar_catalog.DEFAULT_OUT.parent / "F1.8.json",
) -> None:
    """Publish the ar-events viewer layer: events, hourly IVT frames and the ENSO report (F1.6, F1.8)."""
    if not events.exists():
        raise typer.BadParameter(f"catalog not found: {events}")
    if not any(era5_dir.glob("[0-9][0-9][0-9][0-9].zarr")):
        raise typer.BadParameter(f"no <year>.zarr stores in {era5_dir}")
    layer_dir, index = ar_layer.build_layer(
        events, era5_dir, out, enso_report if enso_report.is_file() else None
    )
    frames = sum(e["n_frames"] for e in index["events"].values())
    typer.echo(f"{len(index['events'])} events with frames, {frames} hourly frames -> {layer_dir}")

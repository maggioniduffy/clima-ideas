import json
import os
from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.api.app import DEFAULT_DATA_ROOT
from clima_nqn.io import dem, era5, flow, forcing, snow
from clima_nqn.io.enso import DEFAULT_PATH, build_enso, fetch_oni, read_enso, write_enso
from clima_nqn.layers import flood_stations
from clima_nqn.publish import (
    make_client,
    plan_uploads,
    publish_layers,
    resolve_credentials,
)
from clima_nqn.stages.ar import catalog as ar_catalog
from clima_nqn.stages.ar import enso as ar_enso
from clima_nqn.stages.ar import extremes as ar_extremes
from clima_nqn.stages.ar import layer as ar_layer
from clima_nqn.stages.flood import causes as flood_causes
from clima_nqn.stages.flood import enso as flood_enso
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


@flow_app.command("enso")
def flow_enso(
    flow_dir: Annotated[Path, typer.Option(help="Parquet directory of F2.1.")] = flow.OUT_DIR,
    enso: Annotated[Path, typer.Option(help="ENSO Parquet (clima-nqn enso fetch).")] = DEFAULT_PATH,
    out: Annotated[Path, typer.Option(help="Output JSON.")] = flood_enso.OUT_PATH,
    report: Annotated[Path, typer.Option(help="Report path.")] = flood_enso.REPORT_PATH,
    station: Annotated[
        list[int] | None, typer.Option(help="Station ID (repeatable); default 12004, 12010, 12012.")
    ] = None,
    analysis_station: Annotated[
        list[int] | None,
        typer.Option(
            help="Station that counts for the F6.2 verdict (repeatable); default 12004, 12010. Others are flagged unreliable."
        ),
    ] = None,
    n_perm: Annotated[int, typer.Option(help="Permutations per phase test.")] = flood_enso.N_PERM,
    addendum: Annotated[
        bool, typer.Option(help="Run the post-hoc robustness addendum (12004, 12010).")
    ] = True,
    addendum_n_perm: Annotated[
        int, typer.Option(help="Permutations per addendum permutation test.")
    ] = flood_enso.N_PERM,
) -> None:
    """Flow by ENSO phase and GEV with ONI covariate vs. stationary, BH-adjusted (F2.7)."""
    if not enso.exists():
        raise typer.BadParameter(f"ENSO table not found: {enso} (run clima-nqn enso fetch)")
    res = flood_enso.run(
        flow_dir, enso, out, report, stations=station,
        analysis=tuple(analysis_station or flood_enso.ANALYSIS_STATIONS), n_perm=n_perm,
        addendum=addendum, addendum_n_perm=addendum_n_perm,
    )  # fmt: skip
    typer.echo(f"{len(res['stations'])} stations; verdict F6.2: {res['meta']['verdict']}")
    if "addendum" in res:
        typer.echo(f"gate F6.2 (addendum): {res['addendum']['gate']['outcome']}")
    typer.echo(f"-> {out}, {report}")


@flow_app.command("snow-fetch")
def flow_snow_fetch(
    flow_dir: Annotated[Path, typer.Option(help="Parquet directory of F2.1.")] = flow.OUT_DIR,
    catalog: Annotated[
        Path, typer.Option(help="AR event catalog (clima-nqn ar catalog).")
    ] = flood_causes.DEFAULT_CATALOG,
    out: Annotated[Path, typer.Option(help="Output Parquet.")] = snow.DEFAULT_OUT,
    station: Annotated[
        list[int] | None, typer.Option(help="Station ID (repeatable); default 12004, 12010, 12012.")
    ] = None,
    workers: Annotated[int, typer.Option(help="Concurrent day reads.")] = 16,
    retries: Annotated[int, typer.Option(help="Attempts per read.")] = 3,
    retry_wait: Annotated[float, typer.Option(help="Seconds of linear backoff.")] = 30,
) -> None:
    """Download ERA5 snow water equivalent around the flood peaks (ARCO-ERA5, anonymous; F2.3)."""
    if not catalog.is_file():
        raise typer.BadParameter(f"AR catalog not found: {catalog}")
    try:
        flood_causes.validate_stations(station)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    _, period = flood_causes.load_catalog(catalog)
    floods = flood_causes.collect_floods(flow_dir, station, period)
    windows = [(sid, d) for sid, df in floods.items() for d in df["date"]]
    path = snow.fetch_snow(
        windows, out, workers=workers, retries=retries, retry_wait=retry_wait, progress=typer.echo
    )
    typer.echo(f"snow -> {path}")


@flow_app.command("forcing")
def flow_forcing(
    era5_dir: Annotated[
        Path, typer.Option(help="Per-year ERA5 Zarr stores with tp and deg0l (era5 fetch).")
    ] = forcing.DEFAULT_ERA5_DIR,
    t2m_dir: Annotated[
        Path,
        typer.Option(
            help="Per-year ERA5 Zarr stores with t2m (era5 fetch --variables 2m_temperature). "
            "Missing years leave the temperature and PET columns NaN; rerun to fill them."
        ),
    ] = forcing.DEFAULT_T2M_DIR,
    t2m_run_id: Annotated[
        str | None, typer.Option(help="Workflow run id of the t2m download, recorded as source.")
    ] = None,
    dem_dir: Annotated[
        Path, typer.Option(help="GLO-30 tiles for the static elevation attributes.")
    ] = dem.RAW_DIR,
    out: Annotated[Path, typer.Option(help="Output Parquet (static JSON goes next to it).")] = (
        forcing.DEFAULT_OUT
    ),
    station: Annotated[
        list[int] | None, typer.Option(help="Station ID (repeatable); default 12004, 12010, 12012.")
    ] = None,
) -> None:
    """Daily ERA5 forcing (P, freezing level, T, PET) per upstream basin for the flow models (F2.5)."""
    try:
        chosen = flood_causes.validate_stations(station)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    try:
        result = forcing.build_forcing(
            era5_dir, out, t2m_dir, t2m_run_id, stations=chosen, progress=typer.echo
        )
    except (FileNotFoundError, ValueError) as e:
        raise typer.BadParameter(str(e)) from e
    static = forcing.build_static(out, dem_dir, stations=chosen)
    typer.echo(f"forcing -> {result['path']}")
    typer.echo(f"static -> {static}")
    if result["missing_t2m_years"]:
        years = ", ".join(str(y) for y in result["missing_t2m_years"])
        typer.echo(f"no temperature (NaN) for years: {years}; rerun once --t2m-dir has them")


@flow_app.command("causes")
def flow_causes(
    flow_dir: Annotated[Path, typer.Option(help="Parquet directory of F2.1.")] = flow.OUT_DIR,
    gev_dir: Annotated[
        Path, typer.Option(help="GEV JSON directory of F2.2.")
    ] = flood_extremes.GEV_DIR,
    catalog: Annotated[
        Path, typer.Option(help="AR event catalog (clima-nqn ar catalog).")
    ] = flood_causes.DEFAULT_CATALOG,
    snow_path: Annotated[
        Path, typer.Option("--snow", help="Snow Parquet (clima-nqn flow snow-fetch).")
    ] = snow.DEFAULT_OUT,
    out: Annotated[Path, typer.Option(help="Output JSON.")] = flood_causes.OUT_PATH,
    report: Annotated[Path, typer.Option(help="Report path.")] = flood_causes.REPORT_PATH,
    station: Annotated[
        list[int] | None, typer.Option(help="Station ID (repeatable); default 12004, 12010, 12012.")
    ] = None,
    n_perm: Annotated[
        int, typer.Option(help="Draws of the chance baseline.")
    ] = flood_causes.N_PERM,
) -> None:
    """Label the annual floods by probable cause: AR window, chance baseline and snow (F2.3)."""
    if not catalog.is_file():
        raise typer.BadParameter(f"AR catalog not found: {catalog} (run clima-nqn ar catalog)")
    try:
        flood_causes.validate_stations(station)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    if not snow_path.is_file():
        typer.echo(
            f"warning: no snow file {snow_path}; snow is 'sin dato' (run clima-nqn flow snow-fetch)"
        )
    res = flood_causes.run(
        flow_dir, gev_dir, catalog, snow_path, out, report, stations=station, n_perm=n_perm
    )
    for s in res["stations"]:
        typer.echo(f"{s['station_id']}: {s['n_floods']} floods, {s['label_counts']}")
    typer.echo(f"-> {out}, {report}")


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
    variables: Annotated[
        str,
        typer.Option(
            help="Comma-separated ERA5 names or short names to fetch: "
            + ", ".join(f"{k} ({v})" for k, v in era5.AVAILABLE_VARIABLES.items())
            + ". Default: the four phase-1 variables."
        ),
    ] = ",".join(era5.VARIABLES),
) -> None:
    """Fetch one or more years to <out>/<year>.zarr (complete years skipped, incomplete rebuilt)."""
    if (year is None) == (years is None):
        raise typer.BadParameter("give exactly one of --year or --years")
    try:
        box = era5.parse_area(area)
        month_list, hour_list = era5.parse_months(months), era5.parse_hours(hours)
        year_list = [year] if year is not None else era5.parse_years(years or "")
        var_map = era5.resolve_variables(variables)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    failed: list[int] = []
    for y in year_list:
        try:
            era5.fetch_year(
                y,
                month_list,
                hour_list,
                box,
                out,
                workers=workers,
                retries=retries,
                variables=var_map,
            )
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


@app.command("publish")
def publish_cmd(
    root: Annotated[
        Path | None,
        typer.Option(help="Processed data root (default: $CLIMA_NQN_DATA or data/processed)."),
    ] = None,
    prefix: Annotated[str, typer.Option(help="Key prefix inside the bucket.")] = "",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List the objects to upload; no env vars, no network.")
    ] = False,
) -> None:
    """Upload layers and the layers.json index to Cloudflare R2 (reads R2_* env vars)."""
    data_root = Path(root or os.environ.get("CLIMA_NQN_DATA") or DEFAULT_DATA_ROOT)
    # A missing root would publish an empty layers.json over the live catalog.
    if not data_root.is_dir():
        typer.echo(f"data root not found: {data_root}", err=True)
        raise typer.Exit(1)
    if dry_run:
        uploads = plan_uploads(data_root, prefix)
        for u in uploads:
            typer.echo(f"{u.key}  {u.size} B  {u.content_type}")
        total = sum(u.size for u in uploads)
        typer.echo(f"{len(uploads)} objects, {total / 1e6:.2f} MB (dry run)")
        return
    try:
        cfg = resolve_credentials(os.environ)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    client = make_client(cfg["R2_ACCOUNT_ID"], cfg["R2_ACCESS_KEY_ID"], cfg["R2_SECRET_ACCESS_KEY"])
    count, total = publish_layers(data_root, client, cfg["R2_BUCKET"], prefix)
    typer.echo(f"{count} objects, {total / 1e6:.2f} MB -> bucket {cfg['R2_BUCKET']}")

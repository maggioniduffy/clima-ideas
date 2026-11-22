"""``hindcast analogs-*`` command bodies (F5.5); registered in ``cli.py``."""

from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.io import era5
from clima_nqn.stages.hindcast import analogs as an


def analogs_library(
    out: Annotated[
        Path,
        typer.Option(help="Per-year stores directory (fetch) or the combined zarr (--combine)."),
    ],
    year: Annotated[int | None, typer.Option(help="Year to fetch (1980-2025).")] = None,
    combine: Annotated[
        bool, typer.Option("--combine", help="Combine <year>.zarr stores from --src.")
    ] = False,
    src: Annotated[
        Path | None, typer.Option(help="With --combine: directory with <year>.zarr stores.")
    ] = None,
    workers: Annotated[
        int, typer.Option(help="Concurrent ARCO chunk reads.")
    ] = era5.DEFAULT_WORKERS,
    months: Annotated[str, typer.Option(help='Months to fetch, e.g. "1-12" or "3".')] = "1-12",
) -> None:
    """Daily IVT library (mean of 00/06/12/18 UTC viwve, viwvn): fetch one year or combine the years."""
    if combine:
        if src is None:
            raise typer.BadParameter("--combine needs --src")
        an.combine_library(src, out)
        return
    if year is None:
        raise typer.BadParameter("give --year, or --combine --src")
    an.fetch_library_year(
        year, out, workers=workers, months=era5.parse_months(months) if months != "1-12" else None
    )


def analogs_imerg(
    store: Annotated[Path, typer.Option(help="IMERG zarr store: a directory or a .zarr.zip file.")],
    out: Annotated[Path, typer.Option(help="CSV with date and <region>_mm.")] = Path(
        "reports/05/F5.5-imerg.csv"
    ),
) -> None:
    """Daily (UTC) regional mean IMERG rain for the 3 F5.3 regions, from the half-hourly store."""
    import numpy as np
    import xarray as xr
    import zarr

    from clima_nqn.stages.hindcast import riskday as rd

    handle = zarr.storage.ZipStore(store, mode="r") if str(store).endswith(".zip") else store
    ds = xr.open_zarr(handle, consolidated=False)
    lat = np.round(ds["lat"].values.astype("float64"), 3)
    lon = np.round(ds["lon"].values.astype("float64"), 3)
    masks = rd.regions(lat, lon)
    cells = {r: int(m.sum()) for r, m in masks.items()}
    cover = an.box_coverage(
        (float(lat.min()), float(lat.max())), (float(lon.min()), float(lon.max()))
    )
    typer.echo(f"units {ds['precipitation'].attrs.get('units')}, cells per region {cells}")
    typer.echo(
        "share of each region inside the IMERG box: "
        + ", ".join(f"{r} {c:.2f}" for r, c in cover.items())
    )
    if min(cells.values()) == 0:
        raise typer.BadParameter(f"a region has no IMERG cell: {cells}")
    keep = [r for r, ok in an.imerg_usable(cover).items() if ok]
    typer.echo(
        f"regions kept (coverage >= {an.MIN_IMERG_COVERAGE}): {keep}; the others are not written"
    )
    masks = {r: masks[r] for r in keep}
    table = an.imerg_daily_regional(
        _TimeSlicer(ds["precipitation"].transpose("time", "lat", "lon")),
        ds["time"].values,
        lat,
        lon,
        masks,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    table.round(3).to_csv(out)
    typer.echo(f"{out}: {len(table)} days, {int(table.notna().all(axis=1).sum())} complete")


class _TimeSlicer:
    """Slice a lazy DataArray on its first axis and return numpy (keeps memory at one chunk)."""

    def __init__(self, da):
        self.da = da

    def __getitem__(self, sl):
        return self.da.isel(time=sl).values


def analogs(
    library: Annotated[
        Path, typer.Option(help="era5-ivt-daily.zarr from `analogs-library --combine`.")
    ],
    events: Annotated[Path, typer.Option(help="F1.3 events.parquet.")],
    out: Annotated[Path, typer.Option(help="Output directory.")],
    imerg: Annotated[Path | None, typer.Option(help="reports/05/F5.5-imerg.csv.")] = None,
    era5_obs: Annotated[Path | None, typer.Option(help="reports/05/F5.3-obs.csv.")] = None,
    n_boot: Annotated[int, typer.Option(help="Bootstrap resamples.")] = an.N_BOOT,
) -> None:
    """Analog search, outcomes and baseline for every event (F5.5): analogs.parquet/json, F5.5.json/md."""
    res = an.run(library, events, imerg, era5_obs, out, n_boot=n_boot)
    typer.echo(
        f"{out}: analogs.parquet, analogs.json, F5.5.json, F5.5.md; {res['n_events']} events"
    )


def analogs_layer(
    src: Annotated[Path, typer.Option(help="analogs.json from `hindcast analogs`.")],
    out: Annotated[
        Path | None, typer.Option(help="Layer directory (default: <data root>/hindcast-analogs).")
    ] = None,
) -> None:
    """Build the hindcast-analogs viewer layer (F5.5)."""
    from clima_nqn.layers import hindcast_analogs as layer

    typer.echo(layer.build(src, out or layer.DEFAULT_OUT))

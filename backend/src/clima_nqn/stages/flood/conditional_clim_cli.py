"""``flow conditional-clim`` command body (F6.9); registered in ``cli.py``."""

from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.stages.flood import conditional_clim as cc


def conditional_clim(
    events: Annotated[Path, typer.Option(help="F1.3 events.parquet (ERA5 ivt_max, deg0l_max).")],
    flow_dir: Annotated[
        Path, typer.Option(help="Directory with <id>.parquet and stations.json (F2.1).")
    ],
    out: Annotated[
        Path, typer.Option(help="Output directory (F6.9.json, F6.9.md).")
    ] = cc.REPORT_DIR,
    ivt_zarr: Annotated[
        Path | None,
        typer.Option(help="gefs-reforecast-ivt.zarr (F5.10); omit to skip GEFS inputs."),
    ] = None,
    cases: Annotated[Path | None, typer.Option(help="cases.parquet of F5.1/F5.10.")] = None,
    n_boot: Annotated[int, typer.Option(help="Bootstrap resamples.")] = cc.N_BOOT,
    seed: Annotated[int, typer.Option(help="Bootstrap seed.")] = cc.SEED,
) -> None:
    """Conditional climatology of high flow by AR-event IVT, 0 degC level and season (F6.9)."""
    res = cc.run(events, flow_dir, ivt_zarr, cases, out, n_boot=n_boot, seed=seed)
    pooled = res["results"]["p95"]["main"]["clim"]["pooled"]
    typer.echo(
        f"{out}: F6.9.json, F6.9.md; pooled BSS vs climatology = {pooled['bss']:.3f} "
        f"[{pooled['ci_lo']:.3f}, {pooled['ci_hi']:.3f}], n = {pooled['n']}"
    )

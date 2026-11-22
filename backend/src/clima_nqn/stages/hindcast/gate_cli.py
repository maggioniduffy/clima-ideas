"""``hindcast gate`` command body (F5.8); registered in ``cli.py``."""

from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.stages.hindcast import gate as gate_mod


def gate(
    forecasts: Annotated[
        Path, typer.Option(help="gefs-reforecast.zarr with every-day cases (F5.3).")
    ],
    obs: Annotated[
        Path,
        typer.Option(help="Regional obs: reports/05/F5.3-obs.csv (or the ERA5 obs zarr of F5.3)."),
    ],
    events: Annotated[Path, typer.Option(help="F1.3 events.parquet.")],
    out: Annotated[Path, typer.Option(help="Output directory (F5.8.json, F5.8.md).")],
    n_boot: Annotated[int, typer.Option(help="Bootstrap resamples.")] = 1000,
    seed: Annotated[int, typer.Option(help="Bootstrap seed.")] = 0,
) -> None:
    """Evidence gate (criteria 1-3) for the risk-day logistic, per region and lead (F5.8)."""
    res = gate_mod.run(forecasts, obs, events, out, n_boot=n_boot, seed=seed)
    summ = gate_mod._verdict_summary(res)
    typer.echo(
        f"{out}: F5.8.json, F5.8.md; pooled test events = {res['n_events_pooled_test']}; "
        f"max contiguous passing lead = {summ}"
    )

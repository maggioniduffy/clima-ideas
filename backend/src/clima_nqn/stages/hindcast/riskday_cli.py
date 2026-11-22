"""``hindcast riskday`` command body (F5.3); registered in ``cli.py`` by the orchestrator."""

from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.stages.hindcast import riskday as riskday_mod


def riskday(
    forecasts: Annotated[
        Path, typer.Option(help="gefs-reforecast.zarr with every-day cases (F5.3).")
    ],
    obs: Annotated[
        Path, typer.Option(help="ERA5 obs zarr with precip_mm and cp_mm (`hindcast observe`).")
    ],
    events: Annotated[Path, typer.Option(help="F1.3 events.parquet.")],
    out: Annotated[Path, typer.Option(help="Output directory (F5.3.json, F5.3.md).")],
    n_boot: Annotated[int, typer.Option(help="Bootstrap resamples.")] = 1000,
    seed: Annotated[int, typer.Option(help="Bootstrap seed.")] = 0,
) -> None:
    """Risk-day classifier (climatology, logistic, LightGBM) and per-mechanism skill (F5.3)."""
    res = riskday_mod.run(forecasts, obs, events, out, n_boot=n_boot, seed=seed)
    typer.echo(
        f"{out}: F5.3.json, F5.3.md; independent test events (pooled) = {res['n_events_pooled_test']}"
    )

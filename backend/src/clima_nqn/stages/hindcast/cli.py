"""``clima-nqn hindcast`` commands (F5.1): cases, fetch (shardable), combine."""

import logging
import os
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from clima_nqn.stages.hindcast import cases as cases_mod
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import store

hindcast_app = typer.Typer(help="Hindcast forecasts for AR events and control days (F5.1).")


@hindcast_app.callback()
def main() -> None:
    """Hindcast forecasts for AR events and control days (F5.1)."""


def _model(name: str) -> fc.ModelSpec:
    if name not in fc.MODELS:
        raise typer.BadParameter(f"model must be one of {', '.join(fc.MODELS)}")
    return fc.MODELS[name]


@hindcast_app.command("cases")
def make_cases(
    events: Annotated[Path, typer.Option(help="F1.3 events.parquet.")],
    out: Annotated[Path, typer.Option(help="Output cases.parquet.")] = Path("cases.parquet"),
    seed: Annotated[int, typer.Option(help="Seed for the control draw.")] = cases_mod.DEFAULT_SEED,
) -> None:
    """Event cases (day of IVT maximum) and seeded control days without AR events within 3 days."""
    cases = cases_mod.build_cases(pd.read_parquet(events), seed)
    counts = cases_mod.write_cases(cases, out, seed, source=str(events))
    typer.echo(f"{out}: {counts}")


@hindcast_app.command("fetch")
def fetch(
    model: Annotated[str, typer.Option(help=f"One of {', '.join(fc.MODELS)}.")],
    cases: Annotated[Path, typer.Option(help="cases.parquet from `hindcast cases`.")],
    out: Annotated[Path, typer.Option(help="Output directory for the shard store.")],
    shard: Annotated[str, typer.Option(help="i/n: shard i (1-based) of n.")] = "1/1",
    workers: Annotated[int, typer.Option(help="Threads for byte-range GETs.")] = 16,
    leads: Annotated[str | None, typer.Option(help="Comma-separated leads, default 1..10.")] = None,
    max_cases: Annotated[
        int | None, typer.Option(help="Smoke test: only the first N cases.")
    ] = None,
    kind: Annotated[
        str | None, typer.Option(help="Smoke test: only event or control cases.")
    ] = None,
) -> None:
    """Fetch the model's forecasts for this shard's cases; resumes and skips finished cases."""
    spec = _model(model)
    try:
        i, n = fc.parse_shard(shard)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    lead_list = tuple(int(x) for x in leads.split(",")) if leads else fc.LEADS
    table = fc.eligible_cases(cases_mod.read_cases(cases), spec)
    if kind:
        table = table[table["kind"] == kind].reset_index(drop=True)
    table = table.iloc[: max_cases if max_cases else None]
    mine = table.iloc[i - 1 :: n].reset_index(drop=True)
    logging.basicConfig(level=logging.WARNING)  # httpx logs every request at INFO
    fetcher = fc.HttpFetcher()
    path = store.shard_path(out, model, i, n)
    res = store.fetch_shard(spec, mine, fetcher, path, lead_list, workers, log_fn=typer.echo)
    typer.echo(f"{path}: {res}; {fetcher.requests} requests, {fetcher.bytes / 1e6:.1f} MB")
    if res["n_error"]:
        typer.echo(f"WARNING: {res['n_error']} entries failed after retries; rerun to retry them")


@hindcast_app.command("combine")
def combine(
    model: Annotated[str, typer.Option(help=f"One of {', '.join(fc.MODELS)}.")],
    in_dir: Annotated[Path, typer.Option("--in", help="Directory with the shard stores.")],
    out: Annotated[Path, typer.Option(help="Output directory; writes <model>.zarr.")],
    allow_partial: Annotated[bool, typer.Option(help="Accept missing shards / pending.")] = False,
) -> None:
    """Merge the shards of a model into ``<out>/<model>.zarr``."""
    spec = _model(model)
    try:
        ds = store.combine_shards(
            spec, in_dir, out / f"{model}.zarr", allow_partial, os.environ.get("GITHUB_RUN_ID", "")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"{out / (model + '.zarr')}: {dict(ds.sizes)}; {ds.attrs}")

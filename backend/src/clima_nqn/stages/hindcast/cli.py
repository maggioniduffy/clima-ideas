"""``clima-nqn hindcast`` commands (F5.1): cases, fetch (shardable), combine."""

import json
import logging
import os
from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
import typer

from clima_nqn.stages.hindcast import cases as cases_mod
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import observe as observe_mod
from clima_nqn.stages.hindcast import store
from clima_nqn.stages.hindcast import verify as verify_mod

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


@hindcast_app.command("observe")
def observe(
    cases: Annotated[Path, typer.Option(help="cases.parquet from `hindcast cases`.")],
    out: Annotated[Path, typer.Option(help="Output era5-obs.zarr.")],
    workers: Annotated[int, typer.Option(help="Threads for ERA5 chunk reads.")] = 64,
    max_days: Annotated[
        int | None, typer.Option(help="Smoke test: only the first N dates.")
    ] = None,
    csv: Annotated[Path | None, typer.Option(help="Also write date,box_mean_mm here.")] = None,
) -> None:
    """ERA5 daily precipitation (mm) for the valid dates inside any model's period (F5.2)."""
    dates = observe_mod.eligible_dates(cases_mod.read_cases(cases))
    if max_days:
        dates = dates[:max_days]
    typer.echo(f"{len(dates)} dates")
    ds = observe_mod.observed_days(dates, workers=workers, log_fn=typer.echo)
    observe_mod.write_obs(ds, out)
    if csv:
        box = verify_mod.box_mean(ds["precip_mm"]).to_series()
        csv.parent.mkdir(parents=True, exist_ok=True)
        box.rename("box_mean_mm").rename_axis("date").round(4).to_csv(csv)
    typer.echo(f"{out}: {dict(ds.sizes)}; era5t={ds.attrs['era5t']}")


def _clean(value):
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


@hindcast_app.command("verify")
def verify(
    forecasts: Annotated[Path, typer.Option(help="Directory with <model>.zarr from F5.1.")],
    obs: Annotated[Path, typer.Option(help="era5-obs.zarr from `hindcast observe`.")],
    out: Annotated[Path, typer.Option(help="Output directory (F5.2.json, F5.2.md).")],
    models: Annotated[str, typer.Option(help="Comma-separated models.")] = (
        "gefs-reforecast,ifs,aifs"
    ),
    n_boot: Annotated[int, typer.Option(help="Bootstrap resamples.")] = 1000,
    seed: Annotated[int, typer.Option(help="Bootstrap seed.")] = 0,
) -> None:
    """Verify the forecasts against ERA5 per lead: skill, contingency, CRPS, bootstrap CIs (F5.2)."""
    thresholds, main = (5.0, 1.0, 10.0), 5.0
    obs_ds = observe_mod.read_obs(obs)
    obs_box = verify_mod.box_mean(obs_ds["precip_mm"]).to_series()
    frames, info = [], {}
    for name in (m.strip() for m in models.split(",") if m.strip()):
        path = forecasts / f"{name}.zarr"
        if not path.exists():
            typer.echo(f"WARNING: {path} missing, skipped")
            continue
        ds = store.read_store(path)
        kinds = verify_mod.str_values(ds["kind"])
        info[name] = {
            "source": ds.attrs.get("source", ""),
            "period": ds.attrs.get("period", ""),
            "n_event": int((kinds == "event").sum()),
            "n_control": int((kinds == "control").sum()),
        }
        frames.append(
            verify_mod.verify_model(
                ds, obs_box, thresholds, main, n_boot, seed, name, obs_ds["precip_mm"]
            )
        )
        typer.echo(f"{name}: verified")
    if not frames:
        raise typer.BadParameter(f"no <model>.zarr found in {forecasts}")
    df = pd.concat(frames, ignore_index=True)
    horizons = {thr: verify_mod.useful_horizon(df, thr) for thr in thresholds}
    meta = {
        "main": main,
        "thresholds": list(thresholds),
        "n_boot": n_boot,
        "seed": seed,
        "obs_source": obs_ds.attrs.get("source", ""),
        "obs_window": obs_ds.attrs.get("window", ""),
        "obs_note": f"{obs_ds.sizes['date']} fechas; ERA5T: {obs_ds.attrs.get('era5t')}",
        "models": info,
    }
    out.mkdir(parents=True, exist_ok=True)
    records = [{k: _clean(v) for k, v in r.items()} for r in df.to_dict("records")]
    payload = {
        "records": records,
        "horizons": {str(k): v for k, v in horizons.items()},
        "meta": meta,
    }
    (out / "F5.2.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    (out / "F5.2.md").write_text(verify_mod.render_md(df, horizons, meta))
    typer.echo(f"{out / 'F5.2.md'}: {len(df)} records")

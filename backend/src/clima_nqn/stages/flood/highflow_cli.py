"""``flow highflow`` and ``flow highflow-fetch-ops`` command bodies (F6.7); registered in ``cli.py``."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from clima_nqn.io import camels_cl, flow, forcing
from clima_nqn.stages.flood import highflow as hf
from clima_nqn.stages.flood import highflow_data as hd
from clima_nqn.stages.flood import lstm as flood_lstm

REFORECAST_ZARR = Path("data/f53-alldays/gefs-reforecast.zarr")


def _forcing_last(forcing_path: Path) -> pd.Timestamp:
    f = forcing.read_forcing(forcing_path)
    return pd.Timestamp(f.loc[f["precip_mm"].notna(), "date"].max())


def _ops_floods(flow_dir: Path, forcing_path: Path, stations: list[int]) -> pd.DataFrame:
    """Large annual maxima whose whole window is in the operational era and inside the forcing."""
    last = _forcing_last(forcing_path)
    everything = set(pd.date_range(hd.OPS_FIRST_INIT, last))
    frames = [
        hd.station_floods(flow.read_flow(flow_dir / f"{sid}.parquet"), sid, last, everything)
        for sid in stations
    ]
    fl = pd.concat(frames, ignore_index=True)
    return fl[fl["large"] & (fl["source"] == "operational")].reset_index(drop=True)


def fetch_ops(
    peak_from: Annotated[
        str, typer.Option(help="Only floods with peak >= this date (YYYY-MM-DD).")
    ] = "",
    peak_to: Annotated[
        str, typer.Option(help="Only floods with peak <= this date (YYYY-MM-DD).")
    ] = "",
    station: Annotated[
        list[int] | None, typer.Option(help="Station (repeatable); default all.")
    ] = None,
    forcing_path: Annotated[Path, typer.Option("--forcing", help="Forcing Parquet.")] = Path(
        "data/f25-forcing/forcing.parquet"
    ),
    flow_dir: Annotated[Path, typer.Option(help="Daily flow Parquets.")] = Path("data/f25-flow"),
    out_dir: Annotated[Path, typer.Option(help="Cache directory.")] = hd.OPS_DIR,
    workers: Annotated[int, typer.Option(help="Concurrent downloads per init.")] = 16,
    retry_missing: Annotated[bool, typer.Option(help="Redo inits that recorded errors.")] = False,
    refresh: Annotated[bool, typer.Option(help="Download again even if cached.")] = False,
    dry_run: Annotated[bool, typer.Option(help="List the windows and exit.")] = False,
) -> None:
    """Download the operational GEFS 0.25 deg windows (peak-15..peak+15) of the 2020-2025 floods (F6.7)."""
    fl = _ops_floods(flow_dir, forcing_path, list(station or hd.STATIONS))
    if peak_from:
        fl = fl[fl["peak_date"] >= pd.Timestamp(peak_from)]
    if peak_to:
        fl = fl[fl["peak_date"] <= pd.Timestamp(peak_to)]
    inits = hd.flood_inits(fl["peak_date"])
    for r in fl.itertuples():
        typer.echo(f"flood {r.station_id} {r.peak_date:%Y-%m-%d} {r.q_peak_m3s:.0f} m3/s")
    typer.echo(f"{len(fl)} floods, {len(inits)} init days x 5 members x 40 steps")
    if dry_run:
        return
    n_err = n_miss = 0
    t0 = time.time()
    for i, day in enumerate(inits, 1):
        side = hd.fetch_init(
            day, out_dir, workers=workers, refresh=refresh, retry_missing=retry_missing
        )
        n_miss += side["n_missing"]
        n_err += side["n_missing_errors"]
        typer.echo(
            f"[{i}/{len(inits)}] {day:%Y-%m-%d}: {side['status']}, missing {side['n_missing']} "
            f"(errors {side['n_missing_errors']}) ({time.time() - t0:.0f} s)"
        )
    typer.echo(f"done: {len(inits)} inits -> {out_dir}; missing files {n_miss} (errors {n_err})")


def highflow(
    fold: Annotated[
        list[int] | None, typer.Option(help="Hydrological year (repeatable); default all.")
    ] = None,
    seeds: Annotated[int, typer.Option(help="LSTM ensemble size (seeds 0..N-1).")] = 5,
    epochs: Annotated[int, typer.Option(help="Fine-tuning epochs per fold (max).")] = 30,
    pretrain_epochs: Annotated[int, typer.Option(help="CAMELS-CL pretraining epochs (once).")] = 10,
    samples_per_epoch: Annotated[int, typer.Option(help="Windows sampled per epoch.")] = 20000,
    gr4j_seeds: Annotated[
        int, typer.Option(help="GR4J calibration seeds (0..N-1, best kept).")
    ] = 3,
    maxiter: Annotated[int, typer.Option(help="GR4J differential-evolution generations.")] = 50,
    lstm: Annotated[bool, typer.Option("--lstm/--no-lstm", help="Include the LSTM.")] = True,
    pretrain: Annotated[
        bool, typer.Option("--pretrain/--no-pretrain", help="CAMELS-CL pretraining.")
    ] = True,
    report_only: Annotated[
        bool, typer.Option(help="Do not run folds; aggregate the saved ones.")
    ] = False,
    force: Annotated[bool, typer.Option(help="Rerun folds that already have results.")] = False,
    n_boot: Annotated[int, typer.Option(help="Bootstrap resamples (fixed seed).")] = hf.N_BOOT,
    work_dir: Annotated[
        Path, typer.Option(help="Fold results and pretrained weights.")
    ] = hf.WORK_DIR,
    report_dir: Annotated[
        Path, typer.Option(help="Where F6.7.md/json are written.")
    ] = hf.REPORT_DIR,
    forcing_path: Annotated[Path, typer.Option("--forcing", help="Forcing Parquet.")] = Path(
        "data/f25-forcing/forcing.parquet"
    ),
    flow_dir: Annotated[Path, typer.Option(help="Daily flow Parquets.")] = Path("data/f25-flow"),
    reforecast: Annotated[
        Path, typer.Option(help="gefs-reforecast.zarr (F5.3).")
    ] = REFORECAST_ZARR,
    ops_dir: Annotated[Path, typer.Option(help="Operational GEFS cache.")] = hd.OPS_DIR,
    camels_dir: Annotated[Path, typer.Option(help="CAMELS-CL zips.")] = camels_cl.DEFAULT_DIR,
    camels_cache: Annotated[
        Path, typer.Option(help="Tidy CAMELS-CL Parquet.")
    ] = camels_cl.DEFAULT_OUT,
    no_report: Annotated[bool, typer.Option(help="Skip writing the report.")] = False,
    pretrain_only: Annotated[
        bool, typer.Option(help="Only pretrain the --seed-list seeds (shard of the pretraining).")
    ] = False,
    train_only: Annotated[
        bool,
        typer.Option(
            help="Only fine-tune --fold Y for --seed-list and save the weights; no scoring."
        ),
    ] = False,
    seed_list: Annotated[
        list[int] | None,
        typer.Option(help="LSTM seed (repeatable) for --pretrain-only/--train-only."),
    ] = None,
    no_retrain: Annotated[
        bool, typer.Option(help="Fail if a fold lacks saved LSTM weights instead of training them.")
    ] = False,
    list_folds: Annotated[bool, typer.Option(help="Print the fold years (JSON) and exit.")] = False,
) -> None:
    """Leave-one-flood-out high-flow test (F6.7): folds, scores and reports/06/F6.7.{md,json}.

    Sharding: ``--pretrain-only --seed-list k`` (once per seed), ``--train-only --fold Y --seed-list k``
    (per fold and seed), then a plain ``flow highflow`` (``--no-retrain``) reuses the saved weights.
    """
    rc = hf.RunConfig(
        seeds=seeds, epochs=epochs, pretrain_epochs=pretrain_epochs,
        samples_per_epoch=samples_per_epoch, gr4j_seeds=tuple(range(gr4j_seeds)),
        maxiter=maxiter, use_lstm=lstm,
    )  # fmt: skip
    if (pretrain_only or train_only) and not (lstm and seed_list):
        raise typer.BadParameter("--pretrain-only/--train-only need the LSTM and --seed-list")
    if pretrain_only and train_only:
        raise typer.BadParameter("--pretrain-only and --train-only are exclusive")
    if seed_list and not set(seed_list) <= set(range(seeds)):
        raise typer.BadParameter(f"--seed-list must be within 0..{seeds - 1}")
    if train_only and (not fold or len(fold) != 1):
        raise typer.BadParameter("--train-only needs exactly one --fold")
    if lstm and not list_folds:
        try:
            flood_lstm.import_torch()
        except flood_lstm.TorchMissing as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from e
    if pretrain_only:
        table, attrs = camels_cl.load_camels(camels_dir, camels_cache)
        camels = flood_lstm.camels_basins(table, attrs, camels_cl.select_basins(table))
        hf.pretrain_once(
            camels, rc, work_dir / "pretrain", progress=typer.echo, seed_list=seed_list
        )
        return
    if train_only:
        try:
            stations, _ = hf.load_stations(forcing_path, flow_dir, work_dir)
            pre = hf.load_pretrained(rc, work_dir / "pretrain") if pretrain else None
        except (FileNotFoundError, ValueError, KeyError) as e:
            raise typer.BadParameter(str(e)) from e
        t0 = time.time()
        hf.train_lstm_fold(
            stations, fold[0], rc, pre, typer.echo, out_dir=work_dir / f"fold-{fold[0]}",
            seed_list=seed_list, train_only=True,
        )  # fmt: skip
        typer.echo(f"fold {fold[0]} seeds {seed_list}: {time.time() - t0:.0f} s")
        return
    try:
        stations, info = hf.load_stations(forcing_path, flow_dir, work_dir)
        floods, tables = hf.plan_floods(stations, reforecast, ops_dir)
    except (FileNotFoundError, ValueError, KeyError) as e:
        raise typer.BadParameter(str(e)) from e
    inc = floods[floods["included"]]
    years = sorted(int(y) for y in inc["hydro_year"].unique())
    if fold:
        years = [y for y in years if y in set(fold)]
    if list_folds:
        typer.echo(json.dumps(years))
        return
    typer.echo(
        f"floods: {int(floods['large'].sum())} large, {len(inc)} with forecasts; folds {years}"
    )
    pre = None
    pretrain_note = "no usado (LSTM omitido)" if not lstm else "no usado: LSTM entrenado desde cero"
    if lstm and pretrain:
        try:
            table, attrs = camels_cl.load_camels(camels_dir, camels_cache)
            ids = camels_cl.select_basins(table)
            pretrain_note = (
                f"CAMELS-CL (Alvarez-Garreton et al., 2018, HESS 22, 5817–5846; PANGAEA DOI 10.1594/PANGAEA.894885; "
                f"CC-BY-4.0), {len(ids)} cuencas chilenas con al menos 10 años de caudal, hasta {table['date'].max():%Y-%m-%d}; "
                "forzante CR2MET, distinto del ERA5 de Neuquén; preentrenado una sola vez, sin datos de Neuquén."
            )
            if not report_only:
                camels = flood_lstm.camels_basins(table, attrs, ids)
                pre = hf.pretrain_once(camels, rc, work_dir / "pretrain", progress=typer.echo)
        except FileNotFoundError as e:
            typer.echo(f"CAMELS-CL no disponible ({e}); el LSTM se entrena desde cero.", err=True)
            pretrain_note = (
                "CAMELS-CL no se pudo leer: LSTM entrenado desde cero con normalización por fold."
            )
    if not report_only:
        for year in years:
            out = work_dir / f"fold-{year}"
            if (out / "fold.json").is_file() and not force:
                typer.echo(f"fold {year}: ya hecho, se omite")
                continue
            t0 = time.time()
            hf.run_fold(
                year,
                inc[inc["hydro_year"] == year],
                stations,
                tables,
                work_dir,
                rc,
                pre,
                typer.echo,
                allow_train=not no_retrain,
            )
            typer.echo(f"fold {year}: {time.time() - t0:.0f} s -> {out}")
    done = [
        work_dir / f"fold-{y}" for y in years if (work_dir / f"fold-{y}" / "fold.json").is_file()
    ]
    if no_report or not done:
        return
    ctx = {
        "forcing_period": info.get("12004", {}).get("forcing_period", ""),
        "pretrain": pretrain_note,
        "n_boot": n_boot,
        "elevation_filled": info.get("elevation_filled_from_F2.5-bands"),
        "seeds": seeds,
        "lstm": lstm,
    }
    res = hf.aggregate(floods, done, ctx, n_boot)
    md, js = hf.write_report(res, report_dir)
    typer.echo(f"report -> {md}, {js}")

"""``clima-nqn seasonal ...`` commands (F6.2)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from clima_nqn.stages.seasonal import fetch as fetch_mod

seasonal_app = typer.Typer(help="Seasonal tercile model (F6.2, experimental).")


@seasonal_app.command("fetch-state")
def fetch_state(
    out: Annotated[Path, typer.Option(help="Output Parquet.")] = fetch_mod.STATE_PATH,
    first: Annotated[str, typer.Option(help="First issue date.")] = "1980-01-01",
    last: Annotated[str, typer.Option(help="Last issue date.")] = "2026-06-01",
    workers: Annotated[int, typer.Option()] = 16,
) -> None:
    """Fetch ERA5 snow and soil water at issue - 5 d (idempotent); logs to data/seasonal/fetch.log."""
    out.parent.mkdir(parents=True, exist_ok=True)
    logfile = (out.parent / "fetch.log").open("a")

    def log(msg: str) -> None:
        print(msg, file=logfile, flush=True)
        print(msg, file=sys.stderr, flush=True)

    fetch_mod.fetch_state(out, first, last, workers=workers, log=log)


@seasonal_app.command("validate")
def validate_cmd(
    scheme: Annotated[str, typer.Option(help="outer | control | both")] = "both",
    target: Annotated[
        list[str] | None, typer.Option(help="Target (repeatable); default all.")
    ] = None,
    n_jobs: Annotated[int, typer.Option(help="Parallel folds.")] = 2,
    force: Annotated[bool, typer.Option(help="Recompute cached predictions.")] = False,
) -> None:
    """Run the nested validation; predictions are cached in data/seasonal/preds/ (idempotent)."""
    from clima_nqn.stages.seasonal import data, validate

    inp = data.load_inputs()
    targets = target or [*data.MAIN_TARGETS, *data.SENSITIVITY_TARGETS]
    schemes = ["outer", "control"] if scheme == "both" else [scheme]
    for t in targets:
        for s in schemes:
            validate.run_scheme(s, t, inp, n_jobs=n_jobs, force=force, log=typer.echo)


@seasonal_app.command("report")
def report_cmd(
    json_out: Annotated[Path, typer.Option(help="F6.2.json path.")] = Path(
        "../reports/06/F6.2.json"
    ),
    md_out: Annotated[Path, typer.Option(help="F6.2.md path.")] = Path("../reports/06/F6.2.md"),
    final: Annotated[bool, typer.Option(help="Fit and save final models for winners.")] = True,
) -> None:
    """Score the cached predictions, write F6.2.json and F6.2.md, and save final models if any beats clim."""

    import pandas as pd

    from clima_nqn.stages.seasonal import data, report, score, summary
    from clima_nqn.stages.seasonal import final as final_mod
    from clima_nqn.stages.seasonal.fetch import STATE_PATH

    inp = data.load_inputs()
    js = summary.build(inp.oni)
    state = pd.read_parquet(STATE_PATH)
    meta = {
        "n_boot": score.N_BOOT,
        "seed": score.SEED,
        "input_hashes": inp.hashes,
        "state_period": f"{state['issue_date'].min():%Y-%m} a {state['issue_date'].max():%Y-%m} (emisión; muestra a emisión − 5 d)",
        "sources": {
            "state": "ERA5 (Copernicus C3S) via ARCO-ERA5, 0.25 deg, CC-BY 4.0; not ERA5-Land",
            "rain": "F2.5 forcing.parquet (ERA5 box means, sin verificar)",
            "ar": "F1.3 events.parquet (TECA BARD 6.0.0), 1980-01-01/2025-12-31",
            "flow": "F2.5 SNIH daily flow, monthly mean valid with >= 25 days",
            "oni": "NOAA CPC ONI (revised series)",
        },
    }
    winners: dict[str, str] = {}
    for t in data.MAIN_TARGETS:
        vt = [v for v in js["verdicts"] if v["target"] == t]
        wins = {v["model"] for v in vt if v["beats_climatology"] and v["lead"] != "all"}
        allr = {
            v["model"]: v["rpss_vs_clim"] for v in vt if v["lead"] == "all" and v["model"] in wins
        }
        if allr:
            winners[t] = max(allr, key=lambda m: allr[m])
    saved = []
    if winners and final:
        for t, kind in winners.items():
            saved.append(final_mod.fit_final(inp, t, kind))
        meta["final_note"] = (
            "Al menos una variable y anticipación supera a la climatología; modelos guardados en "
            "`backend/models/seasonal-v1/` (entrenados con todos los años): "
            + "; ".join(
                f"{s['target']} ({s['kind']}, conjunto {s['feature_set']}, {s['config']}, hash de entradas {s['input_hash']})"
                for s in saved
            )
            + ". La emisión al registro es un paso posterior; sigue siendo Experimental."
        )
    else:
        meta["final_note"] = (
            "Ninguna variable ni anticipación supera a la climatología con IC 95 % que excluya 0: no se guarda ningún modelo; "
            "solo se emitirán baselines."
        )
    js["meta"] = meta
    js["final_models"] = saved
    js["beats_climatology"] = [
        {k: v[k] for k in ("target", "lead", "model", "beats_climatology")} for v in js["verdicts"]
    ]
    js = summary.sanitize(js)
    summary.write_json(js, json_out)
    report.write_markdown(js, meta, md_out)
    typer.echo(f"{json_out} {md_out}; winners: {winners or 'none'}")

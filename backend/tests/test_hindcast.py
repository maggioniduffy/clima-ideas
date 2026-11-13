import json

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import flow
from clima_nqn.layers import flood_stations as fs
from clima_nqn.layers.manifest import load_manifest
from clima_nqn.stages.flood import hindcast, lstm

AREA = 1000.0
SID = "12004"
FORCED = "2023-06-26"


def synth_basin(sid=SID):
    dates = pd.date_range("2000-01-01", "2025-12-31", freq="D")
    n = len(dates)
    rng = np.random.default_rng(0)
    doy = dates.day_of_year.to_numpy()
    precip = rng.gamma(0.6, 6.0, n) * (rng.random(n) < 0.4)
    tmean = 8 + 8 * np.cos(2 * np.pi * doy / 365.25) + rng.normal(0, 1, n)
    pet = np.clip(1 + 0.1 * tmean, 0, None)
    q = 0.5 * precip + 0.3 * np.r_[0.0, precip[:-1]] + 0.5  # mm/d
    # one clear annual maximum per hydrological year, on a known day (June 26 of the year)
    for y in range(2000, 2026):
        d = dates.get_loc(pd.Timestamp(f"{y}-06-26"))
        q[d] += 20 + (y - 2000) + (50 if y == 2023 else 0)
        q[d] += 8 if y in (2016, 2019) else 0
    x = np.stack([precip, tmean, tmean - 5, tmean + 5, pet], axis=1)
    return lstm.Basin(
        id=sid, dates=dates, x=x, q=q,
        static=np.array([np.log(AREA), 1500.0, -38.0]), group="neuquen",
    )  # fmt: skip


def flow_frame(basin):
    q_m3s = basin.q * AREA / lstm.M3S_TO_MM_DAY
    return pd.DataFrame({"date": basin.dates, "q_m3s": q_m3s, "qualifier": "", "validated": True})


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    pytest.importorskip("torch")
    root = tmp_path_factory.mktemp("hindcast")
    basin = synth_basin()
    df = flow_frame(basin)
    flow_dir = root / "flow"
    flow.write_flow(df, flow_dir / f"{SID}.parquet")
    meta = {"id": int(SID), "name": "Natural", "river": "Río X", "lat": -38.5, "lon": -69.4,
            "area_km2": AREA, "hydro_year_start_month": 4, "alta_year": 1990, "note": "",
            "first_date": None, "last_date": None, "first_valid_date": None,
            "last_valid_date": None}  # fmt: skip
    (flow_dir / "stations.json").write_text(
        json.dumps({"source": "s", "url": "u", "fetched": "2026-11-09", "stations": [meta]}),
        encoding="utf-8",
    )
    cfg = lstm.TrainConfig(
        mode="forecast", hidden=8, dropout=0.0, seq_len=12, batch_size=64, samples_per_epoch=256,
        epochs=2, patience=100, lr=0.01, seeds=(0, 1), pretrain=False,
    )  # fmt: skip
    info = {"run_name": "fc-tiny", "neuquen": {SID: {"area_km2": AREA, "notes": []}},
            "pretrain": {"used": False}}  # fmt: skip
    run = lstm.train_run([basin], None, cfg, info=info)
    run_dir = lstm.save_run(run, root / "runs" / "fc-tiny")
    return {"root": root, "basin": basin, "df": df, "run": run, "run_dir": run_dir,
            "flow_dir": flow_dir}  # fmt: skip


def test_event_selection_test_years_top3_and_forced(world):
    ev = hindcast.select_events(world["df"], (2014, 2025), SID)
    years = set(ev["hydro_year"])
    assert years <= set(range(2014, 2026))
    assert len(ev) == hindcast.TOP_EVENTS
    assert pd.Timestamp(FORCED) in set(ev["date"])
    assert ev["date"].is_monotonic_increasing
    # another station: no forced event, the three largest peaks of the test years
    other = hindcast.select_events(world["df"], (2014, 2025), "99999")
    assert len(other) == 3 and set(other["hydro_year"]) <= set(range(2014, 2026))


def test_forced_event_replaces_the_smallest_when_not_in_top3(world):
    df = world["df"].copy()
    # make 2023 small: it only enters through the forced rule
    in_2023 = (df["date"] >= "2023-04-01") & (df["date"] < "2024-04-01")
    df.loc[in_2023, "q_m3s"] = 0.5
    df.loc[df["date"] == pd.Timestamp(FORCED), "q_m3s"] = 1.0
    plain = hindcast.select_events(df, (2014, 2025), "99999")
    forced = hindcast.select_events(df, (2014, 2025), SID)
    assert pd.Timestamp(FORCED) not in set(plain["date"]) and len(forced) == 3
    assert pd.Timestamp(FORCED) in set(forced["date"])
    # a forced date that is not an annual maximum is not invented
    df.loc[df["date"] == pd.Timestamp(FORCED), "q_m3s"] = np.nan
    assert pd.Timestamp(FORCED) not in set(hindcast.select_events(df, (2014, 2025), SID)["date"])


def test_payload_grid_band_ordering_and_conversion(world):
    run, basin = world["run"], world["basin"]
    payloads = hindcast.build_events(run, [basin], world["flow_dir"])
    p = payloads[SID]
    assert p["station_id"] == SID and len(p["events"]) == 3
    area = p["meta"]["area_km2"]
    assert area == AREA
    for e in p["events"]:
        assert (
            e["obs"]["start"]
            == (pd.Timestamp(e["peak_date"]) - pd.Timedelta(days=14)).date().isoformat()
        )
        assert len(e["obs"]["q"]) == 22
        assert [i["days_before_peak"] for i in e["issues"]] == list(range(7, -1, -1))
        for i in e["issues"]:
            assert len(i["median"]) == len(i["lo"]) == len(i["hi"]) == 7
            assert all(
                lo <= m <= hi for lo, m, hi in zip(i["lo"], i["median"], i["hi"], strict=True)
            )
            assert i["persistence"] is not None
    # m3/s round trip: the stored median equals the model's mm/d times area / 86.4
    e = p["events"][-1]
    day = pd.Timestamp(e["issues"][-1]["issue_date"])
    ds = lstm.Dataset.from_basins([basin], "default", run.norm)
    end = hindcast.issue_ends(ds, 0, pd.DatetimeIndex([day]), run.config)
    mm = lstm.ensemble_median(lstm.predict(run, ds, end, 7))[0]
    np.testing.assert_allclose(e["issues"][-1]["median"], mm * AREA / lstm.M3S_TO_MM_DAY, atol=0.06)
    # persistence is the observed flow on the issue day
    obs_day = world["df"].set_index("date")["q_m3s"][day]
    assert e["issues"][-1]["persistence"] == pytest.approx(obs_day, abs=0.06)


def test_meta_and_caveat(world):
    p = hindcast.build_events(world["run"], [world["basin"]], world["flow_dir"])[SID]
    m = p["meta"]
    assert m["caveat"] == (
        "Pronóstico retrospectivo con meteorología observada (ERA5), no pronóstico operativo. "
        "Experimental, no es una alerta."
    )
    assert m["forcing"] == "ERA5 observada, no pronóstico"
    assert m["run_name"] == "fc-tiny" and m["mode"] == "forecast" and m["seeds"] == [0, 1]
    assert m["split"] == "default" and m["test_years"] == [2014, 2025]
    assert m["area_note"] is None and m["pretrain"] is None
    assert hindcast.AREA_NOTES["12012"] == "área SNIH igual a la de Chos Malal, sin verificar"


def test_sim_run_is_rejected(world):
    run = world["run"]
    sim = lstm.Run(config=lstm.TrainConfig(mode="sim"), norm=run.norm)
    with pytest.raises(ValueError, match="forecast"):
        hindcast.build_events(sim, [world["basin"]], world["flow_dir"])


def test_strict_json_and_layer_registration(world, tmp_path):
    p = hindcast.build_events(world["run"], [world["basin"]], world["flow_dir"])
    bad = json.loads(json.dumps(p))
    bad[SID]["events"][0]["peak_q"] = float("nan")
    with pytest.raises(ValueError):
        hindcast.write_events(bad, tmp_path / "x")
    out = tmp_path / "layer"
    fs.build_layer(world["flow_dir"], tmp_path / "nogev", out)
    assert (out / "stations" / f"{SID}.json").is_file()
    assert "has_events" not in json.loads((out / "stations" / f"{SID}.json").read_text())
    paths = hindcast.write_events(p, out)
    assert paths == [out / "events" / f"{SID}.json"]
    text = paths[0].read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    json.loads(text, parse_constant=lambda c: pytest.fail(c))
    assert json.loads((out / "stations" / f"{SID}.json").read_text())["has_events"] is True
    assert load_manifest(out / "manifest.json").files[-1] == f"events/{SID}.json"
    # rebuilding the layer keeps the events registered
    fs.build_layer(world["flow_dir"], tmp_path / "nogev", out)
    assert f"events/{SID}.json" in load_manifest(out / "manifest.json").files
    assert json.loads((out / "stations" / f"{SID}.json").read_text())["has_events"] is True


def test_cli_lstm_hindcast(world, tmp_path):
    root = world["root"]
    out = tmp_path / "layer"
    # forcing Parquet is not needed: stub the basin builder with the synthetic basin
    from clima_nqn.stages.flood import lstm as lstm_mod

    orig = lstm_mod.neuquen_basins
    lstm_mod.neuquen_basins = lambda *a, **k: ([world["basin"]], {})
    try:
        r = CliRunner().invoke(
            app,
            ["flow", "lstm-hindcast", "--run-name", "fc-tiny", "--out-dir", str(root / "runs"),
             "--flow-dir", str(world["flow_dir"]), "--out", str(out)],
        )  # fmt: skip
    finally:
        lstm_mod.neuquen_basins = orig
    assert r.exit_code == 0, r.output
    assert (out / "events" / f"{SID}.json").is_file()

import json

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import flow
from clima_nqn.layers.manifest import LayerManifest, load_manifest
from clima_nqn.stages.ar import catalog, response


def flow_df(start, end, values=None):
    dates = pd.date_range(start, end, freq="D", name="date")
    q = np.full(len(dates), 10.0) if values is None else values
    return pd.DataFrame({"date": dates, "q_m3s": q, "qualifier": "", "validated": True})


def meta(sid, name, note=""):
    return {"id": sid, "name": name, "river": "Río X", "note": note}


@pytest.fixture
def world(tmp_path):
    flow_dir, layer = tmp_path / "flow", tmp_path / "layer"
    flow_dir.mkdir()
    layer.mkdir()
    # station 1: 10 everywhere, 40 on 2000-03-15, gap on 2000-03-12
    df1 = flow_df("2000-01-01", "2000-12-31")
    df1.loc[df1["date"] == "2000-03-15", "q_m3s"] = 40.0
    df1.loc[df1["date"] == "2000-03-12", "q_m3s"] = np.nan
    # station 2 (regulated): starts after the first event; q_before = 0 for the second
    df2 = flow_df("2000-04-01", "2000-12-31")
    df2.loc[df2["date"] == "2000-07-20", "q_m3s"] = 0.0
    df2.loc[df2["date"] == "2000-07-22", "q_m3s"] = 5.0
    flow.write_flow(df1, flow_dir / "1.parquet")
    flow.write_flow(df2, flow_dir / "2.parquet")
    stations = [meta(1, "Natural"), meta(2, "Regulada", "regulada aguas arriba"), meta(3, "Vacía")]
    (flow_dir / "stations.json").write_text(
        json.dumps({"source": "s", "url": "u", "fetched": "2026-11-09", "stations": stations}),
        encoding="utf-8",
    )
    events = pd.DataFrame(
        {
            "event_id": ["AR-2000-001", "AR-2000-002"],
            "start": pd.to_datetime(["2000-03-10 06:00", "2000-07-21 00:00"]),
            "end": pd.to_datetime(["2000-03-11 00:00", "2000-07-21 03:00"]),  # exclusive end
        }
    )
    events.attrs.update(period="2000-01-01/2000-12-31")
    cat = catalog.write_catalog(
        events.reindex(columns=catalog.COLUMNS), layer.parent / "events.parquet"
    )
    return cat, flow_dir, layer


def test_peak_before_lag_and_window(world):
    cat, flow_dir, layer = world
    res = response.build(cat, flow_dir, layer)
    ev1 = {r["station_id"]: r for r in res["events"]["AR-2000-001"]}
    # event 1 covers only 2000-03-10 (end 00:00 exclusive); window 03-10..03-20; station 2 has no data
    assert set(ev1) == {"1"}
    r = ev1["1"]
    assert (r["q_before"], r["q_peak"], r["peak_date"], r["lag_days"], r["ratio"]) == (
        10.0, 40.0, "2000-03-15", 5, 4.0,
    )  # fmt: skip
    assert r["daily"]["start"] == "2000-03-07"
    # 03-07 .. 03-20 = 14 days, gap on 03-12 is index 5
    assert len(r["daily"]["q"]) == 14 and r["daily"]["q"][5] is None
    assert r["daily"]["q"][8] == 40.0


def test_ratio_null_when_before_is_zero_and_regulated_flag(world):
    cat, flow_dir, layer = world
    res = response.build(cat, flow_dir, layer)
    ev2 = {r["station_id"]: r for r in res["events"]["AR-2000-002"]}
    assert set(ev2) == {"1", "2"}
    assert ev2["2"]["q_before"] == 0.0 and ev2["2"]["ratio"] is None
    assert ev2["2"]["q_peak"] == 10.0 and ev2["2"]["lag_days"] == 0
    by_id = {s["id"]: s for s in res["stations"]}
    assert by_id["2"]["regulated"] is True and by_id["1"]["regulated"] is False
    assert "3" not in by_id  # no Parquet


def test_output_fields_and_wording(world):
    cat, flow_dir, layer = world
    res = response.build(cat, flow_dir, layer)
    assert res["window_days_after"] == 10 and res["context_days_before"] == 3
    assert res["period"] == "2000-01-01/2000-12-31"
    assert res["source"].startswith(flow.SOURCE + " / ")
    assert "coincide con" in res["note"] and "causó" not in res["note"]
    written = json.loads((layer / "responses.json").read_text(encoding="utf-8"))
    assert written == res


def test_manifest_updated_once_and_kept_by_layer(world):
    cat, flow_dir, layer = world
    (layer / "manifest.json").write_text(
        LayerManifest(
            id="ar-events", title="t", kind="events", source="s", period="2000-01-01/2000-12-31",
            license="l", updated_at="2026-01-01T00:00:00Z", files=["events.json"],
        ).model_dump_json(),
        encoding="utf-8",
    )  # fmt: skip
    response.build(cat, flow_dir, layer)
    response.build(cat, flow_dir, layer)
    assert load_manifest(layer / "manifest.json").files == ["events.json", "responses.json"]


def test_cli(world):
    cat, flow_dir, layer = world
    r = CliRunner().invoke(
        app,
        ["ar", "response", "--events", str(cat), "--flow-dir", str(flow_dir), "--out", str(layer)],
    )
    assert r.exit_code == 0, r.output
    assert "2 events, 2 stations, 3 pairs" in r.output
    bad = CliRunner().invoke(app, ["ar", "response", "--events", str(layer / "nope.parquet")])
    assert bad.exit_code != 0

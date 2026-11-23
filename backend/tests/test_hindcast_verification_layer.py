import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from clima_nqn.api.app import create_app
from clima_nqn.layers import hindcast_verification as hv
from clima_nqn.layers.manifest import load_manifest

LATS = np.array([0.0, 60.0], dtype="float64")  # weights cos(0)=1 and cos(60)=0.5
LONS = np.array([-70.0, -69.0], dtype="float64")
LEADS = [1, 2]


def make_ds(model: str, n_member: int) -> xr.Dataset:
    """Two events and one control. Event E1: lat 0 row = 3, lat 60 row = 6 -> weighted mean 4 (+ member offset)."""
    n = 3
    data = np.zeros((n, len(LEADS), n_member, len(LATS), len(LONS)))
    for m in range(n_member):
        data[0, :, m, 0, :] = 3.0 + m
        data[0, :, m, 1, :] = 6.0 + m
    data[1] = 1.0  # E2: flat 1 mm
    data[2] = 50.0  # control: must not appear
    status = np.zeros((n, len(LEADS), n_member), dtype="int8")
    if n_member > 1:
        status[1, 1, 0] = (
            1  # E2, lead 2, member 0 not published -> NaN, excluded from the ensemble stats
        )
        data[1, 1, 0] = np.nan
    status[1, 0, n_member - 1] = 0
    ds = xr.Dataset(
        {
            "precip_mm": (("case", "lead", "member", "lat", "lon"), data),
            "status": (("case", "lead", "member"), status),
        },
        coords={
            "case": ["AR-2001-001", "AR-2001-002", "CTL-2001-0101"],
            "kind": ("case", ["event", "event", "control"]),
            "event_id": ("case", ["AR-2001-001", "AR-2001-002", ""]),
            "valid_date": ("case", pd.to_datetime(["2001-05-02", "2001-04-01", "2001-01-01"])),
            "lead": LEADS,
            "member": np.arange(n_member),
            "lat": LATS,
            "lon": LONS,
        },
        attrs={
            "source": f"{model} falso de prueba",
            "license": "CC0",
            "period": "valid 2001-01-01..2001-12-31",
        },
    )
    return ds


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    root = tmp_path_factory.mktemp("hv")
    fc = root / "f51"
    fc.mkdir()
    for model, n_member in (("gefs-reforecast", 3), ("ifs", 1), ("aifs", 1)):
        make_ds(model, n_member).to_zarr(fc / f"{model}.zarr", consolidated=False)
    rep = root / "reports"
    rep.mkdir()
    pd.DataFrame(
        {"date": ["2001-04-01", "2001-05-02", "2001-01-01"], "box_mean_mm": [2.5, 7.0, 0.1]}
    ).to_csv(rep / "F5.2-obs.csv", index=False)
    rec = []
    for model in hv.MODELS:
        for lead in (1, 2):
            base = {"model": model, "lead": lead, "threshold": None, "n": 5}
            rec += [
                {**base, "kind": "event", "metric": "crpss", "value": 0.5, "lo": 0.1, "hi": 0.8},
                {**base, "kind": "event", "metric": "bias", "value": -1.0, "lo": -2.0, "hi": 0.0},
                {**base, "kind": "event", "metric": "n", "value": 5.0, "lo": None, "hi": None},
                {
                    **base,
                    "kind": "control",
                    "metric": "crpss",
                    "value": 9.0,
                    "lo": None,
                    "hi": None,
                },
            ]
    (rep / "F5.2.json").write_text(json.dumps({"records": rec}))
    summ = [
        {
            "lead": "1",
            "kind": "event",
            "n": 4,
            "mae_ifs": 1.0,
            "mae_aifs": 2.0,
            "diff": 1.0,
            "lo": 0.0,
            "hi": 2.0,
            "bias_ifs": 0.1,
            "bias_aifs": 0.2,
            "wins_aifs": 1,
            "wins_ifs": 2,
            "ties": 1,
            "p_sign": 0.5,
            "verdict": "sin diferencia detectable",
        },
        {
            "lead": "1",
            "kind": "control",
            "n": 4,
            "mae_ifs": 9.0,
            "mae_aifs": 9.0,
            "diff": 0.0,
            "lo": 0.0,
            "hi": 0.0,
            "bias_ifs": 0.0,
            "bias_aifs": 0.0,
            "wins_aifs": 0,
            "wins_ifs": 0,
            "ties": 4,
            "p_sign": 1.0,
            "verdict": "x",
        },
    ]
    (rep / "F5.4.json").write_text(
        json.dumps(
            {"summary": summ, "meta": {"first": "2024-03-03", "last": "2025-11-24", "n_event": 4}}
        )
    )

    def row(lead, status):
        ci = {"value": 0.3, "lo": 0.1, "hi": 0.5}
        pf = {
            "pod": 0.5,
            "far": float("nan"),
            "hits": 1,
            "false_alarms": 0,
            "n_risk_days": 2,
            "thr": 0.5,
        }
        return {
            "n_days": 10,
            "base_rate": 0.05,
            "n_events": 7,
            "n_events_pooled": 9,
            "bss_log_clim": ci,
            "bss_log_markov": ci,
            "bss_log_binary": ci,
            "reliability": [],
            "prob_cap": 0.7,
            "status": status,
            "pod_far": {"p>=0.5": pf, "p>=2base": pf},
            "lgbm": {"shown": False},
        }

    f58 = {
        "quantile": 0.95,
        "thresholds": {"r1": 10.0},
        "n_events_pooled_test": 9,
        "n_events_test": {"r1": 7},
        "regions": {
            "r1": {
                "1": row(1, "pasa hindcast (espera la temporada prospectiva)"),
                "2": row(2, "Experimental"),
            }
        },
        "meta": {"fc_source": "GEFS falso", "fc_period": "2000 … 2019"},
    }
    (rep / "F5.8.json").write_text(json.dumps(f58))
    out = root / "processed" / hv.LAYER_ID
    hv.build(fc, rep, out)
    return out


def load(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_manifest_contract(inputs):
    m = load_manifest(inputs / "manifest.json")
    assert m.id == "hindcast-verification" and m.kind == "series"
    assert m.title == "Verificación retrospectiva de pronósticos"
    assert "ERA5" in m.source and "GEFSv12" in m.source and "AIFS" in m.source
    assert "CC BY 4.0" in m.license and "NODD" in m.license
    assert m.period == "2001-04-01/2001-05-02"  # event days only, controls excluded
    assert m.files == ["cases.json", "skill.json"]
    for f in m.files:
        assert (inputs / f).is_file()


def test_cases_events_only_with_cos_weighted_ensemble_stats(inputs):
    c = load(inputs, "cases.json")
    assert c["leads"] == [1, 2]
    g = c["models"]["gefs-reforecast"]
    assert [e["event_id"] for e in g["events"]] == [
        "AR-2001-002",
        "AR-2001-001",
    ]  # sorted by date; no control
    e1 = g["events"][1]
    # weighted box mean of member m: (1*(3+m) + 0.5*(6+m)) / 1.5 = 4 + m  -> members 4, 5, 6
    assert e1["mean"] == [5.0, 5.0] and e1["min"] == [4.0, 4.0] and e1["max"] == [6.0, 6.0]
    assert e1["obs_mm"] == 7.0 and e1["date"] == "2001-05-02"
    e2 = g["events"][0]
    assert e2["obs_mm"] == 2.5
    assert e2["mean"] == [1.0, 1.0]  # lead 2 without member 0 still 1.0 from the others
    ifs = c["models"]["ifs"]["events"][1]
    assert ifs["mean"] == ifs["min"] == ifs["max"] == [4.0, 4.0]  # one member: no range


def test_unpublished_entries_are_null(tmp_path):
    ds = make_ds("ifs", 1)
    ds["status"].values[0, 1, 0] = 1
    res = hv.model_cases(ds, pd.Series([1.0], index=pd.to_datetime(["2001-05-02"])))
    ev = {e["event_id"]: e for e in res["events"]}
    out = json.dumps(hv._clean(ev["AR-2001-001"]), allow_nan=False)
    assert json.loads(out)["mean"][1] is None and json.loads(out)["mean"][0] == 4.0
    assert (
        ev["AR-2001-002"]["obs_mm"] != ev["AR-2001-002"]["obs_mm"]
    )  # no observation -> NaN (build refuses it)


def test_build_refuses_events_without_observation(inputs, tmp_path):
    rep = tmp_path / "rep"
    rep.mkdir()
    for f in ("F5.2.json", "F5.4.json", "F5.8.json"):
        (rep / f).write_text((inputs.parent.parent / "reports" / f).read_text())
    pd.DataFrame({"date": ["2001-04-01"], "box_mean_mm": [1.0]}).to_csv(
        rep / "F5.2-obs.csv", index=False
    )
    with pytest.raises(ValueError, match="without an ERA5 observation"):
        hv.build(inputs.parent.parent / "f51", rep, tmp_path / "out")


def test_skill_curves_events_only(inputs):
    s = load(inputs, "skill.json")
    g = s["models"]["ifs"]
    assert g["leads"] == [1, 2]
    assert g["crpss"][0] == {
        "lead": 1,
        "value": 0.5,
        "lo": 0.1,
        "hi": 0.8,
    }  # control record (9.0) ignored
    assert g["bias"][1]["value"] == -1.0 and g["n"][0] == {"lead": 1, "n": 5}


def test_aifs_vs_ifs_events_only(inputs):
    a = load(inputs, "skill.json")["aifs_vs_ifs"]
    assert len(a["rows"]) == 1 and a["rows"][0]["lead"] == "1" and a["rows"][0]["mae_aifs"] == 2.0
    assert a["first"] == "2024-03-03" and a["n_event"] == 4


def test_gate_table_status_and_nan_as_null(inputs):
    g = load(inputs, "skill.json")["gate"]
    rows = g["regions"]["r1"]
    assert [r["lead"] for r in rows] == [1, 2]
    assert (
        rows[0]["status"] == "pasa hindcast (espera la temporada prospectiva)"
        and rows[1]["status"] == "Experimental"
    )
    assert rows[0]["bss_log_clim"] == {"value": 0.3, "lo": 0.1, "hi": 0.5}
    assert rows[0]["n_events_pooled"] == 9 and rows[0]["prob_cap"] == 0.7
    assert rows[0]["pod_far"]["p>=0.5"]["far"] is None  # NaN -> null: strict JSON
    assert g["quantile"] == 0.95 and g["n_events_pooled_test"] == 9


def test_files_are_strict_json(inputs):
    for f in ("cases.json", "skill.json"):
        json.loads(
            (inputs / f).read_text(encoding="utf-8"), parse_constant=lambda c: pytest.fail(c)
        )


def test_api_serves_the_layer(inputs):
    client = TestClient(create_app(inputs.parent))
    assert client.get("/layers").json()[0]["id"] == "hindcast-verification"
    assert client.get("/layers/hindcast-verification/data").json()["id"] == "hindcast-verification"
    assert (
        client.get("/layers/hindcast-verification/data", params={"file": "skill.json"}).status_code
        == 200
    )

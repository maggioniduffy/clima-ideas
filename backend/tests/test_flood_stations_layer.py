import itertools
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import flow
from clima_nqn.layers import flood_stations as fs
from clima_nqn.layers.manifest import load_manifest

LOC, SCALE, XI = 100.0, 40.0, 0.2
RLEVELS = [(2, 1.0), (5, 1.5), (10, 2.0), (25, 2.5), (50, 3.0), (100, 3.5)]


def daily(start, end, drop=()):
    dates = pd.date_range(start, end, freq="D", name="date")
    q = np.arange(len(dates), dtype=float) + 0.04
    q[[i for i, d in enumerate(dates) if d.strftime("%Y-%m-%d") in drop]] = np.nan
    df = pd.DataFrame({"date": dates, "q_m3s": q, "qualifier": "", "validated": True})
    return df


def station_meta(sid, name, note=""):
    return {
        "id": sid, "name": name, "river": "Río X", "lat": -38.5, "lon": -69.4, "area_km2": 1000.0,
        "hydro_year_start_month": 4, "alta_year": 1990, "note": note,
        "first_date": None, "last_date": None, "first_valid_date": None, "last_valid_date": None,
    }  # fmt: skip


def gev_json(sid):
    return {
        "station_id": sid, "name": "n", "river": "r", "area_km2": 1000.0,
        "hydro_year_start_month": 4, "min_valid_days": 330,
        "source": "SNIH (SIPH) — Red Hidrológica Nacional", "url": "u", "fetched": "2026-11-09",
        "period": "2000-01-01/2003-12-31", "n_years": 3, "years_used": [2000, 2001, 2002],
        "excluded_years": [], "top": 5,
        "gev": {
            "loc": LOC, "scale": SCALE, "shape_xi": XI, "shape_c_scipy": -XI, "n": 3,
            "n_samples": 20, "seed": 1, "ci_level": 0.95, "ks_statistic": 0.1, "ks_pvalue": 0.8,
            "return_levels": [
                {"return_period": t, "value": 200.0 * t**0.3, "ci95_low": 100.0 * t**0.3 * k,
                 "ci95_high": 400.0 * t**0.3 * k}
                for t, k in RLEVELS
            ],
        },
        "annual_maxima": [
            {"hydro_year": 2000, "date": "2000-06-01", "q_m3s": 321.46, "valid_days": 366,
             "empirical_T": 4.0, "gev_T": 3.1},
            {"hydro_year": 2001, "date": "2001-06-01", "q_m3s": 500.0, "valid_days": 365,
             "empirical_T": 2.0, "gev_T": 2.2},
        ],
    }  # fmt: skip


@pytest.fixture
def world(tmp_path):
    flow_dir, gev_dir, out = tmp_path / "flow", tmp_path / "flow" / "gev", tmp_path / "out"
    gev_dir.mkdir(parents=True)
    frames = {
        1001: daily("2000-04-01", "2003-03-31", drop=("2000-04-10", "2000-04-11")),
        1002: daily("2000-04-01", "2002-03-31"),
    }
    for sid, df in frames.items():
        flow.write_flow(df, flow_dir / f"{sid}.parquet")
    stations = [
        station_meta(1001, "Natural"),
        station_meta(1002, "Regulada", note="regulada aguas arriba (Alicurá, 1984); sin verificar"),
        station_meta(1003, "Sin datos"),  # no Parquet: left out
    ]
    (flow_dir / "stations.json").write_text(
        json.dumps({"source": "s", "url": "u", "fetched": "2026-11-09", "stations": stations}),
        encoding="utf-8",
    )
    (gev_dir / "1001.json").write_text(json.dumps(gev_json(1001)), encoding="utf-8")
    fs.build_layer(flow_dir, gev_dir, out)
    return out


def load(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_manifest_validates_and_lists_every_file(world):
    m = load_manifest(world / "manifest.json")
    assert m.id == "flood-stations"
    assert m.title == "Crecidas: caudal y período de retorno"
    assert m.kind == "points"
    assert m.source == "SNIH (SIPH) — Red Hidrológica Nacional"
    assert m.period == "2000-04-01/2003-03-31"
    assert m.license == (
        "Uso libre citando la fuente (términos SNIH/SIPH); datos actualizados al 2026-11-09"
    )
    assert m.files == ["stations.json", "stations/1001.json", "stations/1002.json"]
    for f in m.files:
        assert (world / f).is_file()


def test_stations_json_fields_and_value_rule(world):
    rows = {r["id"]: r for r in load(world, "stations.json")}
    assert set(rows) == {"1001", "1002"}
    assert set(rows["1001"]) == {
        "id", "lon", "lat", "value", "name", "river", "area_km2", "has_gev", "regulated",
    }  # fmt: skip
    # GEV station: value = 100-year return level
    assert rows["1001"]["has_gev"] and not rows["1001"]["regulated"]
    assert rows["1001"]["value"] == pytest.approx(200.0 * 100**0.3, abs=0.1)
    # no GEV: value = max observed daily flow
    n = len(daily("2000-04-01", "2002-03-31"))
    assert not rows["1002"]["has_gev"] and rows["1002"]["regulated"]
    assert rows["1002"]["value"] == pytest.approx(n - 1 + 0.04, abs=0.1)


def test_daily_array_covers_the_range_with_null_gaps(world):
    d = load(world, "stations/1001.json")
    start, end = date(2000, 4, 1), date(2003, 3, 31)
    assert d["daily"]["start"] == "2000-04-01"
    assert len(d["daily"]["q"]) == (end - start).days + 1
    assert d["daily"]["q"][9] is None and d["daily"]["q"][10] is None
    assert d["daily"]["q"][0] == 0.0 and d["daily"]["q"][11] == 11.0  # one decimal
    assert d["period"] == "2000-04-01/2003-03-31"
    assert d["source"] == flow.SOURCE and d["fetched"] == "2026-11-09"


def test_gev_station_has_curve_levels_and_maxima(world):
    d = load(world, "stations/1001.json")
    assert d["gev"] == {
        "loc": LOC, "scale": SCALE, "shape_xi": XI, "n_years": 3, "ks_p": 0.8, "irregular": False,
    }  # fmt: skip
    assert [r["t"] for r in d["return_levels"]] == [2, 5, 10, 25, 50, 100]
    curve = d["curve"]
    ts, qs = [c["t"] for c in curve], [c["q"] for c in curve]
    assert 38 <= len(curve) <= 42
    assert ts[0] == pytest.approx(1.1) and ts[-1] == pytest.approx(200.0)
    assert ts == sorted(ts) and all(b > a for a, b in itertools.pairwise(qs))
    assert d["annual_maxima"][0] == {
        "hydro_year": 2000, "date": "2000-06-01", "q": 321.5, "t_empirical": 4.0, "t_gev": 3.1,
    }  # fmt: skip
    assert [m["hydro_year"] for m in d["top_floods"]] == [2001, 2000]


def test_curve_ci_is_null_outside_the_stored_t_range(world):
    curve = load(world, "stations/1001.json")["curve"]
    for c in curve:
        inside = 2 <= c["t"] <= 100
        assert (c["lo"] is not None) == inside and (c["hi"] is not None) == inside
        if inside:
            assert c["lo"] <= c["q"] * 10 and c["lo"] < c["hi"]
    # interpolation hits the stored values at stored periods
    at = {round(c["t"], 6): c for c in curve}
    assert min(abs(c["t"] - 2) for c in curve) < 0.5 and at


def test_irregular_flag_follows_xi(tmp_path):
    g = gev_json(1)
    g["gev"]["shape_xi"] = 0.5
    block = fs.gev_block(g["gev"], g["n_years"])
    assert block["irregular"] is True


def test_regulated_station_has_no_gev_or_curve(world):
    d = load(world, "stations/1002.json")
    for key in ("gev", "return_levels", "curve"):
        assert key not in d
    assert d["has_gev"] is False and d["regulated"] is True
    assert d["annual_maxima"] and all(m["t_gev"] is None for m in d["annual_maxima"])
    assert len(d["top_floods"]) <= 5


def test_cli_flow_layer(tmp_path, world):
    flow_dir = tmp_path / "flow"
    out = tmp_path / "cli-out"
    res = CliRunner().invoke(
        app,
        ["flow", "layer", "--flow-dir", str(flow_dir), "--gev-dir", str(flow_dir / "gev"),
         "--out", str(out)],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    assert (out / "manifest.json").is_file()

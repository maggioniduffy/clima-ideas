import json
import math

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import rasterio
import xarray as xr
from rasterio.transform import from_origin
from typer.testing import CliRunner

from clima_nqn import cli
from clima_nqn.io import dem, forcing, snow

LATS = np.array([-38.0, -37.75, -37.5, -37.0])
LONS = np.array([-71.0, -70.75, -70.5])
BOX = (-37.8, -37.4, -71.0, -70.6)  # lat -37.75, -37.5 and lon -71.0, -70.75 inside
SID = 12010


def write_store(path, year, variables, lats=LATS, lons=LONS, end=None):
    times = pd.date_range(f"{year}-01-01", end or f"{year}-12-31 23:00", freq="h")
    data = {}
    for name, fn in variables.items():
        arr = np.asarray(fn(times), dtype="float32")
        if arr.ndim == 1:
            arr = np.broadcast_to(arr[:, None, None], (len(times), len(lats), len(lons))).copy()
        data[name] = (("time", "lat", "lon"), arr)
    xr.Dataset(data, coords={"time": times, "lat": lats, "lon": lons}).to_zarr(
        path, mode="w", consolidated=False
    )


def p1(times):
    return np.ones(len(times)) * 0.001  # 1 mm every hour -> 24 mm/day


def d0(times):
    return np.full(len(times), 3000.0)


def t2m(times):
    return 273.15 + 10 + 5 * np.sin(2 * np.pi * (times.hour.values - 9) / 24)


def make_dirs(tmp_path, years=(2020,), with_t2m=True):
    e, t = tmp_path / "era5", tmp_path / "t2m"
    for y in years:
        write_store(e / f"{y}.zarr", y, {"tp": p1, "deg0l": d0})
        if with_t2m:
            write_store(t / f"{y}.zarr", y, {"t2m": t2m})
    return e, t


def run(tmp_path, e, t, **kw):
    return forcing.build_forcing(
        e, tmp_path / "out" / "forcing.parquet", t, boxes={SID: BOX}, progress=lambda *_: None, **kw
    )


def test_tp_daily_window_is_01_to_00(tmp_path):
    def tp(times):
        v = np.zeros(len(times))
        v[(times == "2020-03-10 00:00").nonzero()[0]] = 0.005  # belongs to 9 March
        v[(times == "2020-03-10 01:00").nonzero()[0]] = 0.002  # belongs to 10 March
        v[(times == "2020-03-11 00:00").nonzero()[0]] = 0.003  # belongs to 10 March
        return v

    e = tmp_path / "era5"
    write_store(e / "2020.zarr", 2020, {"tp": tp, "deg0l": d0})
    write_store(e / "2021.zarr", 2021, {"tp": p1, "deg0l": d0}, end="2021-01-01 00:00")
    df, _ = forcing.year_frame(2020, e, None, {SID: BOX})
    day = df.set_index("date")["precip_mm"]
    assert day["2020-03-09"] == pytest.approx(5.0)
    assert day["2020-03-10"] == pytest.approx(5.0)
    assert day["2020-03-11"] == 0.0
    # Dec 31 takes its last hour (1 mm) from 2021-01-01 00:00
    assert day["2020-12-31"] == pytest.approx(1.0)


def test_last_day_nan_without_next_year(tmp_path):
    e, _ = make_dirs(tmp_path, with_t2m=False)
    df, have_t = forcing.year_frame(2020, e, None, {SID: BOX})
    assert have_t is False
    assert math.isnan(df.set_index("date")["precip_mm"]["2020-12-31"])
    assert df.set_index("date")["precip_mm"]["2020-06-01"] == pytest.approx(24.0)
    assert len(df) == 366


def test_box_mean_cos_weights_and_exclusion():
    values = np.zeros((2, len(LATS), len(LONS)), dtype="float32")
    values[:, 2, 0] = 10.0  # lat -37.5, lon -71.0 (inside)
    values[:, 1, 0] = 20.0  # lat -37.75 (inside)
    values[:, 1, 2] = 1000.0  # lon -70.5: outside the box
    values[:, 0, :] = 1000.0  # lat -38: outside
    da = xr.DataArray(
        values, dims=("time", "lat", "lon"), coords={"time": [0, 1], "lat": LATS, "lon": LONS}
    )
    w1, w2 = math.cos(math.radians(-37.5)), math.cos(math.radians(-37.75))
    # cells inside: lat {-37.75, -37.5} x lon {-71.0, -70.75}; values 20, 0 (lon -70.75), 10, 0
    expected = (20 * w2 + 0 * w2 + 10 * w1 + 0 * w1) / (2 * w1 + 2 * w2)
    np.testing.assert_allclose(forcing.box_mean(da, BOX), [expected, expected], rtol=1e-6)
    with pytest.raises(ValueError, match="no ERA5 cell"):
        forcing.box_mean(da, (-37.6, -37.55, -71.0, -70.0))


def test_oudin_pet_hand_value_and_zero_below_minus5():
    lat, doy, temp = -37.0, 15, 20.0
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    delta = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(-math.tan(phi) * math.tan(delta))
    re = (
        24 * 60 / math.pi * 0.0820 * dr
        * (ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))
    )  # fmt: skip
    expected = re / 2.45 * (temp + 5) / 100
    assert 3 < expected < 6  # sanity: a January day at 37 S
    assert forcing.oudin_pet(np.array([temp]), lat, doy)[0] == pytest.approx(expected)
    out = forcing.oudin_pet(np.array([-5.0, -12.0, np.nan]), lat, doy)
    assert out[0] == 0.0 and out[1] == 0.0 and math.isnan(out[2])


def test_temperature_stats_and_pet_columns(tmp_path):
    e, t = make_dirs(tmp_path)
    res = run(tmp_path, e, t)
    assert res["missing_t2m_years"] == []
    df = pd.read_parquet(res["path"]).set_index("date")
    assert list(pd.read_parquet(res["path"]).columns) == forcing.COLUMNS
    hours = np.arange(24)
    series = 10 + 5 * np.sin(2 * np.pi * (hours - 9) / 24)
    row = df.loc["2020-06-01"]
    assert row["tmean_c"] == pytest.approx(series.mean(), abs=1e-4)
    assert row["tmin_c"] == pytest.approx(series.min(), abs=1e-4)
    assert row["tmax_c"] == pytest.approx(series.max(), abs=1e-4)
    assert row["deg0l_m"] == pytest.approx(3000.0)
    expected = forcing.oudin_pet(np.array([row["tmean_c"]]), -37.6, 153)[0]
    assert row["pet_mm"] == pytest.approx(expected)


def test_missing_t2m_gives_nan_and_rerun_fills(tmp_path):
    e, t = make_dirs(tmp_path, years=(2020, 2021), with_t2m=False)
    write_store(t / "2021.zarr", 2021, {"t2m": t2m})
    res = run(tmp_path, e, t)
    assert res["missing_t2m_years"] == [2020]
    df = pd.read_parquet(res["path"])
    y20 = df[df["date"].dt.year == 2020]
    assert y20[["tmean_c", "tmin_c", "tmax_c", "pet_mm"]].isna().all().all()
    assert not y20["precip_mm"].iloc[:-1].isna().any()
    assert df[df["date"].dt.year == 2021]["tmean_c"].notna().all()
    # no t2m dir at all
    res = forcing.build_forcing(
        e, tmp_path / "other.parquet", None, boxes={SID: BOX}, progress=lambda *_: None
    )
    assert res["missing_t2m_years"] == [2020, 2021]
    # temperature arrives later: the rerun recomputes only 2020
    write_store(t / "2020.zarr", 2020, {"t2m": t2m})
    res = run(tmp_path, e, t)
    assert res["computed"] == [2020]
    assert res["missing_t2m_years"] == []
    assert pd.read_parquet(res["path"])["tmean_c"].notna().all()


def test_resume_does_not_recompute(tmp_path, monkeypatch):
    e, t = make_dirs(tmp_path, years=(2020, 2021))
    first = run(tmp_path, e, t)
    assert first["computed"] == [2020, 2021]
    calls = []
    real = forcing.year_frame

    def spy(*args, **kwargs):
        calls.append(args[0])
        return real(*args, **kwargs)

    second = run(tmp_path, e, t, year_fn=spy)
    assert calls == [] and second["computed"] == []
    again = pd.read_parquet(first["path"])
    assert len(again) == 366 + 365


def test_box_change_refuses_to_append(tmp_path):
    e, t = make_dirs(tmp_path)
    run(tmp_path, e, t)
    with pytest.raises(ValueError, match="differs"):
        forcing.build_forcing(
            e,
            tmp_path / "out" / "forcing.parquet",
            t,
            boxes={SID: (-37.8, -37.4, -71.0, -70.0)},
            progress=lambda *_: None,
        )


def test_parquet_metadata(tmp_path):
    e, t = make_dirs(tmp_path)
    res = run(tmp_path, e, t, t2m_run_id="43326516635")
    meta = {k.decode(): v.decode() for k, v in pq.read_schema(res["path"]).metadata.items()}
    assert "ARCO-ERA5" in meta["source"] and "ERA5" in meta["source"]
    assert meta["license"] == "CC-BY 4.0"
    assert "mm/day" in meta["units"] and "degC" in meta["units"]
    assert meta["period"] == "2020-01-01 to 2020-12-31"
    assert meta["tp_deg0l_run_id"] == "42437929137"
    assert meta["t2m_run_id"] == "43326516635"
    assert "UTC-3" in meta["day_note"]
    assert snow.BOX_NOTE in meta["box_note"]


def write_tile(dem_dir, lat, lon, fn):
    n = 120
    data = fn(np.linspace(lat + 1, lat, n)[:, None], np.linspace(lon, lon + 1, n)[None, :])
    dem_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        dem_dir / f"{dem.tile_name(lat, lon)}.tif", "w", driver="GTiff", height=n, width=n,
        count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(lon, lat + 1, 1 / n, 1 / n),
    ) as ds:  # fmt: skip
        ds.write(np.broadcast_to(data, (n, n)).astype("float32"), 1)


def test_static_attributes(tmp_path):
    box = (-37.9, -37.1, -71.0, -70.2)
    dem_dir = tmp_path / "dem"
    # elevation grows with longitude: 1000 m at lon -71, 3000 m at lon -70; the box ends at -70.2
    write_tile(dem_dir, -38, -71, lambda la, lo: 1000 + 2000 * (lo + 71))
    path = forcing.build_static(
        tmp_path / "forcing.parquet", dem_dir, [SID], {SID: box}, step=1 / 120
    )
    assert path.name == "forcing.static.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    b = doc["basins"][str(SID)]
    expected_area = (
        6371.0088**2
        * math.radians(0.8)
        * (math.sin(math.radians(-37.1)) - math.sin(math.radians(-37.9)))
    )
    assert b["area_km2"] == pytest.approx(expected_area)
    assert b["centroid_lat"] == pytest.approx(-37.5) and b["centroid_lon"] == pytest.approx(-70.6)
    assert b["elev_min_m"] == pytest.approx(1000, abs=30)
    assert b["elev_max_m"] == pytest.approx(2600, abs=30)
    assert b["elev_mean_m"] == pytest.approx(1800, abs=40)
    assert b["frac_above_2000m"] == pytest.approx(0.375, abs=0.03)  # lon > -70.5
    assert "CC-BY" in doc["license"] and doc["units"] and doc["box_note"]


def test_static_missing_tiles_gives_null_and_warns(tmp_path):
    with pytest.warns(UserWarning, match="missing DEM tile"):
        path = forcing.build_static(
            tmp_path / "forcing.parquet", tmp_path / "nodem", [SID], {SID: BOX}
        )
    b = json.loads(path.read_text(encoding="utf-8"))["basins"][str(SID)]
    assert b["elev_mean_m"] is None and b["area_km2"] > 0


def test_cli_help_lists_every_option():
    res = CliRunner().invoke(cli.app, ["flow", "forcing", "--help"])
    assert res.exit_code == 0
    for opt in ("--era5-dir", "--t2m-dir", "--t2m-run-id", "--dem-dir", "--out", "--station"):
        assert opt in res.output


def test_cli_unknown_station_lists_valid(tmp_path):
    res = CliRunner().invoke(
        cli.app, ["flow", "forcing", "--station", "99999", "--out", str(tmp_path / "f.parquet")]
    )
    assert res.exit_code != 0
    for sid in snow.UPSTREAM_BOXES:
        assert str(sid) in res.output


def test_cli_runs_and_reports_missing_years(tmp_path, monkeypatch):
    e, _ = make_dirs(tmp_path, with_t2m=False)
    monkeypatch.setattr(snow, "UPSTREAM_BOXES", {SID: BOX})
    monkeypatch.setattr(forcing.snow, "UPSTREAM_BOXES", {SID: BOX})
    out = tmp_path / "o" / "f.parquet"
    res = CliRunner().invoke(
        cli.app,
        ["flow", "forcing", "--station", str(SID), "--era5-dir", str(e),
         "--t2m-dir", str(tmp_path / "nope"), "--dem-dir", str(tmp_path / "nodem"),
         "--out", str(out)],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    assert "no temperature (NaN) for years: 2020" in res.output
    assert out.exists() and (tmp_path / "o" / "f.static.json").exists()

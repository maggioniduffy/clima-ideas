"""F5.3 stage A: all-days cases, wide grid, observe with cp / date range, combine grid check."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.stages.hindcast import cases as cases_mod
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import observe, store

SPEC = fc.MODELS["gefs-reforecast"]
LEADS3 = (1, 5, 10)
WIDE = fc.WIDE_GRID


class WideFetcher:
    """Returns a field on the fetcher's grid; value encodes init date and lead."""

    def __init__(self, grid=WIDE):
        self.grid = grid

    def fetch(self, model, init, lead, member):
        v = float(init.strftime("%Y%m%d")) % 1000 + lead + fc.GEFS_MEMBERS.index(member) * 0.1
        return np.full(self.grid.shape, v, dtype=np.float32)


# --- all-days cases ----------------------------------------------------------------------------


def test_all_days_cases_default_period_and_columns():
    cases = cases_mod.all_days_cases()
    assert list(cases.columns) == cases_mod.COLUMNS
    assert len(cases) == (pd.Timestamp("2019-12-31") - pd.Timestamp("2000-01-10")).days + 1 == 7296
    assert cases["valid_date"].iloc[0] == pd.Timestamp("2000-01-10")
    assert cases["valid_date"].iloc[-1] == pd.Timestamp("2019-12-31")
    assert cases["valid_date"].is_unique and cases["case_id"].is_unique
    assert (cases["kind"] == "all").all() and cases["event_id"].isna().all()
    assert cases["ivt_max"].isna().all()
    assert cases["case_id"].iloc[0] == "ALL-20000110"
    assert (cases["month"] == cases["valid_date"].dt.month).all()
    assert cases["valid_date"].dtype == np.dtype("datetime64[ns]")


def test_all_days_cases_every_lead_has_an_init_inside_the_gefs_period():
    cases = cases_mod.all_days_cases()
    kept = fc.eligible_cases(cases, SPEC)
    assert len(kept) == len(cases)  # all inside the model's valid period
    first_init = min(fc.init_date(cases["valid_date"].iloc[0], L) for L in fc.LEADS)
    last_init = max(fc.init_date(cases["valid_date"].iloc[-1], L) for L in fc.LEADS)
    assert first_init == pd.Timestamp("2000-01-01")  # first GEFS reforecast init
    assert last_init <= pd.Timestamp("2019-12-31")
    # one day earlier would need an init before 2000-01-01 at lead 10
    assert fc.init_date(pd.Timestamp("2000-01-09"), 10) < first_init


def test_all_days_cases_rejects_reversed_range_and_writes_parquet(tmp_path):
    with pytest.raises(ValueError, match="before"):
        cases_mod.all_days_cases("2010-07-10", "2010-07-01")
    cases = cases_mod.all_days_cases("2010-07-01", "2010-07-10")
    counts = cases_mod.write_cases(
        cases, tmp_path / "c.parquet", 0, "all-days", cases_mod.ALL_DAYS_RULE
    )
    assert counts["all"] == 10
    back = cases_mod.read_cases(tmp_path / "c.parquet")
    assert list(back["case_id"]) == list(cases["case_id"])


def test_cli_cases_all_days(tmp_path):
    out = tmp_path / "alldays" / "cases.parquet"
    r = CliRunner().invoke(
        app,
        ["hindcast", "cases", "--all-days", "--first", "2010-07-01", "--last", "2010-07-10",
         "--out", str(out)],
    )  # fmt: skip
    assert r.exit_code == 0, r.output
    assert len(cases_mod.read_cases(out)) == 10
    r = CliRunner().invoke(app, ["hindcast", "cases", "--out", str(out)])
    assert r.exit_code != 0  # no --events and no --all-days


# --- grids -------------------------------------------------------------------------------------


def test_wide_grid_shape_and_coords():
    assert fc.WIDE_AREA == (-36.0, -72.0, -41.25, -67.5)
    assert WIDE.shape == (22, 19)
    assert WIDE.lat[0] == -41.25 and WIDE.lat[-1] == -36.0
    assert WIDE.lon[0] == -72.0 and WIDE.lon[-1] == -67.5
    assert (np.diff(WIDE.lat) > 0).all() and (np.diff(WIDE.lon) > 0).all()
    assert np.allclose(np.diff(WIDE.lat), 0.25) and np.allclose(np.diff(WIDE.lon), 0.25)


def test_f51_defaults_unchanged():
    assert fc.AREA == fc.F51_AREA == (-36.0, -71.5, -41.0, -68.0)
    assert fc.F51_GRID.shape == (21, 15) == (len(fc.LAT), len(fc.LON))
    assert np.array_equal(fc.LAT, fc.F51_GRID.lat) and np.array_equal(fc.LON, fc.F51_GRID.lon)
    assert fc.get_grid("wide") is fc.WIDE_GRID
    with pytest.raises(ValueError):
        fc.get_grid("huge")


def test_to_target_grid_wide_selects_and_interpolates():
    lat = np.arange(-45.0, -30.0 + 1e-6, 0.25)
    lon = np.arange(-76.0, -64.0 + 1e-6, 0.25)
    field = xr.DataArray(
        np.broadcast_to(lon + 100.0, (len(lat), len(lon))).copy(),
        coords={"lat": lat, "lon": lon},
        dims=("lat", "lon"),
    )
    out = fc.to_target_grid(field, WIDE)
    assert out.shape == (22, 19)
    np.testing.assert_allclose(out[0], WIDE.lon + 100.0, atol=1e-4)


def test_empty_store_wide_area():
    cases = cases_mod.all_days_cases("2010-07-01", "2010-07-03")
    ds = store.empty_store(SPEC, cases, LEADS3, WIDE)
    assert ds["precip_mm"].shape == (3, 3, 5, 22, 19)
    assert np.array_equal(ds["lat"].values, WIDE.lat) and np.array_equal(ds["lon"].values, WIDE.lon)
    assert (ds["kind"].values == "all").all()
    assert store.store_grid(store.empty_store(SPEC, cases, LEADS3)) == fc.F51_GRID  # no attr: F5.1
    default = store.empty_store(SPEC, cases, LEADS3)
    assert default["precip_mm"].shape == (3, 3, 5, 21, 15)


def test_fetch_shard_wide_roundtrip_and_attrs(tmp_path):
    cases = cases_mod.all_days_cases("2010-07-01", "2010-07-04")
    path = tmp_path / "m.zarr"
    res = store.fetch_shard(
        SPEC, cases, WideFetcher(), path, LEADS3, 4, log_fn=lambda m: None, grid=WIDE
    )
    assert res["n_ok"] == 4 * 3 * 5 and res["n_pending"] == 0
    ds = store.read_store(path)
    assert ds["precip_mm"].shape == (4, 3, 5, 22, 19)
    assert ds.attrs["area"] == list(fc.WIDE_AREA) and ds.attrs["grid_name"] == "wide"
    assert "-72" in ds.attrs["grid"] and "-41.25" in ds.attrs["grid"]
    assert store.store_grid(ds) == WIDE
    # resuming with another grid is refused
    with pytest.raises(ValueError, match="different"):
        store.fetch_shard(
            SPEC, cases, WideFetcher(fc.F51_GRID), path, LEADS3, 4, log_fn=lambda m: None
        )


def _shard(tmp_path, cases, i, n, grid):
    store.fetch_shard(
        SPEC, cases.iloc[i - 1 :: n].reset_index(drop=True), WideFetcher(grid),
        store.shard_path(tmp_path, SPEC.name, i, n), LEADS3, 2, log_fn=lambda m: None, grid=grid,
    )  # fmt: skip


def test_combine_wide_shards_keeps_grid(tmp_path):
    cases = cases_mod.all_days_cases("2010-07-01", "2010-07-06")
    for i in (1, 2):
        _shard(tmp_path / "s", cases, i, 2, WIDE)
    ds = store.combine_shards(SPEC, tmp_path / "s", tmp_path / "out.zarr")
    assert ds.attrs["area"] == list(fc.WIDE_AREA) and ds.attrs["n_shards"] == 2
    assert ds["precip_mm"].shape[-2:] == (22, 19)
    assert list(ds["case"].values) == list(cases["case_id"])


def test_combine_rejects_mixed_grids(tmp_path):
    cases = cases_mod.all_days_cases("2010-07-01", "2010-07-06")
    _shard(tmp_path / "s", cases, 1, 2, WIDE)
    _shard(tmp_path / "s", cases, 2, 2, fc.F51_GRID)
    with pytest.raises(ValueError, match="disagree on the grid"):
        store.combine_shards(SPEC, tmp_path / "s", tmp_path / "out.zarr")


# --- observe: cp, date range, wide grid ----------------------------------------------------------


def fake_arco_cp(stop: str = "2026-06-30"):
    """ARCO-like store: tp = hour index * 1e-3 m, cp = half of it."""
    times = pd.date_range("2020-01-01", "2020-01-10", freq="h")
    lat = np.arange(-30.0, -45.0 - 1e-6, -0.25)
    lon = np.arange(280.0, 300.0 + 1e-6, 0.25)
    hours = np.arange(len(times), dtype="float32") * 1e-3
    tp = np.broadcast_to(hours[:, None, None], (len(times), len(lat), len(lon))).copy()
    dims = ("time", "latitude", "longitude")
    return xr.Dataset(
        {"total_precipitation": (dims, tp), "convective_precipitation": (dims, tp * 0.5)},
        coords={"time": times, "latitude": lat, "longitude": lon},
        attrs={"valid_time_stop": stop},
    )


def test_observed_days_cp_wide_grid():
    ds = observe.observed_days(
        pd.date_range("2020-01-03", "2020-01-05"),  # a date range, not a cases table
        opener=fake_arco_cp, workers=4, retries=1, grid=WIDE, variables=("tp", "cp"),
    )  # fmt: skip
    assert ds["precip_mm"].shape == ds["cp_mm"].shape == (3, 22, 19)
    assert np.array_equal(ds["lat"].values, WIDE.lat) and np.array_equal(ds["lon"].values, WIDE.lon)
    assert ds["cp_mm"].dtype == np.float32
    assert np.allclose(ds["precip_mm"].sel(date="2020-01-03").values, 1452.0)
    assert np.allclose(ds["cp_mm"].sel(date="2020-01-03").values, 726.0)
    assert ds.attrs["grid_name"] == "wide" and "convective" in ds.attrs["variables"]


def test_observed_days_default_has_only_tp_on_f51():
    ds = observe.observed_days(["2020-01-03"], opener=fake_arco_cp, retries=1)
    assert "cp_mm" not in ds and ds["precip_mm"].shape == (1, 21, 15)
    with pytest.raises(ValueError, match="variables"):
        observe.observed_days(["2020-01-03"], opener=fake_arco_cp, retries=1, variables=("xx",))


def test_cli_observe_requires_exactly_one_of_cases_or_range(tmp_path):
    cases = tmp_path / "c.parquet"
    cases_mod.write_cases(cases_mod.all_days_cases("2010-07-01", "2010-07-03"), cases, 0)
    run = CliRunner().invoke
    out = str(tmp_path / "o.zarr")
    assert run(app, ["hindcast", "observe", "--out", out]).exit_code != 0
    both = ["--cases", str(cases), "--first", "2010-07-01", "--last", "2010-07-02"]
    assert run(app, ["hindcast", "observe", "--out", out, *both]).exit_code != 0
    only_first = ["--first", "2010-07-01"]
    assert run(app, ["hindcast", "observe", "--out", out, *only_first]).exit_code != 0
    assert run(app, ["hindcast", "observe", "--out", out, "--first", "2010-07-02",
                     "--last", "2010-07-01"]).exit_code != 0  # fmt: skip
    r = run(app, ["hindcast", "observe", "--out", out, "--first", "2010-07-01", "--last",
                  "2010-07-02", "--area", "huge"])  # fmt: skip
    assert r.exit_code != 0

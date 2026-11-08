import numpy as np
import pandas as pd
import pytest
import xarray as xr

from clima_nqn.io import era5

RAW_NAMES = list(era5.VARIABLES)


def make_raw(times, lats=None, lons=None):
    """ARCO-like dataset: 0..360 longitudes, descending latitudes, long variable names.

    Every value encodes its position: value = lat * 1000 + lon_in_0_360 + hour_index / 100.
    """
    lats = np.arange(10.0, -11.0, -5.0) if lats is None else lats
    lons = np.arange(0.0, 360.0, 30.0) if lons is None else lons
    times = pd.DatetimeIndex(times)
    grid = (
        lats[None, :, None] * 1000
        + lons[None, None, :]
        + np.arange(len(times))[:, None, None] / 100
    )
    data = {
        name: (
            ("time", "latitude", "longitude"),
            grid.astype("float32"),
            {"units": "u", "long_name": name},
        )
        for name in RAW_NAMES
    }
    return xr.Dataset(data, coords={"time": times, "latitude": lats, "longitude": lons})


def test_crop_converts_lon_and_orders_lat():
    ds = make_raw(pd.date_range("2023-01-01", periods=2, freq="h"))
    out = era5.crop_to_area(ds, (6.0, -65.0, -6.0, 65.0))  # N, W, S, E
    assert list(out.data_vars) == list(era5.VARIABLES.values())
    assert out["lat"].values.tolist() == [-5.0, 0.0, 5.0]
    assert out["lon"].values.tolist() == [-60.0, -30.0, 0.0, 30.0, 60.0]
    # value at lat=5, lon=-60 (= 300 in the store) is lat*1000 + 300 at hour 0
    assert out["viwve"].sel(lat=5.0, lon=-60.0, time=out["time"][0]).item() == pytest.approx(5300.0)
    assert out["viwve"].sel(lat=-5.0, lon=30.0, time=out["time"][1]).item() == pytest.approx(
        -4970.0 + 0.01
    )
    assert out["viwve"].dtype == np.float32
    assert out["viwve"].attrs["units"] == "u"
    assert out["viwve"].attrs["long_name"] == RAW_NAMES[0]


def test_crop_neuquen_box_on_global_grid():
    lats = np.arange(90.0, -90.25, -0.25)
    lons = np.arange(0.0, 360.0, 0.25)
    ds = make_raw(pd.date_range("2023-01-01", periods=1, freq="h"), lats, lons)
    out = era5.crop_to_area(ds, era5.NEUQUEN_BOX)
    assert out["lat"].values[0] == -43.0 and out["lat"].values[-1] == -34.0
    assert out["lon"].values[0] == -74.0 and out["lon"].values[-1] == -66.0
    assert out.sizes["lat"] == 37 and out.sizes["lon"] == 33


def test_expected_times_leap_and_hours():
    assert len(era5.expected_times(2024, range(1, 13), range(24))) == 366 * 24
    assert len(era5.expected_times(2023, range(1, 13), range(24))) == 365 * 24
    feb = era5.expected_times(2024, [2], [0, 12])
    assert len(feb) == 29 * 2
    assert feb[0] == pd.Timestamp("2024-02-01 00:00") and feb[-1] == pd.Timestamp(
        "2024-02-29 12:00"
    )
    assert feb.is_monotonic_increasing


def test_parse_helpers():
    assert era5.parse_years("1980-1982,1990") == [1980, 1981, 1982, 1990]
    assert era5.parse_months("1-3,6") == [1, 2, 3, 6]
    assert era5.parse_hours("0,12") == [0, 12]
    assert era5.parse_hours("0-23") == list(range(24))
    with pytest.raises(ValueError):
        era5.parse_months("0-13")
    with pytest.raises(ValueError):
        era5.parse_hours("24")


def write_year(path, year, months, hours):
    times = era5.expected_times(year, months, hours)
    ds = era5.crop_to_area(make_raw(times), (6.0, -65.0, -6.0, 65.0))
    ds.to_zarr(path, mode="w", consolidated=False)
    return ds


def test_is_complete(tmp_path):
    path = tmp_path / "2023.zarr"
    assert era5.is_complete(path, 2023, [1], [0, 12]) is False  # missing
    write_year(path, 2023, [1], [0, 12])
    assert era5.is_complete(path, 2023, [1], [0, 12]) is True
    assert era5.is_complete(path, 2023, [1, 2], [0, 12]) is False  # more requested
    assert era5.is_complete(path, 2023, [1], [0]) is False  # different hours


def test_is_complete_detects_missing_step_and_variable(tmp_path):
    path = tmp_path / "2023.zarr"
    times = era5.expected_times(2023, [1], [0, 12])
    ds = era5.crop_to_area(make_raw(times), (6.0, -65.0, -6.0, 65.0))
    ds.isel(time=slice(0, -1)).to_zarr(path, mode="w", consolidated=False)
    assert era5.is_complete(path, 2023, [1], [0, 12]) is False
    ds.drop_vars("tp").to_zarr(path, mode="w", consolidated=False)
    assert era5.is_complete(path, 2023, [1], [0, 12]) is False


class FakeStore:
    """Stands in for the ARCO dataset; counts reads."""

    def __init__(self):
        times = pd.date_range("2022-12-31", "2023-03-01 23:00", freq="h")
        self.ds = make_raw(times)
        self.calls = 0

    def open(self):
        self.calls += 1
        return self.ds


def test_fetch_year_writes_and_is_idempotent(tmp_path):
    store = FakeStore()
    area = (6.0, -65.0, -6.0, 65.0)
    kw = {
        "months": [1, 2],
        "hours": [0, 12],
        "area": area,
        "out_dir": tmp_path,
        "opener": store.open,
        "retry_wait": 0,
        "workers": 2,
    }
    path = era5.fetch_year(2023, **kw)
    assert path == tmp_path / "2023.zarr"
    assert not (tmp_path / "2023.zarr.tmp").exists()
    out = xr.open_zarr(path, consolidated=False)
    assert out.sizes["time"] == (31 + 28) * 2
    assert out.attrs["license"] == "CC-BY 4.0"
    assert out.attrs["era5t"] is False or out.attrs["era5t"] == 0
    assert "Copernicus" in out.attrs["source"]
    assert out["tp"].dtype == np.float32
    assert "01:00" in out["tp"].attrs["note"]
    calls = store.calls
    again = era5.fetch_year(2023, **kw)
    assert again == path and store.calls == calls  # skipped, store not even opened


def test_fetch_year_rebuilds_incomplete(tmp_path):
    store = FakeStore()
    area = (6.0, -65.0, -6.0, 65.0)
    bad = tmp_path / "2023.zarr"
    write_year(bad, 2023, [1], [0])  # wrong content
    era5.fetch_year(
        2023,
        months=[1],
        hours=[0, 12],
        area=area,
        out_dir=tmp_path,
        opener=store.open,
        retry_wait=0,
    )
    assert era5.is_complete(bad, 2023, [1], [0, 12])


def test_fetch_month_retries_then_succeeds(tmp_path):
    store = FakeStore()
    fails = {"n": 0}

    def flaky():
        fails["n"] += 1
        if fails["n"] < 3:
            raise OSError("transient")
        return store.ds

    ds = era5.fetch_month(
        2023, 1, [0], (6.0, -65.0, -6.0, 65.0), opener=flaky, retries=3, retry_wait=0
    )
    assert ds.sizes["time"] == 31 and fails["n"] == 3


def test_fetch_month_gives_up(tmp_path):
    def broken():
        raise OSError("down")

    with pytest.raises(OSError):
        era5.fetch_month(2023, 1, [0], era5.NEUQUEN_BOX, opener=broken, retries=2, retry_wait=0)


def test_era5t_flag_from_store_attrs(tmp_path):
    store = FakeStore()
    store.ds.attrs["valid_time_stop"] = "2023-01-15"
    path = era5.fetch_year(
        2023,
        months=[1],
        hours=[0],
        area=(6.0, -65.0, -6.0, 65.0),
        out_dir=tmp_path,
        opener=store.open,
        retry_wait=0,
    )
    assert bool(xr.open_zarr(path, consolidated=False).attrs["era5t"]) is True


def test_combine(tmp_path):
    area = (6.0, -65.0, -6.0, 65.0)
    for year in (2022, 2021, 2023):
        write_year(tmp_path / f"{year}.zarr", year, [1], [0, 12])
    (tmp_path / "2024.zarr.tmp").mkdir()  # leftovers are ignored
    out = era5.combine(tmp_path, tmp_path / "neuquen.zarr")
    ds = xr.open_zarr(out, consolidated=False)
    assert ds.sizes["time"] == 3 * 31 * 2
    assert ds["time"].to_index().is_monotonic_increasing
    assert ds["time"].values[0] == np.datetime64("2021-01-01T00:00")
    assert ds["viwve"].dtype == np.float32
    assert ds.attrs["period"].startswith("2021-01-01")
    assert area  # grid is the per-year grid
    assert not (tmp_path / "neuquen.zarr.tmp").exists()


def test_combine_without_years_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        era5.combine(tmp_path, tmp_path / "neuquen.zarr")


@pytest.mark.slow
def test_live_one_day_two_hours(tmp_path):
    path = era5.fetch_year(2023, months=[1], hours=[0, 12], out_dir=tmp_path, days=[1])
    ds = xr.open_zarr(path, consolidated=False)
    assert ds.sizes["time"] == 2
    assert set(ds.data_vars) == set(era5.VARIABLES.values())
    assert float(ds["viwve"].isnull().sum()) == 0
    assert float(ds["lat"].min()) == -43.0

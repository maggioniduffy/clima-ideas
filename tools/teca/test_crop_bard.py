"""Tests for crop_bard.py with synthetic BARD-like files of known values (no TECA needed)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

sys.path.insert(0, str(Path(__file__).parent))
import crop_bard

NQN = [-34.0, -74.0, -43.0, -66.0]  # N, W, S, E


def make_bard(path, times, lon, lat, units="days since 1980-01-01 00:00:00"):
    """Write a BARD-like file where value = f(time index, lat, lon in -180..180) so it can be checked after cropping."""
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    lon180 = ((lon + 180) % 360) - 180
    t = np.arange(len(times))[:, None, None]
    prob = (t * 1000 + lat[None, :, None] * 10 + lon180[None, None, :]).astype(np.float32)
    tag = (prob.astype(int) % 2).astype(np.int32)
    ds = xr.Dataset(
        {"ar_probability": (("time", "lat", "lon"), prob), "ar_binary_tag": (("time", "lat", "lon"), tag)},
        coords={"time": np.array(times, dtype="datetime64[ns]"), "lat": lat, "lon": lon},
    )
    ds["time"].encoding.update({"units": units, "calendar": "standard"})
    ds.attrs = {"title": "synthetic BARD"}
    ds.to_netcdf(path)
    return ds


def expected(times_idx, lat, lon180):
    return (times_idx * 1000 + lat[:, None] * 10 + lon180[None, :]).astype(np.float32)


@pytest.mark.parametrize("lon_conv", ["180", "360"])
@pytest.mark.parametrize("lat_order", ["asc", "desc"])
def test_crop_conventions(tmp_path, lon_conv, lat_order):
    lon180 = np.arange(-100, -39, 2.0)
    lon = lon180 % 360 if lon_conv == "360" else lon180
    lat = np.arange(-60, -9, 3.0)
    if lat_order == "desc":
        lat = lat[::-1]
    f = tmp_path / "bard_1980-01.nc"
    make_bard(f, ["1980-01-01", "1980-01-02"], lon, lat)
    out = crop_bard.crop_files([f], NQN, tmp_path / "out")
    assert [p.name for p in out] == ["bard_neuquen_1980.nc"]
    ds = xr.open_dataset(out[0])
    assert ds.lon.values.min() >= -74 and ds.lon.values.max() <= -66
    assert ds.lat.values.min() >= -43 and ds.lat.values.max() <= -34
    assert list(ds.lat.values) == sorted(ds.lat.values)
    assert list(ds.lon.values) == sorted(ds.lon.values)
    assert ds.sizes["time"] == 2
    exp_lat = np.arange(-42, -33, 3.0)
    exp_lon = np.arange(-74, -65, 2.0)
    assert np.array_equal(ds.lat.values, exp_lat)
    assert np.array_equal(ds.lon.values, exp_lon)
    for i in range(2):
        assert np.array_equal(ds.ar_probability.values[i], expected(i, exp_lat, exp_lon))
    assert ds.ar_binary_tag.dims == ("time", "lat", "lon")


def test_multi_month_sorted_and_year_groups(tmp_path):
    lon = np.arange(-80, -60, 2.0)
    lat = np.arange(-50, -20, 3.0)
    f_b = tmp_path / "bard_1981-01.nc"
    f_a = tmp_path / "bard_1980-12.nc"
    f_c = tmp_path / "bard_1980-11.nc"
    make_bard(f_b, ["1981-01-01", "1981-01-02"], lon, lat)
    make_bard(f_a, ["1980-12-01", "1980-12-02"], lon, lat)
    make_bard(f_c, ["1980-11-01"], lon, lat)
    out = crop_bard.crop_files([f_b, f_a, f_c], NQN, tmp_path / "out")
    assert [p.name for p in out] == ["bard_neuquen_1980.nc", "bard_neuquen_1981.nc"]
    d80 = xr.open_dataset(out[0])
    d81 = xr.open_dataset(out[1])
    assert d80.sizes["time"] == 3 and d81.sizes["time"] == 2
    assert list(d80.time.values) == sorted(d80.time.values)
    assert str(d80.time.values[0])[:10] == "1980-11-01" and str(d80.time.values[-1])[:10] == "1980-12-02"
    # f_c (index 0), then f_a indices 0 and 1
    exp_lat = d80.lat.values
    exp_lon = d80.lon.values
    assert np.array_equal(d80.ar_probability.values[0], expected(0, exp_lat, exp_lon))
    assert np.array_equal(d80.ar_probability.values[2], expected(1, exp_lat, exp_lon))
    assert np.array_equal(d81.ar_probability.values[1], expected(1, exp_lat, exp_lon))


def test_attrs_and_time_encoding(tmp_path):
    f = tmp_path / "bard_1980-01.nc"
    make_bard(f, ["1980-01-01"], np.arange(-80, -60, 2.0), np.arange(-50, -20, 3.0), units="hours since 1900-01-01 00:00:00")
    out = crop_bard.crop_files([f], NQN, tmp_path / "out")
    ds = xr.open_dataset(out[0])
    assert ds.attrs["title"] == "synthetic BARD"
    assert ds.attrs["crop_area"] == "-34,-74,-43,-66"
    assert "bard_1980-01.nc" in ds.attrs["source_files"]
    assert ds.time.encoding["units"].startswith("hours since 1900-01-01")
    assert ds.ar_probability.encoding.get("zlib") is True


def test_empty_crop_raises(tmp_path):
    f = tmp_path / "bard_1980-01.nc"
    make_bard(f, ["1980-01-01"], np.arange(10, 40, 2.0), np.arange(30, 60, 3.0))
    with pytest.raises(ValueError, match="no grid points"):
        crop_bard.crop_files([f], NQN, tmp_path / "out")


def test_main_default_area_and_parse(tmp_path):
    f = tmp_path / "bard_1980-01.nc"
    make_bard(f, ["1980-01-01"], np.arange(-80, -60, 2.0), np.arange(-50, -20, 3.0))
    assert crop_bard.main(["--out", str(tmp_path / "o"), str(f)]) == 0
    assert (tmp_path / "o" / "bard_neuquen_1980.nc").exists()
    assert crop_bard.main([f"--area=-30,-72,-40,-68", "--out", str(tmp_path / "o2"), str(f)]) == 0
    ds = xr.open_dataset(tmp_path / "o2" / "bard_neuquen_1980.nc")
    assert ds.lon.values.max() <= -68 and ds.attrs["crop_area"] == "-30,-72,-40,-68"

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import xarray as xr

from clima_nqn.stages.ar import catalog

# Cell centers sit on a quarter-degree offset so none falls on the polygon edge.
LAT = -42.75 + 0.5 * np.arange(17)  # -42.75 .. -34.75, ascending
LON = -73.75 + 0.5 * np.arange(16)  # -73.75 .. -66.25
# Cells inside lon -71.95..-70.0, lat -41.1..-36.0: lon -71.75..-70.25 (4), lat -40.75..-36.25 (10)
N_INSIDE = 40
IN_LAT, IN_LON = -38.25, -70.75  # inside
OUT_LAT, OUT_LON = -34.75, -66.25  # outside


def make_mask():
    return catalog.polygon_mask(LAT, LON)


def make_bard(times, ar_cells):
    """BARD-like dataset. ``ar_cells``: {time: [(lat, lon, prob), ...]}."""
    times = pd.DatetimeIndex(times)
    prob = np.zeros((len(times), len(LAT), len(LON)), dtype="float32")
    for t, cells in ar_cells.items():
        i = times.get_loc(pd.Timestamp(t))
        for lat, lon, p in cells:
            prob[i, np.flatnonzero(LAT == lat)[0], np.flatnonzero(LON == lon)[0]] = p
    return xr.Dataset(
        {
            "ar_probability": (("time", "lat", "lon"), prob),
            "ar_binary_tag": (("time", "lat", "lon"), (prob >= 0.67).astype("int8")),
        },
        coords={"time": times, "lat": LAT, "lon": LON},
    )


def six_hourly(start, n):
    return pd.date_range(start, periods=n, freq="6h")


# --- polygon / mask ------------------------------------------------------------------------


def test_polygon_is_the_documented_rectangle():
    lons = [v[0] for v in catalog.CORDILLERA_POLYGON]
    lats = [v[1] for v in catalog.CORDILLERA_POLYGON]
    assert (min(lons), max(lons)) == (-71.95, -70.0)
    assert (min(lats), max(lats)) == (-41.1, -36.0)


def test_polygon_mask_known_cells():
    mask = make_mask()
    assert mask.dims == ("lat", "lon")
    assert int(mask.sum()) == N_INSIDE
    assert bool(mask.sel(lat=IN_LAT, lon=IN_LON))
    assert not bool(mask.sel(lat=OUT_LAT, lon=OUT_LON))
    # just outside each edge
    assert not bool(mask.sel(lat=-35.75, lon=IN_LON))
    assert not bool(mask.sel(lat=-41.25, lon=IN_LON))
    assert not bool(mask.sel(lat=IN_LAT, lon=-72.25))
    assert not bool(mask.sel(lat=IN_LAT, lon=-69.75))


def test_polygon_mask_non_rectangular_polygon():
    triangle = [(0.0, 0.0), (4.5, 0.0), (0.0, 4.5)]
    mask = catalog.polygon_mask(np.array([0.5, 1.5, 3.5]), np.array([0.5, 1.5, 3.5]), triangle)
    # (lat, lon): inside iff lon + lat < 4.5
    expected = np.array([[True, True, True], [True, True, False], [True, False, False]])
    np.testing.assert_array_equal(mask.values, expected)


# --- ar_steps ------------------------------------------------------------------------------


def test_ar_steps_values():
    times = six_hourly("2000-01-01", 3)
    ds = make_bard(
        times,
        {
            times[1]: [(IN_LAT, IN_LON, 0.9), (IN_LAT, -71.25, 0.7), (IN_LAT, -70.25, 0.5)],
        },
    )
    steps = catalog.ar_steps(ds, make_mask())
    assert list(steps.columns) == ["time", "prob_max", "area_frac", "is_ar"]
    assert list(steps["is_ar"]) == [False, True, False]
    assert steps["prob_max"].iloc[1] == pytest.approx(0.9)
    assert steps["area_frac"].iloc[1] == pytest.approx(2 / N_INSIDE)  # 0.9 and 0.7; 0.5 is below
    assert steps["prob_max"].iloc[0] == 0.0


def test_ar_outside_polygon_not_counted():
    times = six_hourly("2000-01-01", 2)
    ds = make_bard(times, {times[0]: [(OUT_LAT, OUT_LON, 1.0), (-42.75, -73.75, 1.0)]})
    steps = catalog.ar_steps(ds, make_mask())
    assert not steps["is_ar"].any()
    assert steps["prob_max"].max() == 0.0
    assert catalog.group_events(steps).empty


def test_ar_steps_threshold_is_inclusive_and_configurable():
    times = six_hourly("2000-01-01", 1)
    ds = make_bard(times, {times[0]: [(IN_LAT, IN_LON, 0.5)]})
    assert not catalog.ar_steps(ds, make_mask())["is_ar"].iloc[0]
    assert catalog.ar_steps(ds, make_mask(), threshold=0.5)["is_ar"].iloc[0]


def test_ar_steps_empty_mask_raises():
    ds = make_bard(six_hourly("2000-01-01", 1), {})
    empty = catalog.polygon_mask(LAT, LON, [(10.0, 10.0), (11.0, 10.0), (11.0, 11.0)])
    with pytest.raises(ValueError, match="no grid cell"):
        catalog.ar_steps(ds, empty)


# --- group_events --------------------------------------------------------------------------


def steps_from_flags(flags, start="2000-01-01", probs=None):
    times = six_hourly(start, len(flags))
    probs = probs if probs is not None else [0.9 if f else 0.0 for f in flags]
    return pd.DataFrame(
        {
            "time": times,
            "prob_max": probs,
            "area_frac": [0.1 if f else 0.0 for f in flags],
            "is_ar": flags,
        }
    )


def test_consecutive_steps_merge_and_gap_splits():
    steps = steps_from_flags([True, True, True, False, True, False, False])
    ev = catalog.group_events(steps)
    assert len(ev) == 2
    first, second = ev.iloc[0], ev.iloc[1]
    assert first["start"] == pd.Timestamp("2000-01-01 00:00")
    assert first["end"] == pd.Timestamp("2000-01-01 18:00")  # last step 12:00 + 6 h, exclusive
    assert first["duration_h"] == 18
    assert first["n_steps"] == 3
    assert second["start"] == pd.Timestamp("2000-01-02 00:00")
    assert second["end"] == pd.Timestamp("2000-01-02 06:00")
    assert second["duration_h"] == 6 and second["n_steps"] == 1


def test_max_gap_steps_bridges_one_step_only():
    steps = steps_from_flags([True, False, True, False, False, True])
    assert len(catalog.group_events(steps, max_gap_steps=0)) == 3
    bridged = catalog.group_events(steps, max_gap_steps=1)
    assert len(bridged) == 2
    assert bridged.iloc[0]["start"] == pd.Timestamp("2000-01-01 00:00")
    assert bridged.iloc[0]["end"] == pd.Timestamp("2000-01-01 18:00")
    assert bridged.iloc[0]["duration_h"] == 18
    assert bridged.iloc[0]["n_steps"] == 2  # AR steps only; the bridged step is not counted
    assert bridged.iloc[1]["start"] == pd.Timestamp("2000-01-02 06:00")


def test_event_prob_and_area_maxima():
    steps = steps_from_flags([True, True, False], probs=[0.7, 0.95, 0.2])
    steps["area_frac"] = [0.1, 0.3, 0.0]
    ev = catalog.group_events(steps)
    assert ev.iloc[0]["prob_max"] == pytest.approx(0.95)
    assert ev.iloc[0]["area_frac_max"] == pytest.approx(0.3)


def test_group_events_no_ar_is_empty_with_columns():
    ev = catalog.group_events(steps_from_flags([False, False]))
    assert ev.empty
    assert list(ev.columns) == [
        "start", "end", "duration_h", "n_steps", "prob_max", "area_frac_max",
    ]  # fmt: skip


# --- event_stats ---------------------------------------------------------------------------


def make_era5(start, hours, peak=None):
    """Hourly ERA5-like dataset with known values.

    Inside the polygon: tp 0.001 m/h, deg0l 2000 m, IVT 0. Outside: huge values that must be ignored.
    """
    times = pd.date_range(start, periods=hours, freq="h")
    shape = (hours, len(LAT), len(LON))
    mask = make_mask().values
    inside = np.broadcast_to(mask, shape)
    viwve = np.where(inside, 0.0, 900.0).astype("float32")
    viwvn = np.where(inside, 0.0, 900.0).astype("float32")
    tp = np.where(inside, 0.001, 5.0).astype("float32")
    deg0l = np.where(inside, 2000.0, 9000.0).astype("float32")
    if peak is not None:
        t, lat, lon, ve, vn = peak
        i = times.get_loc(pd.Timestamp(t))
        j, k = np.flatnonzero(LAT == lat)[0], np.flatnonzero(LON == lon)[0]
        viwve[i, j, k], viwvn[i, j, k] = ve, vn
    return xr.Dataset(
        {
            "viwve": (("time", "lat", "lon"), viwve),
            "viwvn": (("time", "lat", "lon"), viwvn),
            "tp": (("time", "lat", "lon"), tp),
            "deg0l": (("time", "lat", "lon"), deg0l),
        },
        coords={"time": times, "lat": LAT, "lon": LON},
    )


def one_event(start, end):
    return pd.DataFrame(
        {
            "start": [pd.Timestamp(start)],
            "end": [pd.Timestamp(end)],
            "duration_h": [(pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() / 3600],
            "n_steps": [1],
            "prob_max": [0.9],
            "area_frac_max": [0.1],
        }
    )


def test_event_stats_ivt_max_value_time_location():
    peak = ("2000-01-01 07:00", -39.75, -71.25, 300.0, 400.0)
    era5 = make_era5("2000-01-01", 48, peak=peak)
    # outside the polygon IVT is 900*sqrt(2) > 500 everywhere: it must not win
    out = catalog.event_stats(one_event("2000-01-01 06:00", "2000-01-01 18:00"), era5, make_mask())
    row = out.iloc[0]
    assert row["ivt_max"] == pytest.approx(500.0)
    assert row["ivt_max_time"] == pd.Timestamp("2000-01-01 07:00")
    assert row["ivt_max_lat"] == pytest.approx(-39.75)
    assert row["ivt_max_lon"] == pytest.approx(-71.25)


def test_event_stats_window_is_half_open():
    # peak exactly at the (exclusive) end hour is not part of the event
    era5 = make_era5("2000-01-01", 48, peak=("2000-01-01 18:00", IN_LAT, IN_LON, 600.0, 800.0))
    out = catalog.event_stats(one_event("2000-01-01 06:00", "2000-01-01 18:00"), era5, make_mask())
    assert out.iloc[0]["ivt_max"] == pytest.approx(0.0)


def test_event_stats_deg0l_and_tp_known_values():
    era5 = make_era5("2000-01-01", 48)
    era5["deg0l"][
        {
            "time": 8,
            "lat": np.flatnonzero(LAT == IN_LAT)[0],
            "lon": np.flatnonzero(LON == IN_LON)[0],
        }
    ] = 3000.0  # 2000-01-01 08:00
    era5["tp"][
        {
            "time": 9,
            "lat": np.flatnonzero(LAT == IN_LAT)[0],
            "lon": np.flatnonzero(LON == IN_LON)[0],
        }
    ] = 0.005  # +0.004 m on one cell
    out = catalog.event_stats(one_event("2000-01-01 06:00", "2000-01-01 18:00"), era5, make_mask())
    row = out.iloc[0]
    hours = 12
    assert row["deg0l_max"] == pytest.approx(3000.0)
    assert row["deg0l_mean"] == pytest.approx(2000.0 + 1000.0 / (hours * N_INSIDE))
    # 12 h * 1 mm everywhere + 4 mm on one of 40 cells
    assert row["tp_sum_mm"] == pytest.approx(12.0 + 4.0 / N_INSIDE, rel=1e-5)


def test_event_stats_keeps_event_columns():
    era5 = make_era5("2000-01-01", 48)
    out = catalog.event_stats(one_event("2000-01-01 06:00", "2000-01-01 18:00"), era5, make_mask())
    assert {"start", "end", "duration_h", "ivt_max", "ivt_max_time", "tp_sum_mm"} <= set(
        out.columns
    )


def test_event_stats_outside_era5_coverage_is_nan():
    era5 = make_era5("2000-01-01", 24)
    out = catalog.event_stats(one_event("2001-01-01 00:00", "2001-01-01 06:00"), era5, make_mask())
    assert np.isnan(out.iloc[0]["ivt_max"]) and np.isnan(out.iloc[0]["tp_sum_mm"])


# --- build_catalog / files -----------------------------------------------------------------


def write_year_files(tmp_path):
    """Two BARD years and two ERA5 years; one AR spans 1980-12-31 18:00 -> 1981-01-01 06:00."""
    bard_dir, era5_dir = tmp_path / "bard", tmp_path / "era5"
    bard_dir.mkdir()
    era5_dir.mkdir()
    cells = [(IN_LAT, IN_LON, 0.9)]
    t80 = pd.date_range("1980-12-30", "1980-12-31 18:00", freq="6h")
    t81 = pd.date_range("1981-01-01", "1981-01-02 18:00", freq="6h")
    ds80 = make_bard(t80, {pd.Timestamp("1980-12-31 18:00"): cells})
    ds81 = make_bard(t81, {pd.Timestamp("1981-01-01 00:00"): cells})
    ds81["ar_probability"].loc[{"time": "1981-01-02 06:00", "lat": IN_LAT, "lon": IN_LON}] = 0.8
    bard = [bard_dir / "bard_neuquen_1980.nc", bard_dir / "bard_neuquen_1981.nc"]
    ds80.to_netcdf(bard[0])
    ds81.to_netcdf(bard[1])

    peak = ("1981-01-01 02:00", -37.75, -70.75, 600.0, 800.0)  # |IVT| = 1000, in the 1981 file
    e80 = make_era5("1980-12-25", 7 * 24)
    e81 = make_era5("1981-01-01", 7 * 24, peak=peak)
    e80.to_zarr(era5_dir / "1980.zarr", consolidated=False)
    e81.to_zarr(era5_dir / "1981.zarr", consolidated=False)
    return bard, [era5_dir / "1980.zarr", era5_dir / "1981.zarr"]


def test_build_catalog_event_across_year_boundary(tmp_path):
    bard, era5 = write_year_files(tmp_path)
    df = catalog.build_catalog(bard, era5)
    assert list(df["event_id"]) == ["AR-1980-001", "AR-1981-001"]
    ev = df.iloc[0]
    assert ev["start"] == pd.Timestamp("1980-12-31 18:00")
    assert ev["end"] == pd.Timestamp("1981-01-01 06:00")
    assert ev["duration_h"] == 12 and ev["n_steps"] == 2
    assert ev["ivt_max"] == pytest.approx(1000.0)
    assert ev["ivt_max_time"] == pd.Timestamp("1981-01-01 02:00")
    assert ev["ivt_max_lat"] == pytest.approx(-37.75)
    assert ev["ivt_max_lon"] == pytest.approx(-70.75)
    # 12 h of 1 mm: hours before and after the year boundary both counted
    assert ev["tp_sum_mm"] == pytest.approx(12.0, rel=1e-5)
    assert ev["deg0l_max"] == pytest.approx(2000.0)
    second = df.iloc[1]
    assert second["start"] == pd.Timestamp("1981-01-02 06:00")
    assert second["prob_max"] == pytest.approx(0.8)


def test_event_id_format_and_numbering():
    events = pd.DataFrame(
        {"start": pd.to_datetime(["1980-03-01", "1980-07-01", "1981-02-01", "2025-12-31"])}
    )
    ids = catalog.assign_event_ids(events)
    assert list(ids) == ["AR-1980-001", "AR-1980-002", "AR-1981-001", "AR-2025-001"]


def test_build_catalog_enso_phase(tmp_path):
    bard, era5 = write_year_files(tmp_path)
    enso = pd.DataFrame(
        {
            "date": pd.to_datetime(["1980-12-01", "1981-01-01"]),
            "oni": [-0.9, 0.7],
            "phase": ["nina", "nino"],
        }
    )
    df = catalog.build_catalog(bard, era5, enso=enso)
    assert list(df["enso_phase"]) == ["nina", "nino"]  # phase of the start month
    assert catalog.build_catalog(bard, era5)["enso_phase"].isna().all()


def test_write_catalog_round_trip_with_metadata(tmp_path):
    bard, era5 = write_year_files(tmp_path)
    df = catalog.build_catalog(bard, era5, threshold=0.67, max_gap_steps=0)
    out = catalog.write_catalog(df, tmp_path / "ar" / "events.parquet", threshold=0.67)
    back = pd.read_parquet(out)
    pd.testing.assert_frame_equal(back, df, check_dtype=False)
    assert list(back.columns) == catalog.COLUMNS
    meta = {k.decode(): v.decode() for k, v in pq.read_schema(out).metadata.items()}
    assert meta["source"] == "ERA5 via ARCO-ERA5 + TECA BARD 6.0.0"
    assert meta["license"] == "CC-BY 4.0"
    assert meta["period"] == "1980-12-30/1981-01-02"
    assert meta["threshold"] == "0.67"
    assert "-71.95" in meta["polygon"] and "-41.1" in meta["polygon"]
    assert catalog.read_metadata(out)["license"] == "CC-BY 4.0"


def test_build_catalog_without_events(tmp_path):
    bard_dir = tmp_path / "bard"
    bard_dir.mkdir()
    ds = make_bard(six_hourly("1980-01-01", 4), {})
    ds.to_netcdf(bard_dir / "bard_neuquen_1980.nc")
    df = catalog.build_catalog([bard_dir / "bard_neuquen_1980.nc"], [])
    assert df.empty and list(df.columns) == catalog.COLUMNS
    out = catalog.write_catalog(df, tmp_path / "events.parquet")
    assert pd.read_parquet(out).empty


def test_event_stats_tp_window_is_start_exclusive_end_inclusive():
    """tp at stamp t accumulates (t-1h, t]: an event [06:00, 18:00) sums stamps 07:00..18:00."""
    era5 = make_era5("2000-01-01", 48)
    era5["tp"][:] = 0.0
    era5["tp"][{"time": 6}] = 1.0  # stamp 06:00 = rain in 05-06 h, before the event
    era5["tp"][{"time": 18}] = 0.002  # stamp 18:00 = rain in 17-18 h, last event hour
    out = catalog.event_stats(one_event("2000-01-01 06:00", "2000-01-01 18:00"), era5, make_mask())
    assert out.iloc[0]["tp_sum_mm"] == pytest.approx(2.0, rel=1e-5)

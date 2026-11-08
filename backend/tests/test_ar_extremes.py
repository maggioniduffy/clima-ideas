import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from clima_nqn.stages.ar import catalog, extremes

# Same grid as test_ar_catalog: 40 cells inside the polygon, one far outside.
LAT = -42.75 + 0.5 * np.arange(17)
LON = -73.75 + 0.5 * np.arange(16)
N_INSIDE = 40
RECT = catalog.LEGACY_RECTANGLE  # the synthetic grid is laid out around the old rectangle
OUT = (np.flatnonzero(LAT == -34.75)[0], np.flatnonzero(LON == -66.25)[0])
IN = (np.flatnonzero(LAT == -38.25)[0], np.flatnonzero(LON == -70.75)[0])


def make_store(tmp_path, year, values=None, stop=None, fill=0.0):
    """Hourly ``tp`` (m) store for ``year``; ``values``: {stamp: scalar or (ilat, ilon, v) list}."""
    end = pd.Timestamp(stop) if stop else pd.Timestamp(year + 1, 1, 1)
    times = pd.date_range(f"{year}-01-01", end, freq="h", inclusive="left")
    tp = np.full((len(times), len(LAT), len(LON)), fill, dtype="float32")
    for stamp, v in (values or {}).items():
        i = times.get_loc(pd.Timestamp(stamp))
        if isinstance(v, list):
            for ilat, ilon, x in v:
                tp[i, ilat, ilon] = x
        else:
            tp[i] = v
    ds = xr.Dataset(
        {"tp": (("time", "lat", "lon"), tp)}, coords={"time": times, "lat": LAT, "lon": LON}
    )
    path = tmp_path / f"{year}.zarr"
    ds.to_zarr(path, mode="w", consolidated=False)
    return path


# --- daily aggregation ---------------------------------------------------------------------


def test_daily_boundary_stamp_midnight_belongs_to_previous_day(tmp_path):
    p = make_store(
        tmp_path,
        2001,
        {"2001-03-10 00:00": 0.010, "2001-03-10 01:00": 0.002, "2001-03-11 00:00": 0.004},
    )
    mean, cells = extremes.daily_precip([p], RECT)
    assert mean[pd.Timestamp("2001-03-09")] == pytest.approx(10.0, rel=1e-5)
    assert mean[pd.Timestamp("2001-03-10")] == pytest.approx(6.0, rel=1e-5)  # 01:00 and next 00:00
    assert mean[pd.Timestamp("2001-03-11")] == pytest.approx(0.0)
    assert cells.shape == (len(mean), N_INSIDE)


def test_daily_cross_year_uses_next_store_and_drops_incomplete_last_day(tmp_path):
    a = make_store(tmp_path, 2001, {"2001-12-31 01:00": 0.003})
    # 2002-01-01 00:00 lives in the 2002 store
    b = make_store(
        tmp_path,
        2002,
        {"2002-01-01 00:00": 0.005, "2002-01-01 05:00": 0.001},
    )
    mean, _ = extremes.daily_precip([a, b], RECT)
    assert mean[pd.Timestamp("2001-12-31")] == pytest.approx(8.0, rel=1e-5)
    assert mean[pd.Timestamp("2002-01-01")] == pytest.approx(1.0, rel=1e-5)
    # 2002 store ends 2002-12-31 23:00 and there is no 2003 store: Dec 31 has 23 stamps
    assert mean.index[-1] == pd.Timestamp("2002-12-30")
    assert len(mean) == 365 + 364
    assert mean.index.is_monotonic_increasing


def test_daily_without_next_store_drops_dec_31_and_first_midnight_is_ignored(tmp_path):
    p = make_store(tmp_path, 2001, {"2001-01-01 00:00": 0.5})
    mean, _ = extremes.daily_precip([p], RECT)
    assert mean.index[0] == pd.Timestamp("2001-01-01")
    assert mean.index[-1] == pd.Timestamp("2001-12-30")
    assert mean.iloc[0] == pytest.approx(0.0)  # the 00:00 stamp is Dec 31 2000


def test_polygon_mean_ignores_outside_cells(tmp_path):
    p = make_store(
        tmp_path,
        2001,
        {"2001-03-10 02:00": [(OUT[0], OUT[1], 5.0), (IN[0], IN[1], 0.040)]},
    )
    mean, cells = extremes.daily_precip([p], RECT)
    day = pd.Timestamp("2001-03-10")
    assert mean[day] == pytest.approx(1.0, rel=1e-5)  # 40 mm in 1 of 40 cells
    assert cells.loc[day].max() == pytest.approx(40.0, rel=1e-5)
    assert (cells.loc[day] > 0).sum() == 1


# --- ar_days -------------------------------------------------------------------------------


def events_df(*pairs):
    return pd.DataFrame(
        {"start": [pd.Timestamp(a) for a, _ in pairs], "end": [pd.Timestamp(b) for _, b in pairs]}
    )


def test_ar_days_overlap_edges():
    days = pd.date_range("2001-03-08", periods=5)  # 8..12
    ev = events_df(("2001-03-09 18:00", "2001-03-10 00:00"))  # ends exactly at Mar 10 00:00
    got = extremes.ar_days(ev, days)
    assert list(got.index) == list(days)
    assert got.tolist() == [False, True, False, False, False]
    ev2 = events_df(("2001-03-11 00:00", "2001-03-11 06:00"))  # starts exactly at D 00:00
    assert extremes.ar_days(ev2, days).tolist() == [False, False, False, True, False]
    ev3 = events_df(("2001-03-10 12:00", "2001-03-11 00:00"))  # ends at the next midnight
    assert extremes.ar_days(ev3, days).tolist() == [False, False, True, False, False]


def test_ar_days_spanning_and_tolerance():
    days = pd.date_range("2001-03-08", periods=7)  # 8..14
    ev = events_df(("2001-03-10 06:00", "2001-03-11 18:00"))
    assert extremes.ar_days(ev, days).tolist() == [False, False, True, True, False, False, False]
    assert extremes.ar_days(ev, days, 1).tolist() == [False, True, True, True, True, False, False]
    # tolerance counts in whole days; an event ending at D 00:00 touches D with tolerance 1
    ev2 = events_df(("2001-03-09 18:00", "2001-03-10 00:00"))
    assert extremes.ar_days(ev2, days, 1).tolist() == [True, True, True, False, False, False, False]
    assert not extremes.ar_days(events_df(), days).any()


# --- stats ---------------------------------------------------------------------------------


def test_wilson_interval_known_value():
    lo, hi = extremes.wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3)
    assert hi == pytest.approx(0.7634, abs=1e-3)
    lo, hi = extremes.wilson_interval(0, 10)
    assert lo == 0.0 and 0.25 < hi < 0.31
    assert all(np.isnan(extremes.wilson_interval(0, 0)))


def test_coincidence_stats_constructed():
    precip = np.arange(200.0)
    ext = precip >= 190
    ar = np.zeros(200, bool)
    ar[195:200] = True
    ar[0:15] = True
    s = extremes.coincidence_stats(precip, ar, ext, 190.0)
    assert s["n_days"] == 200 and s["n_extreme"] == 10 and s["threshold_mm"] == 190.0
    assert s["n_extreme_with_ar"] == 5
    assert s["frac_extreme_with_ar"] == pytest.approx(0.5)
    assert s["base_rate"] == pytest.approx(0.1)
    assert s["ratio"] == pytest.approx(5.0)
    assert s["frac_extreme_precip_volume_with_ar"] == pytest.approx(985 / 1945)
    assert s["ci95_low"] == pytest.approx(0.2366, abs=1e-3)
    assert s["ci95_high"] == pytest.approx(0.7634, abs=1e-3)


def test_coincidence_stats_no_extreme_days():
    s = extremes.coincidence_stats(np.zeros(5), np.zeros(5, bool), np.zeros(5, bool), 1.0)
    assert s["n_extreme"] == 0
    assert np.isnan(s["frac_extreme_with_ar"]) and np.isnan(s["ratio"])


def test_coincidence_stats_seasons():
    days = pd.date_range("2001-01-01", periods=365)
    precip = np.zeros(365)
    ext = np.zeros(365, bool)
    ar = np.zeros(365, bool)
    for stamp, a in (("2001-01-10", True), ("2001-07-04", False), ("2001-07-20", True)):
        i = days.get_loc(pd.Timestamp(stamp))
        precip[i], ext[i], ar[i] = 50.0, True, a
    s = extremes.coincidence_stats(precip, ar, ext, 50.0, months=days.month.values)
    seasons = s["seasons"]
    assert list(seasons) == ["DJF", "MAM", "JJA", "SON"]
    assert sum(v["n_days"] for v in seasons.values()) == 365
    assert seasons["DJF"]["n_days"] == 31 + 28 + 31  # Jan, Feb and Dec of this one year
    assert seasons["DJF"]["n_extreme"] == 1 and seasons["DJF"]["n_extreme_with_ar"] == 1
    assert seasons["JJA"]["n_extreme"] == 2 and seasons["JJA"]["n_extreme_with_ar"] == 1
    assert seasons["JJA"]["frac_extreme_with_ar"] == pytest.approx(0.5)
    assert seasons["MAM"]["n_extreme"] == 0 and seasons["SON"]["n_extreme"] == 0
    assert seasons["JJA"]["threshold_mm"] == 50.0


# --- definitions ---------------------------------------------------------------------------


def constructed():
    days = pd.date_range("2000-01-01", periods=1000)
    vals = np.arange(1000) * 0.1
    cells = pd.DataFrame({0: vals, 1: vals}, index=days)
    d = lambda i, h=0: days[0] + pd.Timedelta(days=i, hours=h)
    ev = events_df(
        (d(995), d(1000)),
        (d(0), d(10)),
        (d(988, 12), d(989, 6)),
    )
    return cells.mean(axis=1), cells, ev


def test_main_p99_and_tolerance_definitions():
    mean, cells, ev = constructed()
    res = extremes.compute_results(mean, cells, ev)
    main = res["main"]
    assert main["n_days"] == 1000
    assert main["threshold_mm"] == pytest.approx(98.901)
    assert main["n_extreme"] == 10  # days 990..999
    assert main["n_extreme_with_ar"] == 5
    assert main["frac_extreme_with_ar"] == pytest.approx(0.5)
    assert main["base_rate"] == pytest.approx(0.017)
    assert main["ratio"] == pytest.approx(0.5 / 0.017)
    assert sum(v["n_days"] for v in main["seasons"].values()) == 1000
    p95 = res["p95"]
    assert p95["n_extreme"] == 50
    assert p95["threshold_mm"] == pytest.approx(94.905)
    tol = res["main_tol1"]
    assert tol["n_extreme"] == 10 and tol["n_extreme_with_ar"] == 7
    assert tol["base_rate"] == pytest.approx(0.021)
    assert tol["threshold_mm"] == main["threshold_mm"]


def test_per_cell_wet_day_p99_pooled():
    days = pd.date_range("2001-01-01", periods=300)
    wet = np.concatenate([np.zeros(100), np.arange(1.0, 201.0)])  # p99 of wet days = 198.01
    cells = pd.DataFrame({0: wet, 1: np.zeros(300)}, index=days)
    ar = pd.Series(False, index=days)
    ar.iloc[299] = True  # the 200 mm day
    s = extremes.per_cell_stats(cells, ar)
    assert s["n_cells"] == 1  # the all-dry cell is skipped
    assert s["n_days"] == 300
    assert s["threshold_mm"] == pytest.approx(198.01)
    assert s["n_extreme"] == 2  # 199 and 200 mm
    assert s["n_extreme_with_ar"] == 1
    assert s["frac_extreme_with_ar"] == pytest.approx(0.5)
    assert s["base_rate"] == pytest.approx(1 / 300)
    assert (
        s["seasons"]["DJF"]["n_days"]
        + s["seasons"]["MAM"]["n_days"]
        + s["seasons"]["JJA"]["n_days"]
        + s["seasons"]["SON"]["n_days"]
        == 300
    )


def test_per_cell_in_results():
    mean, cells, ev = constructed()
    res = extremes.compute_results(mean, cells, ev)
    pc = res["per_cell"]
    assert pc["n_cells"] == 2
    assert pc["n_days"] == 2 * 1000  # dry cell-days still count as days
    assert pc["n_extreme"] > 0


# --- report --------------------------------------------------------------------------------


def test_write_report_and_json(tmp_path):
    mean, cells, ev = constructed()
    res = extremes.compute_results(mean, cells, ev)
    meta = {
        "period": "2000-01-01/2002-09-26",
        "n_events": 3,
        "bard_threshold": 0.67,
        "polygon": [[-71.95, -36.0], [-70.0, -36.0], [-70.0, -41.1], [-71.95, -41.1]],
    }
    path = tmp_path / "out" / "F1.4.md"
    extremes.write_report(res, path, meta)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# F1.4 — Lluvia extrema y ríos atmosféricos (cordillera neuquina)")
    assert "CC-BY 4.0" in text and "TECA BARD 6.0.0" in text
    assert "sin verificar" in text
    assert "tasa base" in text.lower()
    assert "50.0 %" in text  # MAIN fraction
    assert "1.7 %" in text  # MAIN base rate
    assert "29.4" in text  # ratio 0.5 / 0.017
    assert "DJF" in text and "SON" in text
    assert "0.67" in text
    data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["results"]["main"]["n_extreme"] == 10
    assert data["meta"]["n_events"] == 3
    assert extremes.headline(res).startswith("MAIN")
    assert "50.0 %" in extremes.headline(res)

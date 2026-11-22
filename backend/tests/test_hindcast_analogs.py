"""F5.5 analogs: climatology, seasonal pool, exclusions, one-per-system, baseline, outcomes, layer (synthetic)."""

import itertools
import json

import numpy as np
import pandas as pd
import pytest

from clima_nqn.layers import hindcast_analogs as layer
from clima_nqn.layers.manifest import load_manifest
from clima_nqn.stages.hindcast import analogs as an


def _days(first="1980-01-01", last="1989-12-31"):
    return pd.date_range(first, last, freq="D")


def _library(seed=1, first="1980-01-01", last="1989-12-31", dim=12):
    dates = _days(first, last)
    rng = np.random.default_rng(seed)
    return dates, rng.normal(size=(len(dates), dim)).astype("float32")


def _pos(dates, day):
    return int(dates.get_loc(pd.Timestamp(day)))


# --- day of year and climatology ------------------------------------------------------------------


def test_doy365_ignores_leap_day():
    d = pd.to_datetime(
        ["2020-02-28", "2020-02-29", "2020-03-01", "2021-03-01", "2020-12-31", "2021-12-31"]
    )
    assert an.doy365(d).tolist() == [59, 59, 60, 60, 365, 365]


def test_climatology_window_mean_and_wrap():
    dates = _days("1981-01-01", "1983-12-31")  # three non-leap years
    doy = an.doy365(dates)
    clim = an.climatology(doy.astype("float64"), dates, half=15)
    assert clim[99] == pytest.approx(100.0)  # doy 100: symmetric window 85..115
    # doy 5 wraps: doys 355..365 and 1..20 -> mean of (355..365, 1..20)
    want = np.mean(list(range(355, 366)) + list(range(1, 21)))
    assert clim[4] == pytest.approx(want)


def test_anomaly_of_pure_seasonal_cycle_is_zero():
    dates = _days("1981-01-01", "1990-12-31")
    doy = an.doy365(dates)
    cycle = np.cos(2 * np.pi * doy / 365.0)
    vals = np.stack([cycle, 2 * cycle], axis=1)
    clim = an.climatology(vals, dates, half=0)  # no smoothing: exact cycle
    anom = an.anomalies(vals, dates, clim)
    assert np.abs(anom).max() < 1e-12
    # the +-15 day window smooths the cycle, so the anomaly is small but not zero
    smooth = an.anomalies(vals, dates, an.climatology(vals, dates, half=15))
    assert 0 < np.abs(smooth).max() < 0.2


def test_anomalies_remove_year_offset_mean():
    dates = _days("1981-01-01", "1985-12-31")
    vals = np.full((len(dates), 1), 5.0)
    anom = an.anomalies(vals, dates, an.climatology(vals, dates))
    assert np.allclose(anom, 0)


# --- seasonal pool and exclusion --------------------------------------------------------------------


def test_pool_excludes_15_days_around_target_only():
    dates = _days()
    t = pd.Timestamp("1985-07-10")
    pool = an.candidate_mask(dates, t)
    assert not pool[_pos(dates, "1985-07-10")]
    assert not pool[_pos(dates, "1985-06-25")]  # -15
    assert not pool[_pos(dates, "1985-07-25")]  # +15
    assert pool[_pos(dates, "1985-07-26")]  # +16
    assert pool[_pos(dates, "1985-06-24")]  # -16
    assert pool[_pos(dates, "1987-07-10")]  # same doy, another year
    assert not pool[_pos(dates, "1987-09-10")]  # 62 days away in doy


def test_seasonal_window_crosses_new_year():
    dates = _days()
    t = pd.Timestamp("1985-01-05")
    pool = an.candidate_mask(dates, t)
    assert pool[_pos(dates, "1983-12-20")]  # 16 days before Jan 5 across the year end
    assert pool[_pos(dates, "1987-12-06")]  # 30 days before
    assert not pool[_pos(dates, "1987-12-04")]  # 32 days before
    assert pool[_pos(dates, "1987-02-03")]  # 29 days after
    assert not pool[_pos(dates, "1987-02-10")]
    # and the mirror case: target in December sees January days
    t2 = pd.Timestamp("1985-12-28")
    pool2 = an.candidate_mask(dates, t2)
    assert pool2[_pos(dates, "1987-01-10")]
    assert not pool2[_pos(dates, "1987-02-20")]


# --- search ---------------------------------------------------------------------------------------------


def test_exact_synthetic_analog_ranks_first():
    dates, feat = _library()
    t = _pos(dates, "1985-07-10")
    twin = _pos(dates, "1988-07-02")
    feat[twin] = feat[t]
    out = an.find_analogs(feat, dates, t, k=10)
    assert out[0][0] == twin
    assert out[0][1] == pytest.approx(0.0, abs=1e-6)
    assert [d for _, d in out] == sorted(d for _, d in out)
    assert len(out) == 10


def test_close_copies_inside_exclusion_are_never_returned():
    dates, feat = _library()
    t = _pos(dates, "1985-07-10")
    for off in (-15, -3, 1, 15):
        feat[t + off] = feat[t]
    out = an.find_analogs(feat, dates, t, k=10)
    picked = {dates[p] for p, _ in out}
    assert all(abs((d - dates[t]).days) > 15 for d in picked)


def test_one_analog_per_system():
    dates, feat = _library()
    t = _pos(dates, "1985-07-10")
    a = _pos(dates, "1988-07-02")
    for off, noise in ((0, 0.0), (-3, 0.01), (2, 0.02), (3, 0.03)):  # all within +-3 of the best
        feat[a + off] = feat[t] + noise
    out = an.find_analogs(feat, dates, t, k=10)
    picked = sorted(dates[p] for p, _ in out)
    for x, y in itertools.pairwise(picked):
        assert (y - x).days > an.SEPARATION_DAYS
    assert dates[out[0][0]] == dates[a]
    assert dates[a + 3] not in picked and dates[a - 3] not in picked and dates[a + 2] not in picked


def test_nan_candidates_are_skipped_and_k_is_capped():
    dates, feat = _library(first="1980-01-01", last="1984-12-31")
    t = _pos(dates, "1982-07-10")
    feat[_pos(dates, "1983-07-10")] = np.nan
    out = an.find_analogs(feat, dates, t, k=10)
    assert all(np.isfinite(d) for _, d in out)
    assert dates[_pos(dates, "1983-07-10")] not in {dates[p] for p, _ in out}
    few = an.find_analogs(feat, dates, t, k=500)
    assert 0 < len(few) < 500


def test_target_must_be_in_library():
    dates, _ = _library()
    with pytest.raises(ValueError, match="library"):
        an.target_position(dates, pd.Timestamp("1970-01-01"))


# --- baseline ----------------------------------------------------------------------------------------------


def test_baseline_is_reproducible_and_respects_pool():
    dates, _ = _library()
    t = _pos(dates, "1985-01-05")
    a = an.baseline_days(dates, t, k=10, seed=an.BASELINE_SEED, salt=7)
    b = an.baseline_days(dates, t, k=10, seed=an.BASELINE_SEED, salt=7)
    c = an.baseline_days(dates, t, k=10, seed=an.BASELINE_SEED + 1, salt=7)
    d = an.baseline_days(dates, t, k=10, seed=an.BASELINE_SEED, salt=8)
    assert a == b and a != c and a != d
    pool = an.candidate_mask(dates, dates[t])
    assert len(a) == 10 and len(set(a)) == 10
    assert pool[a].all()
    picked = sorted(dates[p] for p in a)
    assert all((y - x).days > an.SEPARATION_DAYS for x, y in itertools.pairwise(picked))


def test_baseline_seed_is_the_decided_one():
    assert an.BASELINE_SEED == 20261122 and an.K == 10 and an.N_BOOT == 1000


# --- outcomes ----------------------------------------------------------------------------------------------


def _events():
    return pd.DataFrame(
        {
            "event_id": ["AR-A", "AR-B"],
            "start": pd.to_datetime(["2000-07-01 06:00", "2000-07-10 00:00"]),
            "end": pd.to_datetime(["2000-07-02 00:00", "2000-07-11 00:00"]),
        }
    )


def test_touching_event_uses_half_open_intervals_by_day():
    ev = _events()
    assert an.touching_event(pd.Timestamp("2000-07-01"), ev) == "AR-A"  # starts 06:00 that day
    assert an.touching_event(pd.Timestamp("2000-06-30"), ev) is None
    assert an.touching_event(pd.Timestamp("2000-07-02"), ev) is None  # end 00:00 exclusive
    assert an.touching_event(pd.Timestamp("2000-07-10"), ev) == "AR-B"
    assert an.touching_event(pd.Timestamp("2000-07-11"), ev) is None


def test_rain_outside_period_is_none():
    idx = pd.to_datetime(["2000-07-01", "2000-07-02"])
    table = pd.DataFrame(
        {"imerg_confluencia": [1.5, np.nan], "era5_confluencia": [2.0, 3.0]}, index=idx
    )
    got = an.rain_for_day(pd.Timestamp("2000-07-01"), table, ("confluencia",))
    assert got == {"confluencia": {"imerg": 1.5, "era5": 2.0}}
    got = an.rain_for_day(pd.Timestamp("2000-07-02"), table, ("confluencia",))
    assert got["confluencia"] == {"imerg": None, "era5": 3.0}
    got = an.rain_for_day(pd.Timestamp("1990-01-01"), table, ("confluencia",))
    assert got["confluencia"] == {"imerg": None, "era5": None}


def test_imerg_daily_regional_units_and_missing_steps():
    t = pd.date_range("2001-03-01", periods=96, freq="30min")
    lat, lon = np.array([-39.0, -38.9]), np.array([-68.0, -67.9])
    p = np.full((96, 2, 2), 2.0, dtype="float32")  # 2 mm/h for 24 h -> 48 mm
    p[60, :, :] = np.nan  # day 2 loses a step
    masks = {"confluencia": np.array([[True, False], [True, False]])}
    out = an.imerg_daily_regional(p, t, lat, lon, masks, chunk_steps=48)
    assert out.index.tolist() == [pd.Timestamp("2001-03-01"), pd.Timestamp("2001-03-02")]
    assert out.loc["2001-03-01", "confluencia_mm"] == pytest.approx(48.0)
    assert np.isnan(out.loc["2001-03-02", "confluencia_mm"])


# --- summary / bootstrap ---------------------------------------------------------------------------------------


def _event_record(i, ar_a, ar_b, rain_a, rain_b):
    return {
        "event_id": f"E{i}",
        "analog_summary": {
            "ar_fraction": ar_a,
            "rain": {"confluencia": {"imerg": rain_a, "era5": None}},
        },
        "baseline": {"ar_fraction": ar_b, "rain": {"confluencia": {"imerg": rain_b, "era5": None}}},
    }


def test_compare_is_deterministic_and_skips_missing():
    recs = [_event_record(i, 0.4, 0.1, 5.0 + i % 3, 2.0) for i in range(30)]
    recs.append(_event_record(99, 0.5, 0.2, None, None))
    s1 = an.compare(recs, ("confluencia",), n_boot=200, seed=0)
    s2 = an.compare(recs, ("confluencia",), n_boot=200, seed=0)
    assert s1 == s2
    ar = s1["ar_fraction"]
    assert ar["n_events"] == 31
    assert ar["analogs"] == pytest.approx((0.4 * 30 + 0.5) / 31, abs=1e-3)
    assert ar["diff_ci"][0] > 0
    rain = s1["rain"]["confluencia"]["imerg"]
    assert rain["n_events"] == 30
    assert rain["diff"] > 0 and rain["diff_ci"][0] > 0
    assert s1["rain"]["confluencia"]["era5"]["n_events"] == 0
    assert s1["rain"]["confluencia"]["era5"]["diff"] is None


# --- layer ----------------------------------------------------------------------------------------------------


def _payload():
    return {
        "k": 10,
        "period": "1980-01-01/2025-12-31",
        "regions": ["confluencia"],
        "method": {"distance": "euclidean on anomalies"},
        "summary": {"ar_fraction": {"analogs": 0.3, "baseline": 0.1}},
        "events": [
            {
                "event_id": "AR-1980-001",
                "date": "1980-02-11",
                "ivt_max": 881.8,
                "ivt_daily_max": 700.1,
                "analogs": [
                    {
                        "date": "1983-02-01",
                        "distance": 12.3,
                        "ar_event_id": None,
                        "ivt_max": 300.0,
                        "rain": {"confluencia": {"imerg": None, "era5": None}},
                    }
                ],
                "analog_summary": {"ar_fraction": 0.0, "rain": {}},
                "baseline": {"ar_fraction": 0.1, "rain": {}},
            }
        ],
    }


def test_layer_json_shape(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "analogs.json").write_text(json.dumps(_payload()), encoding="utf-8")
    out = layer.build(src / "analogs.json", tmp_path / "hindcast-analogs")
    m = load_manifest(out / "manifest.json")
    assert m.id == "hindcast-analogs" and m.kind == "series"
    assert m.files == ["analogs.json"]
    assert m.period == "1980-01-01/2025-12-31"
    assert m.source == "ERA5 (Copernicus) vía ARCO-ERA5; IMERG Final V07 (NASA)"
    assert m.license == "CC BY 4.0"
    data = json.loads((out / "analogs.json").read_text(encoding="utf-8"))
    ev = data["events"][0]
    assert {"event_id", "date", "ivt_max", "analogs", "baseline"} <= set(ev)
    assert {"date", "distance", "ar_event_id", "ivt_max", "rain"} <= set(ev["analogs"][0])
    assert data["source"] == m.source and data["period"] == m.period


def test_layer_rejects_nan_and_missing_keys(tmp_path):
    bad = _payload()
    bad["events"][0]["ivt_max"] = float("nan")
    p = tmp_path / "a.json"
    p.write_text(json.dumps(bad), encoding="utf-8")  # json.dumps writes NaN
    with pytest.raises(ValueError):
        layer.build(p, tmp_path / "o1")
    bad = _payload()
    del bad["events"][0]["analogs"]
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="analogs"):
        layer.build(p, tmp_path / "o2")


def test_uncovered_imerg_regions_are_dropped():
    cov = {"cordillera_norte": 0.02, "cordillera_sur": 0.0, "confluencia": 1.0}
    assert an.imerg_usable(cov) == {
        "cordillera_norte": False,
        "cordillera_sur": False,
        "confluencia": True,
    }
    idx = pd.to_datetime(["2005-01-01"])
    table = pd.DataFrame({f"imerg_{r}": [1.0] for r in an.REGIONS}, index=idx)
    table["era5_cordillera_norte"] = 2.0
    kept = an.drop_uncovered_imerg(table, cov)
    assert list(kept.columns) == ["imerg_confluencia", "era5_cordillera_norte"]
    got = an.rain_for_day(idx[0], kept)
    assert got["cordillera_norte"] == {"imerg": None, "era5": 2.0}
    assert got["confluencia"]["imerg"] == 1.0

import numpy as np
import pandas as pd
import pytest

from clima_nqn.stages.convection import bias


def half_hourly(start: str, n: int, value) -> pd.Series:
    idx = pd.date_range(start, periods=n, freq="30min")
    return pd.Series(
        value(np.arange(n)) if callable(value) else np.full(n, value, dtype=float), index=idx
    )


def test_window_totals_aligns_start_times_and_units():
    # 1 mm/h constant: any 6 h window is 6 mm
    rate = half_hourly("2020-01-01 00:00", 96, 1.0)
    ends = pd.DatetimeIndex(["2020-01-01 06:00", "2020-01-02 00:00"])
    out = bias.window_totals(rate, ends, 6)
    assert out == pytest.approx([6.0, 6.0])


def test_window_totals_uses_half_open_window_start_labelled():
    # rate = step index in mm/h; window [06:00, 12:00) = steps 12..23 -> sum(12..23) * 0.5
    rate = half_hourly("2020-01-01 00:00", 96, lambda i: i.astype(float))
    out = bias.window_totals(rate, pd.DatetimeIndex(["2020-01-01 12:00"]), 6)
    assert out[0] == pytest.approx(sum(range(12, 24)) * 0.5)
    # step 24 (12:00-12:30) is excluded, step 11 (05:30-06:00) too: a shifted end changes the sum
    shifted = bias.window_totals(rate, pd.DatetimeIndex(["2020-01-01 12:30"]), 6)
    assert shifted[0] == pytest.approx(sum(range(13, 25)) * 0.5)


def test_window_totals_incomplete_or_misaligned_is_nan():
    rate = half_hourly("2020-01-01 00:00", 96, 1.0)
    rate.iloc[20] = np.nan  # a missing half hour inside the first window
    ends = pd.DatetimeIndex(
        ["2020-01-01 12:00", "2020-01-01 18:00", "2020-01-01 06:10", "2020-01-01 03:00"]
    )
    out = bias.window_totals(rate, ends, 6)
    assert np.isnan(out[0])  # NaN inside [06:00, 12:00)
    assert out[1] == pytest.approx(6.0)
    assert np.isnan(out[2])  # not on a half-hour boundary
    assert np.isnan(out[3])  # window starts before the series


def test_build_pairs_keeps_full_windows_only():
    rate = half_hourly("2020-01-01 00:00", 96, 2.0)  # 2 mm/h
    station = pd.DataFrame(
        {
            "time": pd.to_datetime(["2020-01-01 12:00", "2020-01-01 03:00", "2020-01-03 12:00"]),
            "period_h": 6,
            "depth_mm": [10.0, 1.0, 5.0],
        }
    )
    pairs = bias.build_pairs(station, rate, rate * 0.5, 6)
    assert len(pairs) == 1  # 03:00 starts before the series, next-day 12:00 is past its end
    assert pairs.loc[0, "imerg"] == pytest.approx(12.0)
    assert pairs.loc[0, "imerg9"] == pytest.approx(6.0)
    assert pairs.loc[0, "station"] == 10.0


def test_total_ratio_pod_far_and_bootstrap_is_seeded():
    pairs = pd.DataFrame(
        {
            "station": [10.0, 20.0, 0.0, 5.0, 0.2],
            "imerg": [5.0, 10.0, 3.0, 0.0, 0.0],
            "imerg9": [5.0, 10.0, 3.0, 0.0, 0.0],
            "year": [2000, 2000, 2001, 2001, 2002],
        }
    )
    m = bias.pair_metrics(pairs)
    assert (m["hits"], m["misses"], m["false_alarms"]) == (2, 1, 1)
    assert m["pod"] == pytest.approx(2 / 3)
    assert m["far"] == pytest.approx(1 / 3)
    assert m["ratio"] == pytest.approx(0.5)
    assert m["years"] == 3
    x, y = np.array([5.0, 10.0, 7.0, 3.0]), np.array([10.0, 20.0, 8.0, 4.0])
    assert bias.bootstrap_ratio_ci(x, y) == bias.bootstrap_ratio_ci(x, y)
    lo, hi = bias.bootstrap_ratio_ci(x, y)
    assert lo <= bias.total_ratio(x, y) <= hi


def test_quantile_mapping_recovers_known_monotone_transform():
    rng = np.random.default_rng(1)

    def transform(v):
        return 2.0 * v**1.1

    imerg_fit = 1.0 + rng.gamma(2.0, 6.0, 20000)
    station_fit = transform(1.0 + rng.gamma(2.0, 6.0, 20000))  # independent sample: marginals only
    qm = bias.fit_qm(imerg_fit, station_fit)
    probe = np.quantile(imerg_fit, [0.1, 0.25, 0.5, 0.75, 0.9])
    assert bias.apply_qm(qm, probe) == pytest.approx(transform(probe), rel=0.04)


def test_quantile_mapping_extrapolates_by_constant_ratio():
    qm = bias.fit_qm(
        np.linspace(1, 10, 200),
        np.linspace(2, 40, 200),
        n_quantiles=20,
        lower_prob=0.0,
        upper_prob=1.0,
    )
    hi, lo = qm.ratio_high, qm.ratio_low
    assert hi == pytest.approx(4.0) and lo == pytest.approx(2.0)
    out = bias.apply_qm(qm, np.array([20.0, 50.0, 0.5, 0.0]))
    assert out == pytest.approx(
        [80.0, 200.0, 1.0, 0.0]
    )  # above range x4, below range x2, zero stays zero
    # monotone non-decreasing everywhere
    grid = np.linspace(0, 60, 500)
    assert np.all(np.diff(bias.apply_qm(qm, grid)) >= -1e-9)


def test_quantile_mapping_rejects_tiny_samples():
    with pytest.raises(ValueError):
        bias.fit_qm(np.array([1.0]), np.array([1.0, 2.0]))


def test_baseline_factor_is_inverse_total_ratio():
    imerg, station = np.array([1.0, 2.0, 3.0]), np.array([2.0, 4.0, 6.0])
    assert bias.total_ratio(imerg, station) == pytest.approx(0.5)
    f = bias.fit_factor(imerg, station)
    assert f == pytest.approx(2.0)
    assert bias.apply_factor(f, imerg) == pytest.approx(station)
    with pytest.raises(ValueError):
        bias.fit_factor(np.zeros(3), station)


def test_leave_one_year_out_never_trains_on_the_held_out_year():
    rng = np.random.default_rng(2)
    n = 400
    imerg = rng.gamma(2.0, 5.0, n)
    pairs = pd.DataFrame(
        {"imerg": imerg, "station": imerg * 1.25, "year": np.repeat(np.arange(2000, 2008), n // 8)}
    )
    # a year with an absurd bias must not leak into its own correction
    pairs.loc[pairs["year"] == 2003, "station"] *= 50
    oof = bias.leave_one_year_out(pairs)
    held = oof.loc[oof["year"] == 2003]
    wet = held["imerg"] >= bias.WET_MM
    assert (held.loc[wet, "factor"] / held.loc[wet, "imerg"]).median() == pytest.approx(
        1.25, rel=0.02
    )


def test_corroborate_p24_flags():
    t = pd.Timestamp("2014-04-07 12:00")
    p6 = pd.DataFrame(
        {
            "time": [t - pd.Timedelta(hours=h) for h in (18, 12, 6, 0)],
            "depth_mm": [10.0, 20.0, 30.0, 59.0],
        }
    )
    p24 = pd.DataFrame(
        {
            "time": [
                t,
                t + pd.Timedelta(days=1),
                t + pd.Timedelta(days=2),
                t + pd.Timedelta(days=3),
            ],
            "depth_mm": [118.0, 118.0, 300.0, 120.0],
        }
    )
    p6_extra = pd.concat(
        [
            p6,
            pd.DataFrame({"time": [t + pd.Timedelta(days=3, hours=-18)], "depth_mm": [1.0]}),
        ]
    )
    flags = bias.corroborate_p24(p24, p6_extra)["flag"].tolist()
    assert flags == ["corroborated", "unchecked", "implausible", "unchecked"]
    p6_bad = p6.assign(depth_mm=[0.0, 0.0, 0.0, 0.0])
    assert bias.corroborate_p24(p24.iloc[:1], p6_bad)["flag"].item() == "inconsistent"

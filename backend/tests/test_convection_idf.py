import math

import numpy as np
import pandas as pd
import pytest

from clima_nqn.stages.convection import idf


def gev_sample(xi, alpha, k, n, seed):
    u = np.random.default_rng(seed).uniform(size=n)
    T = 1 / (1 - u)
    return np.asarray(idf.gev_quantile((xi, alpha, k), T))


@pytest.mark.parametrize("k", [-0.15, 0.0, 0.1])
def test_gev_lmom_recovers_parameters(k):
    true = (30.0, 8.0, k)
    x = gev_sample(*true, n=200_000, seed=1)
    xi, alpha, kk = idf.fit_gev_lmom(x)
    assert xi == pytest.approx(true[0], abs=0.3)
    assert alpha == pytest.approx(true[1], rel=0.03)
    assert kk == pytest.approx(k, abs=0.02)
    for T in (10, 100):
        assert idf.gev_quantile((xi, alpha, kk), T) == pytest.approx(
            idf.gev_quantile(true, T), rel=0.02
        )


def test_gev_return_period_inverts_quantile():
    p = (30.0, 8.0, -0.1)
    for T in (2, 10, 100):
        assert idf.gev_return_period(p, idf.gev_quantile(p, T)) == pytest.approx(T)
    assert idf.gev_return_period((0, 1, 0.5), 10.0) == math.inf  # beyond upper bound (k > 0)


def test_gumbel_mom_closed_form():
    x = np.array([10.0, 20.0, 30.0, 40.0])
    beta = np.std(x, ddof=1) * math.sqrt(6) / math.pi
    mu = 25.0 - 0.5772156649015329 * beta
    assert idf.fit_gumbel_mom(x) == pytest.approx((mu, beta))
    # T=2 -> -ln(-ln 0.5); T=100 -> -ln(-ln 0.99)
    assert idf.gumbel_quantile((mu, beta), 2) == pytest.approx(mu + beta * 0.3665129205816643)
    assert idf.gumbel_quantile((mu, beta), 100) == pytest.approx(mu + beta * 4.600149226776)
    assert idf.gumbel_return_period(
        (mu, beta), idf.gumbel_quantile((mu, beta), 25)
    ) == pytest.approx(25)


def test_weibull_positions():
    xs, Ts = idf.weibull_positions(np.array([3.0, 1.0, 2.0]))
    assert list(xs) == [1.0, 2.0, 3.0]
    assert Ts == pytest.approx([4 / 3, 2.0, 4.0])
    assert idf.empirical_quantile(np.array([3.0, 1.0, 2.0]), 2) == pytest.approx(2.0)
    assert math.isnan(idf.empirical_quantile(np.array([3.0, 1.0, 2.0]), 10))


def test_hydro_year_assignment():
    idx = pd.DatetimeIndex(
        ["2000-06-30 23:30", "2000-07-01 00:00", "2001-06-30 23:30", "2001-07-01"]
    )
    assert list(idf.hydro_year(idx)) == [1999, 2000, 2000, 2001]


def _half_hourly(start, end, values_at):
    idx = pd.date_range(start, end, freq="30min", inclusive="left")
    s = pd.Series(0.0, index=idx)
    for ts, v in values_at.items():
        s[pd.Timestamp(ts)] = v
    return s


def test_annual_maxima_hand_computed():
    # two complete hydro years (2000, 2001) + an incomplete tail (2002)
    s = _half_hourly("2000-07-01", "2003-01-01", {})
    s["2000-12-10 10:00"] = 1.0
    s["2000-12-10 10:30"] = 3.0
    s["2000-12-10 11:00"] = 2.0  # best 1 h = 3+2 = 5 (10:30-11:00); best 30 min = 3; 2 h = 6
    s["2000-12-10 11:30"] = 0.0
    s["2001-12-05 00:00"] = 4.0
    s["2001-12-05 00:30"] = 4.0
    s["2001-12-05 12:00"] = 1.0  # 24 h window holds all three = 9
    s["2002-08-01"] = 99.0  # in incomplete year 2002 -> ignored
    am = idf.annual_maxima(s, durations=(0.5, 1, 2, 24))
    assert list(am.index) == [2000, 2001]
    assert am.attrs["dropped_years"] == [2002]
    assert am.loc[2000].tolist() == [3.0, 5.0, 6.0, 6.0]
    assert am.loc[2001].tolist() == [4.0, 8.0, 8.0, 9.0]


def test_annual_maxima_window_does_not_cross_year_boundary():
    s = _half_hourly("2000-07-01", "2002-07-01", {})
    s["2001-06-30 23:30"] = 5.0
    s["2001-07-01 00:00"] = 5.0  # would be 10 mm/1 h if windows crossed the boundary
    am = idf.annual_maxima(s, durations=(1,))
    assert am.loc[2000, 1] == 5.0 and am.loc[2001, 1] == 5.0


def test_annual_maxima_drops_year_with_gap():
    s = _half_hourly("2000-07-01", "2002-07-01", {})
    s = s.drop(pd.Timestamp("2000-09-01"))
    assert list(idf.annual_maxima(s, durations=(1,)).index) == [2001]


def test_idf_table_synthetic_and_consistency():
    rng = np.random.default_rng(3)
    base = gev_sample(30.0, 8.0, -0.1, 40, seed=4)
    am = pd.DataFrame(
        {d: base * (d**0.4) * rng.uniform(0.99, 1.01, 40) for d in (0.5, 1, 2, 6, 24)}
    )
    am.columns = [0.5, 1.0, 2.0, 6.0, 24.0]
    t = idf.idf_table(am, n_boot=100, seed=1)
    assert set(t.method) == {"gev_lmom", "gumbel_mom", "empirical_weibull"}
    g = t[(t.method == "gev_lmom") & (t.return_period_yr == 10) & (t.duration_h == 24)].iloc[0]
    assert g.ci_low < g.depth_mm < g.ci_high
    assert g.intensity_mm_h == pytest.approx(g.depth_mm / 24)
    assert not g.extrapolated
    assert t[(t.return_period_yr == 100)].extrapolated.all()  # 100 > 2*40
    assert not t[(t.return_period_yr == 100)].method.eq("empirical_weibull").any()  # n+1 = 41 < 100
    assert idf.consistency_violations(t[t.method != "empirical_weibull"]) == []
    assert t.attrs["bias_correction"] == "none"


def test_idf_table_correction_hook_scales_depths():
    base = gev_sample(30.0, 8.0, -0.1, 40, seed=5)
    am = pd.DataFrame({1.0: base})
    a = idf.idf_table(am, n_boot=50, seed=1)
    b = idf.idf_table(am, n_boot=50, seed=1, correction=lambda d: d * 1.5)
    ka = a[(a.method == "gev_lmom") & (a.return_period_yr == 10)].depth_mm.iloc[0]
    kb = b[(b.method == "gev_lmom") & (b.return_period_yr == 10)].depth_mm.iloc[0]
    assert kb == pytest.approx(1.5 * ka)
    assert b.attrs["bias_correction"] == "user-supplied"


def test_consistency_violation_is_reported():
    t = pd.DataFrame(
        {
            "method": "gev_lmom",
            "return_period_yr": 10.0,
            "duration_h": [1.0, 2.0],
            "depth_mm": [20.0, 15.0],
            "intensity_mm_h": [20.0, 7.5],
        }
    )
    assert [v["kind"] for v in idf.consistency_violations(t)] == ["depth_decreases"]

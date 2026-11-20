"""F3.6 convection-by-ENSO helpers (no network, synthetic data)."""

import numpy as np
import pandas as pd

from clima_nqn.stages.ar import enso as ar_enso
from clima_nqn.stages.convection import enso as ce


def _steps(start: str, days: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=48 * days, freq="30min")


def test_local_day_boundary_utc_minus_3():
    # UTC days 2001-01-01..2001-01-03; local days start at 03:00 UTC.
    t = _steps("2001-01-01 00:00", 3)
    x = np.zeros(len(t))
    # 02:30 UTC = 23:30 local on Dec 31 -> belongs to local 2000-12-31 (incomplete day, dropped)
    # 03:00 UTC = 00:00 local on Jan 1 -> local 2001-01-01
    x[t.get_loc(pd.Timestamp("2001-01-01 03:00"))] = 4.0
    x[t.get_loc(pd.Timestamp("2001-01-01 02:30"))] = 10.0
    # 02:30 UTC Jan 2 = 23:30 local Jan 1
    x[t.get_loc(pd.Timestamp("2001-01-02 02:30"))] = 6.0
    days, total, m1h = ce.local_daily(x, t)
    assert list(days) == [pd.Timestamp("2001-01-01"), pd.Timestamp("2001-01-02")]
    # Jan 1 local: 4 + 6 mm/h half-hours -> (4+6)*0.5 = 5 mm; the 10 mm/h belongs to Dec 31 local
    assert total[0, 0] == 5.0
    assert total[1, 0] == 0.0
    assert m1h[0, 0] == 3.0  # isolated half-hours: (4+0)/2 vs (0+6)/2 -> 3


def test_rolling_one_hour_max_and_no_cross_day():
    t = _steps("2001-01-01 03:00", 2)  # exactly local Jan 1 and Jan 2
    x = np.zeros(len(t))
    x[10], x[11] = 8.0, 4.0  # adjacent -> 1 h mean 6
    x[47], x[48] = 20.0, 20.0  # straddles midnight: must not form a window
    _days, _total, m1h = ce.local_daily(x, t)
    assert m1h[0, 0] == 10.0  # in-day windows: (8,4)=6 and (0,20)=10
    assert m1h[1, 0] == 10.0  # (20,0)
    # without the straddling pair the in-day max is 6
    x2 = np.zeros(len(t))
    x2[10], x2[11] = 8.0, 4.0
    _, _, m2 = ce.local_daily(x2, t)
    assert m2[0, 0] == 6.0


def test_incomplete_and_nan_days_dropped():
    t = _steps("2001-01-01 03:00", 3)
    x = np.ones(len(t))
    x[100] = np.nan  # third local day (Jan 3)
    keep = np.ones(len(t), bool)
    keep[5] = False  # missing step in day 1
    days, total, _ = ce.local_daily(x[keep], t[keep])
    assert list(days) == [pd.Timestamp("2001-01-02")]
    assert total[0, 0] == 24.0


def test_season_assignment_december_year():
    days = pd.DatetimeIndex(["2000-12-15", "2001-01-10", "2001-02-28", "2001-04-01", "2001-10-02"])
    season, year = ce.season_of(days)
    assert list(season) == ["DJF", "DJF", "DJF", "", "SON"]
    assert list(year) == [2000, 2000, 2000, 2001, 2001]
    assert ce.expected_days("DJF", 2000) == 31 + 31 + 28  # Dec 2000, Jan, Feb 2001
    assert ce.expected_days("DJF", 2003) == 31 + 31 + 29  # Feb 2004 leap
    assert ce.expected_days("SON", 2000) == 91
    assert ce.oni_year("DJF", 2000) == 2001


def test_season_counts_and_phase():
    enso = pd.DataFrame(
        {
            "date": pd.to_datetime(["2000-09-01", "2000-10-01", "2000-11-01"]),
            "oni": [1.0, 1.2, 1.4],
        }
    )
    days = pd.date_range("2000-09-01", "2000-11-30")
    extreme = np.zeros(len(days), bool)
    extreme[[3, 10]] = True
    table, dropped = ce.season_counts(days, extreme, enso, 2000, 2000)
    assert dropped == ["DJF 2000"]
    assert table.loc[0, "n_extreme_days"] == 2
    assert table.loc[0, "phase"] == "nino"
    assert ar_enso.seasonal_oni(enso, "SON", 2000)[1] == "nino"


def _table(counts_a, counts_b, phase_a="nino", phase_b="nina"):
    rows = [{"season": "SON", "phase": phase_a, "n_extreme_days": c} for c in counts_a]
    rows += [{"season": "SON", "phase": phase_b, "n_extreme_days": c} for c in counts_b]
    return pd.DataFrame(rows)


def test_permutation_strong_difference():
    table = _table([6, 7, 8, 9, 7, 8, 6, 9], [0, 0, 1, 0, 0, 1, 0, 0])
    res = next(
        r
        for r in ce.compare_phases(table, 2000, 0)
        if r["season"] == "SON" and r["pair"] == "nino-nina"
    )
    assert res["diff"] > 6
    assert res["p"] < 0.01
    assert not res["small_n"]


def test_permutation_no_difference_and_small_n():
    table = _table([1, 0, 2, 1, 0, 1], [1, 0, 2, 1, 0, 1])
    res = next(
        r
        for r in ce.compare_phases(table, 2000, 0)
        if r["season"] == "SON" and r["pair"] == "nino-nina"
    )
    assert res["diff"] == 0
    assert res["p"] > 0.9
    small = _table([5, 6, 7], [0, 0, 0])
    r2 = next(
        r
        for r in ce.compare_phases(small, 500, 0)
        if r["season"] == "SON" and r["pair"] == "nino-nina"
    )
    assert r2["small_n"]


def test_wet_quantile_uses_wet_days_only():
    total = np.array([0.0, 0.5, 2.0, 3.0, 4.0])
    m1h = np.array([100.0, 100.0, 1.0, 2.0, 3.0])
    thr, n = ce.wet_quantile(m1h, total, 1.0)
    assert n == 3 and thr == 3.0


def test_per_season_thresholds_differ_and_spot_check():
    rng = np.random.default_rng(1)
    days = pd.date_range("2000-09-01", "2001-02-28")  # SON 2000 + DJF 2000
    n = len(days)
    season, _ = ce.season_of(days)
    max1h = np.where(season == "SON", rng.gamma(2, 6, n), rng.gamma(2, 1.5, n))[:, None]
    total = np.full((n, 1), 5.0)
    enso = pd.DataFrame({"date": pd.to_datetime(["2000-10-01", "2001-01-01"]), "oni": [1.0, 1.0]})
    pooled = ce.build_variant(days, total, max1h, 0, enso, ce.VARIANTS["main"], 100, 0)
    per = ce.build_variant(days, total, max1h, 0, enso, ce.VARIANTS["seas_p99"], 100, 0)
    t = per["threshold_mmh"]
    assert t["SON"] > t["DJF"]
    assert pooled["n_extreme_days_by_season"]["DJF"] == 0
    assert per["n_extreme_days_by_season"]["DJF"] >= 1
    sc = ce.phase_spotcheck(
        pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2015-12-01",
                        "2016-01-01",
                        "2016-02-01",
                        "2010-12-01",
                        "2011-01-01",
                        "2011-02-01",
                    ]
                ),
                "oni": [2.6, 2.5, 2.2, -1.5, -1.4, -1.2],
            }
        )
    )
    assert [c["phase"] for c in sc] == ["nino", "nina"]

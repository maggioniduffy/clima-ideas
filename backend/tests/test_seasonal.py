"""F6.2 seasonal model: leak-free partitions, availability at issue, terciles from training, scores."""

import numpy as np
import pandas as pd
import pytest

from clima_nqn.stages.seasonal import data, folds, model, score


def _samples(first="1980-05-01", last="2025-12-01", leads=range(1, 7)):
    issues = pd.date_range(first, last, freq="MS")
    iss = np.repeat(issues.values, len(leads))
    lead = np.tile(np.array(list(leads)), len(issues))
    tm = folds.target_month_start(iss, lead)
    return pd.DatetimeIndex(iss), lead, tm


def test_target_month_lead1_is_issue_month():
    iss, lead, tm = _samples("2000-03-01", "2000-03-01")
    assert tm[0] == pd.Timestamp("2000-03-01") and tm[-1] == pd.Timestamp("2000-08-01")


def test_hydro_year():
    assert list(folds.hydro_year(pd.to_datetime(["2000-03-01", "2000-04-01", "2001-01-01"]))) == [1999, 2000, 2000]


def test_outer_folds_no_test_or_gap_date_in_training():
    iss, lead, tm = _samples()
    for f in folds.outer_folds(iss, tm, range(1981, 2025)):
        start, end = pd.Timestamp(f.test_year, 4, 1), pd.Timestamp(f.test_year + 1, 4, 1)
        lo, hi = start - pd.DateOffset(months=6), end + pd.DateOffset(months=6)
        assert len(set(f.train) & set(f.test)) == 0 and len(set(f.train) & set(f.gap)) == 0
        # test samples are exactly the issues of the hydro year
        assert ((iss[f.test] >= start) & (iss[f.test] < end)).all()
        assert len(f.test) == ((iss >= start) & (iss < end)).sum()
        # no training issue date and no training target month inside the zone (spill past March included)
        ti, tt = iss[f.train], tm[f.train]
        assert not ((ti >= lo) & (ti < hi)).any()
        tt_end = tt + pd.offsets.MonthBegin(1)
        assert not ((tt_end > lo) & (tt < hi)).any()
        # the test targets (up to August) are not in training either
        assert set(tm[f.test]).isdisjoint(set(tm[f.train]))
        assert len(f.train) + len(f.test) + len(f.gap) == len(iss)


def test_inner_folds_only_outer_training_years_and_strictly_before():
    iss, lead, tm = _samples()
    f = folds.outer_folds(iss, tm, [2000])[0]
    inner = folds.inner_folds(iss, tm, f.train, min_years=15, block_years=5)
    assert inner
    train_set = set(f.train)
    test_years = set(folds.hydro_year(iss[f.test]))
    for tr, va in inner:
        assert set(tr) <= train_set and set(va) <= train_set  # nothing outside outer training
        assert set(tr).isdisjoint(f.test) and set(va).isdisjoint(f.test)
        assert not test_years & set(folds.hydro_year(iss[va]))
        val_start = iss[va].min()
        assert (iss[tr] < val_start).all()
        assert ((tm[tr] + pd.offsets.MonthBegin(1)) <= val_start).all()
        assert len(set(folds.hydro_year(iss[tr]))) >= 15 - 1  # first block validates the 16th year onwards
        assert set(tr).isdisjoint(va)


def test_inner_first_block_has_min_years():
    iss, lead, tm = _samples()
    f = folds.outer_folds(iss, tm, [2010])[0]
    tr, va = folds.inner_folds(iss, tm, f.train, min_years=15, block_years=5)[0]
    yrs = np.unique(folds.hydro_year(iss[f.train]))
    assert set(folds.hydro_year(iss[va])) == set(yrs[15:20])


def test_rolling_origin_trains_strictly_before():
    iss, lead, tm = _samples()
    for f in folds.rolling_origin(iss, tm, range(1995, 2025)):
        start = pd.Timestamp(f.test_year, 4, 1)
        assert (iss[f.train] < start).all()
        assert ((tm[f.train] + pd.offsets.MonthBegin(1)) <= start).all()  # target months over before the test
        assert (iss[f.test] >= start).all() and (iss[f.test] < start + pd.DateOffset(years=1)).all()
        assert len(f.train) > 0


def test_features_available_at_issue_assertion():
    issue = pd.DatetimeIndex(["2000-05-01", "2000-06-01"])
    ok = pd.DataFrame({"a": pd.to_datetime(["2000-04-26", "2000-05-27"]), "b": issue})
    data.assert_available(ok, issue)  # equal or earlier is fine
    bad = ok.assign(c=pd.to_datetime(["2000-04-30", "2000-06-02"]))
    with pytest.raises(AssertionError, match="c"):
        data.assert_available(bad, issue)


def test_built_features_respect_issue_date():
    inp = data.Inputs(
        rain_daily={b: pd.Series(1.0, index=pd.date_range("1979-12-01", "2001-01-31")) for b in (12004, 12010)},
        ar_month=pd.Series(1.0, index=pd.date_range("1980-01-01", "2001-01-01", freq="MS")),
        flow_month={s: pd.Series(5.0, index=pd.date_range("1980-01-01", "2001-01-01", freq="MS")) for s in (12004, 12010)},
        oni=pd.DataFrame({"date": pd.date_range("1979-01-01", "2001-01-01", freq="MS"), "oni": 0.0, "phase": "neutral"}),
        state=pd.DataFrame(
            [
                {"issue_date": d, "box": b, "available_on": d - pd.Timedelta(days=5),
                 **{v: 0.1 for v in data.STATE_VARS}}
                for d in pd.date_range("1980-05-01", "2000-12-01", freq="MS")
                for b in data.BOXES
            ]
        ),
    )  # fmt: skip
    S = data.build_samples(inp, "rain")
    assert len(S) > 0
    assert (S.avail.apply(lambda c: pd.DatetimeIndex(c).values) <= S.meta["issue"].values[:, None]).all().all()
    assert (S.avail["sd_12004"] == S.meta["issue"] - pd.Timedelta(days=5)).all()
    # rain windows end with day I-6: shifting the day I-5 value must not change rain30
    r = inp.rain_daily[12004].copy()
    d = S.meta["issue"].iloc[0]
    r.loc[d - pd.Timedelta(days=5): d] = 1000.0
    inp.rain_daily[12004] = r
    S2 = data.build_samples(inp, "rain")
    assert S2.X["rain30"].iloc[0] == S.X["rain30"].iloc[0] == 30.0
    assert S.X["rain90"].iloc[0] == 90.0


def test_tercile_edges_from_training_only():
    ref = np.arange(1.0, 31.0)  # training values of one calendar month
    cls, tied = model.tercile_classes(ref, np.array([5.5, 15.5, 25.5, 1000.0, -5.0]))
    assert list(cls) == [0, 1, 2, 2, 0] and not tied.any()
    # a huge value only in the "test" months must not move the edges
    idx = pd.date_range("2000-01-01", periods=60, freq="MS")
    series = pd.Series(np.arange(60.0), index=idx)
    series.iloc[-1] = 1e9  # test month, outside the reference
    ref_months = idx[:48]
    cls, _ = model.class_labels(series, ref_months, idx[[48, 59]], series.iloc[[48, 59]].values)
    assert list(cls) == [2, 2]
    cls2, _ = model.class_labels(series, ref_months, idx[[0, 12, 24]], series.iloc[[0, 12, 24]].values)
    assert list(cls2) == [0, 1, 1]  # Jan refs 0,12,24,36: p = .125, .375, .625


def test_tercile_ties_midrank():
    ref = np.array([0.0] * 5 + [1.0] * 3 + [2.0] * 1 + [5.0] * 1)  # AR-like counts
    cls, tied = model.tercile_classes(ref, np.array([0.0, 1.0, 2.0, 5.0, 3.0]))
    # p(0)=0.25 -> low, p(1)=0.65 -> mid, p(2)=0.85 -> high, p(5)=0.95 high, 3 not tied p=0.9 high
    assert list(cls) == [0, 1, 2, 2, 2]
    assert list(tied) == [True, True, True, True, False]


def test_rps_and_brier_hand_computed():
    p = np.array([[0.2, 0.3, 0.5]])
    assert score.rps(p, np.array([2]))[0] == pytest.approx(0.04 + 0.25)
    assert score.rps(p, np.array([0]))[0] == pytest.approx(0.64 + 0.25)
    assert score.rps(p, np.array([1]))[0] == pytest.approx(0.2**2 + 0.5**2 + 0.0)
    clim = np.full((3, 3), 1 / 3)
    assert score.rps(clim, np.array([0, 1, 2])) == pytest.approx([5 / 9, 2 / 9, 5 / 9])
    onehot_wrong = np.array([[1.0, 0.0, 0.0]])
    assert score.rps(onehot_wrong, np.array([2]))[0] == pytest.approx(2.0)
    assert score.brier(p, np.array([2]), 2)[0] == pytest.approx(0.25)
    assert score.brier(p, np.array([2]), 0)[0] == pytest.approx(0.04)
    assert score.brier(p, np.array([0]), 0)[0] == pytest.approx(0.64)


def test_skill_ci_perfect_and_null():
    m = np.array([0.2, 0.3, 0.25, 0.35])
    sk, lo, hi = score.skill_ci(m, m)
    assert sk == pytest.approx(0) and lo <= 0 <= hi
    sk, lo, hi = score.skill_ci(m * 0.5, m)
    assert sk == pytest.approx(0.5) and lo == pytest.approx(0.5) == pytest.approx(hi)
    assert score.skill_ci(m, m, seed=1) == score.skill_ci(m, m, seed=1)


def test_monthly_series_rules():
    d = pd.Series(1.0, index=pd.date_range("2000-01-01", "2000-03-31"))
    d.loc["2000-02-10"] = np.nan
    assert np.isnan(data.monthly_from_daily(d, "sum").loc["2000-02-01"])
    assert data.monthly_from_daily(d, "mean", 25).loc["2000-02-01"] == 1.0  # >= 25 valid days
    ev = pd.DataFrame({"start": pd.to_datetime(["2000-01-05 06:00", "2000-01-20 00:00", "2000-03-01 00:00"])})
    ar = data.ar_monthly(ev, pd.Timestamp("2000-01-01"), pd.Timestamp("2000-03-01"))
    assert list(ar) == [2, 0, 1]


def test_persistence_rule_and_oni_lag():
    assert data.persistence_months("rain") == 2 and data.persistence_months("ar") == 2
    assert data.persistence_months("flow") == 1
    oni = pd.DataFrame({"date": pd.date_range("2000-01-01", periods=12, freq="MS"), "oni": range(12), "phase": "x"})
    v, _ = data.oni_at_issue(oni, pd.Timestamp("2000-06-01"))
    assert v == 2  # season centred on March (ending April), issue in June

import numpy as np
import pandas as pd
import pytest

from clima_nqn.stages.flood import conditional_clim as cc


def make_events(starts, hours=6):
    start = pd.to_datetime(starts, format="mixed")
    return pd.DataFrame(
        {
            "event_id": [f"E{i}" for i in range(len(start))],
            "start": start,
            "end": start + pd.Timedelta(hours=hours),
        }
    )


def test_groups_and_folds_have_no_leakage():
    # 0 and 1 overlap by response window; 2 starts 8 days after 1 (same group); 3 starts 17 days later
    # (separate group, but inside the +-10 day gap of group A's window); 4 is far away.
    ev = make_events(["2000-01-01", "2000-01-05", "2000-01-13", "2000-01-30", "2001-06-01"])
    groups = cc.event_groups(ev)
    assert groups[0] == groups[1] == groups[2]
    assert groups[3] != groups[0] and groups[4] not in (groups[0], groups[3])
    fl = cc.folds(ev)
    assert len(fl) == 3
    first, wend = cc._windows(ev)
    seen = set()
    for train, test in fl:
        seen.update(test.tolist())
        assert not set(train) & set(test)
        lo, hi = cc.fold_window(ev, test)
        for i in train:
            assert wend.iloc[i] < lo or first.iloc[i] > hi
    assert seen == set(range(5))
    train_a = next(tr for tr, te in fl if 0 in te)
    assert 3 not in train_a  # starts inside group A window end (01-23) + gap
    assert 4 in train_a


def test_fold_thresholds_ignore_heldout_dates():
    idx = pd.date_range("2000-01-01", periods=400, freq="D")
    s = pd.Series(np.ones(400), index=idx)
    s.loc["2000-06-01":"2000-06-30"] = 1000.0
    lo, hi = pd.Timestamp("2000-05-25"), pd.Timestamp("2000-07-05")
    assert cc.station_threshold(s, lo, hi, "p95") == 1.0
    assert (
        cc.station_threshold(s, pd.Timestamp("2100-01-01"), pd.Timestamp("2100-01-02"), "p95") > 1.0
    )


def rows(exceed_by_cell, station="A"):
    out = []
    i = 0
    for (ivt, deg, month), flags in exceed_by_cell.items():
        for f in flags:
            out.append(
                {
                    "event_id": f"E{i}",
                    "station_id": station,
                    "ivt_max": ivt,
                    "deg0l_max": deg,
                    "month": month,
                    "q_before": 1.0,
                    "q_peak": 10.0 if f else 1.0,
                }
            )
            i += 1
    return pd.DataFrame(out)


def test_shrinkage_math_and_unseen_bins():
    df = rows(
        {
            (100.0, 1000.0, 6): [1, 1, 0, 0],  # cell freq 0.5
            (900.0, 3000.0, 1): [0, 0, 0, 0],
            (500.0, 2000.0, 6): [1, 0, 0, 0],
        }
    )
    m = cc.fit(df, 5.0, k=2.0)
    p0 = 3 / 12
    assert m.p0["A"] == pytest.approx(p0)
    low = df.iloc[[0]]
    assert cc.predict_proba(m, low)[0] == pytest.approx((2 + 2 * p0) / (4 + 2))
    # unseen cell (ivt in the low tercile but dry season with high 0 degC level) -> p0
    unseen = low.assign(month=1, deg0l_max=3000.0)
    assert cc.predict_proba(m, unseen)[0] == pytest.approx(p0)
    # unseen station and NaN predictors fall back to the overall frequency
    other = low.assign(station_id="Z", ivt_max=np.nan)
    assert cc.predict_proba(m, other)[0] == pytest.approx(p0)
    # edges come from training only: terciles of the 3 distinct events' ivt
    assert m.edges["ivt"][0] < m.edges["ivt"][1] <= 900.0


def test_pooled_and_month_variants_predict():
    df = pd.concat(
        [rows({(100.0, 1000.0, 6): [1, 0]}, "A"), rows({(100.0, 1000.0, 6): [1, 1]}, "B")]
    )
    df["event_id"] = [f"E{i}" for i in range(len(df))]
    pm = cc.fit(df, 5.0, pooled=True)
    mm = cc.fit(df, 5.0, features=("month",))
    assert cc.predict_proba(pm, df.iloc[[0]])[0] == pytest.approx((3 + 2 * 0.75) / (4 + 2))
    assert cc.predict_proba(mm, df.iloc[[0]])[0] == pytest.approx((1 + 2 * 0.5) / (2 + 2))
    assert cc.predict_proba(mm, df.iloc[[0]].assign(month=12))[0] == pytest.approx(0.5)


def test_baselines_use_training_only():
    tr = rows({(1.0, 1.0, 6): [1, 1, 0, 0], (1.0, 1.0, 1): [0, 0]})
    tr["q_before"] = [9.0, 9.0, 1.0, 1.0, 1.0, 1.0]
    te = rows({(1.0, 1.0, 6): [0]}).assign(q_before=9.0)
    b = cc.baseline_probs(tr, te, 5.0)
    assert b["clim"][0] == pytest.approx(0.5)  # wet-season training frequency
    assert b["pers"][0] == pytest.approx(1.0)  # q_before high -> both training highs exceeded
    assert b["pers_raw"][0] == 1.0


def test_bootstrap_shapes_and_perfect_model():
    rng = np.random.default_rng(1)
    y = (rng.random(60) < 0.3).astype(float)
    groups = np.repeat(np.arange(20), 3)
    ref = np.full(60, y.mean())
    bss, lo, hi, boot = cc.bootstrap_bss(y, y.copy(), ref, groups, n_boot=200, seed=3)
    assert boot.shape == (200,)
    assert bss == pytest.approx(1.0) and lo <= hi
    bss2, lo2, hi2, _ = cc.bootstrap_bss(y, ref, ref, groups, n_boot=200, seed=3)
    assert bss2 == pytest.approx(0.0) and lo2 == pytest.approx(0.0) and hi2 == pytest.approx(0.0)
    again = cc.bootstrap_bss(y, y, ref, groups, n_boot=200, seed=3)
    assert np.array_equal(again[3], boot)


def test_score_entity_insufficient_and_reliability():
    pred = pd.DataFrame(
        {
            "exceed": [1.0, 0, 0, 0, 0, 0],
            "p_main": 0.2,
            "p_clim": 0.1,
            "group": [0, 1, 2, 3, 4, 5],
        }
    )
    r = cc.score_entity(pred, "p_main", "p_clim", n_boot=50)
    assert r["status"] == "insuficiente" and r["n_exceed"] == 1 and r["n_groups"] == 6
    rel = cc.reliability(pred["exceed"], pred["p_main"])
    assert sum(b["n"] for b in rel) == 6


def test_build_table_uses_v8_rule():
    idx = pd.date_range("2000-01-01", "2000-03-01", freq="D")
    s = pd.Series(10.0, index=idx)
    s.loc["2000-01-20"] = 50.0
    ev = make_events(["2000-01-10 06:00", "2000-02-20"]).assign(
        ivt_max=[500.0, 600.0], deg0l_max=[2000.0, 2500.0]
    )
    tab = cc.build_table(ev, {"A": s})
    assert tab.loc[0, "q_peak"] == 50.0 and tab.loc[0, "q_before"] == 10.0
    assert tab.loc[0, "month"] == 1 and tab.loc[1, "month"] == 2


def test_evaluate_and_report_smoke():
    rng = np.random.default_rng(0)
    idx = pd.date_range("1990-01-01", "2005-12-31", freq="D")
    s = pd.Series(rng.gamma(2.0, 5.0, len(idx)), index=idx)
    starts = pd.date_range("1991-03-01", periods=40, freq="90D")
    ev = make_events(starts.astype(str)).assign(
        ivt_max=rng.uniform(300, 900, 40), deg0l_max=rng.uniform(1500, 3500, 40)
    )
    tab = cc.build_table(ev, {"12004": s})
    pred = cc.evaluate(tab, ev, {"12004": s}, "annmax_median")
    assert len(pred) == len(tab) and pred["p_main"].between(0, 1).all()
    sc = cc.score_table(pred, "p_main", n_boot=50)
    assert set(sc) == set(cc.REFS) and "pooled" in sc["clim"]

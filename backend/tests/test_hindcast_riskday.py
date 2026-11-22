"""F5.3 risk-day classifier: regions, labels, mechanisms, split, blocks, models, report (synthetic data)."""

import numpy as np
import pandas as pd
import pytest

from clima_nqn.stages.hindcast import riskday as rd


def _ts(*s):
    return pd.to_datetime(list(s))


# --- regions ----------------------------------------------------------------------------------


def test_regions_masks_on_tiny_grid():
    lat = np.arange(-41.0, -36.0, 0.5)
    lon = np.arange(-72.0, -67.0, 0.5)
    m = rd.regions(lat, lon)
    assert set(m) == set(rd.REGIONS)
    lat2d = np.broadcast_to(lat[:, None], m["confluencia"].shape)
    # north/south split the polygon at -38.5 and never overlap
    assert not (m["cordillera_norte"] & m["cordillera_sur"]).any()
    assert (lat2d[m["cordillera_norte"]] >= -38.5).all()
    assert (lat2d[m["cordillera_sur"]] < -38.5).all()
    assert m["cordillera_norte"].any() and m["cordillera_sur"].any()
    # Confluencia: cell centers inside the F3.6 box
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    box = (la >= -39.2) & (la <= -38.7) & (lo >= -68.4) & (lo <= -67.8)
    assert (m["confluencia"] == box).all()
    assert m["confluencia"].sum() == 1  # only (-39.0, -68.0) on this 0.5 deg grid
    # Confluencia is east of the cordillera polygon
    assert not (m["confluencia"] & (m["cordillera_norte"] | m["cordillera_sur"])).any()


# --- thresholds / split / blocks ----------------------------------------------------------------


def test_threshold_uses_train_days_only():
    idx = pd.date_range("2000-01-01", "2019-12-31")
    rng = np.random.default_rng(0)
    s = pd.Series(rng.gamma(0.5, 4.0, len(idx)), index=idx)
    base = rd.train_threshold(s, 0.95)
    s2 = s.copy()
    s2[s2.index >= "2012-01-01"] += 100.0  # valid + test changes must not move it
    assert rd.train_threshold(s2, 0.95) == base
    s3 = s.copy()
    s3.loc["2005-03-01"] = 1e6
    assert rd.train_threshold(s3, 0.95) != base


def test_split_dates_disjoint_and_ordered():
    d = pd.date_range("2000-01-01", "2019-12-31")
    sp = rd.split_masks(d)
    total = sp["train"].astype(int) + sp["valid"].astype(int) + sp["test"].astype(int)
    assert (total == 1).all()
    assert d[sp["train"]].max() < d[sp["valid"]].min()
    assert d[sp["valid"]].max() < d[sp["test"]].min()


def test_event_blocks_merge_consecutive_risk_across_regions():
    d = pd.date_range("2015-01-01", periods=8)
    risk_a = np.array([0, 1, 1, 0, 0, 1, 0, 1], bool)  # region A
    risk_b = np.array([0, 0, 1, 1, 0, 0, 0, 1], bool)  # region B
    ids = rd.event_blocks(d, risk_a | risk_b)
    assert ids[1] == ids[2] == ids[3]  # A and B runs overlap -> one block
    assert ids[5] != ids[3] and ids[5] != ids[7]  # gap day 6 separates
    assert len({ids[0], ids[4], ids[6]}) == 3  # non-risk days are singletons
    assert len(np.unique(ids)) == 6
    # shuffled input order gives the same grouping
    perm = np.array([3, 0, 7, 2, 5, 1, 6, 4])
    ids2 = rd.event_blocks(d[perm], (risk_a | risk_b)[perm])
    assert len(np.unique(ids2)) == 6
    assert ids2[0] == ids2[3] == ids2[5]


# --- mechanism / preponderance ------------------------------------------------------------------


def _events(*pairs):
    pairs = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in pairs]
    return pd.DataFrame(
        {
            "event_id": range(len(pairs)),
            "start": _ts(*[p[0] for p in pairs]),
            "end": _ts(*[p[1] for p in pairs]),
        }
    )


def test_ar_touch_half_open_edges():
    ev = _events(("2015-01-02 06:00", "2015-01-03 00:00"))
    days = pd.date_range("2015-01-01", periods=4)
    # [Jan 2 06:00, Jan 3 00:00): touches Jan 2 only (end is exclusive, Jan 3 00:00 not touched)
    assert list(rd.ar_touch(days, ev)) == [False, True, False, False]
    # event starting exactly at D+1 00:00 does not touch D
    ev2 = _events(("2015-01-03 00:00", "2015-01-03 12:00"))
    assert list(rd.ar_touch(days, ev2)) == [False, False, True, False]
    # +-1 day widens both sides
    assert list(rd.ar_touch(days, ev2, pad_days=1)) == [False, True, True, True]
    assert not rd.ar_touch(days, ev.iloc[0:0]).any()


def test_mechanism_order_and_tp_zero():
    days = pd.date_range("2015-01-01", periods=4)
    ev = _events(("2015-01-01 03:00", "2015-01-01 09:00"))
    tp = np.array([10.0, 10.0, 10.0, 0.0])
    cp = np.array([9.0, 6.0, 1.0, 0.0])  # day1: AR wins over convective-looking cp/tp
    mech = rd.mechanism(days, ev, tp, cp)
    assert list(mech) == ["ar", "convective", "other", "other"]  # tp=0 -> not convective
    # cp fraction threshold is inclusive and variable
    assert rd.mechanism(days, ev, tp, cp, cp_frac=0.6)[1] == "convective"
    assert rd.mechanism(days, ev, tp, cp, cp_frac=0.7)[1] == "other"
    assert rd.mechanism(days, ev, tp, cp, cp_frac=0.0)[3] == "other"


def test_preponderance_counts_and_wilson():
    d = pd.to_datetime(["2015-01-05", "2015-01-06", "2015-01-07", "2015-07-01", "2015-07-02"])
    risk = np.array([1, 1, 1, 1, 0], bool)
    mech = np.array(["ar", "ar", "convective", "other", "ar"])
    p = rd.preponderance(d, risk, mech)
    assert p["DJF"]["n"] == 3 and p["DJF"]["ar"]["k"] == 2
    assert p["DJF"]["ar"]["share"] == pytest.approx(2 / 3)
    from clima_nqn.stages.ar.extremes import wilson_interval

    assert (p["DJF"]["ar"]["lo"], p["DJF"]["ar"]["hi"]) == pytest.approx(wilson_interval(2, 3))
    assert p["JJA"]["n"] == 1 and p["JJA"]["other"]["k"] == 1  # non-risk day not counted
    assert p["all"]["n"] == 4 and p["MAM"]["n"] == 0
    assert np.isnan(p["MAM"]["ar"]["share"])


# --- synthetic end-to-end ------------------------------------------------------------------------


def _synthetic_ctx(seed=0, n_leads=2, n_members=5, signal=True):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2000-01-01", "2019-12-31")
    n = len(dates)
    tp = {}
    members = {}
    for r in rd.REGIONS:
        base = rng.gamma(0.4, 3.0, n)
        tp[r] = base
        mem = np.empty((n, n_leads, n_members))
        for li in range(n_leads):
            noise = 0.3 * (li + 1)
            for k in range(n_members):
                mem[:, li, k] = (base if signal else rng.gamma(0.4, 3.0, n)) * np.exp(
                    rng.normal(0, noise, n)
                )
        mem[5, 0, 2] = np.nan  # a missing member is tolerated
        members[r] = mem
    tp_df = pd.DataFrame(tp, index=dates)
    cp_df = tp_df * rng.uniform(0, 1, tp_df.shape)
    events = _events(
        *[
            (d, d + pd.Timedelta(hours=18))
            for d in pd.date_range("2000-02-01", "2019-12-01", freq="45D")
        ]
    )
    return rd.build_context(dates, range(1, n_leads + 1), members, tp_df, cp_df, events)


def test_climatology_vs_itself_is_zero_and_pooled_events_reported():
    pytest.importorskip("sklearn")
    ctx = _synthetic_ctx()
    res = rd._evaluate(ctx, 0.95, ("log",), n_boot=20, seed=0, light=False)
    assert res["n_events_pooled_test"] > 0
    se = np.array([0.1, 0.2, 0.3])
    assert rd._skill(se, se) == pytest.approx(0.0)
    for r in rd.REGIONS:
        for row in res["regions"][r].values():
            assert "bss_clim" not in row["models"]["clim"]
            assert row["n_days"] == 1826
            assert set(row["mechanisms"]) == set(rd.MECHANISMS)
            assert len(row["models"]["log"]["reliability"]) == 10


def test_logistic_beats_climatology_on_separable_data():
    pytest.importorskip("sklearn")
    ctx = _synthetic_ctx(signal=True)
    res = rd._evaluate(ctx, 0.95, ("log",), n_boot=30, seed=0, light=False)
    for r in rd.REGIONS:
        b = res["regions"][r]["1"]["models"]["log"]["bss_clim"]
        assert b["value"] > 0.2
        assert b["lo"] > 0  # CI excludes zero


def test_logistic_no_better_without_signal():
    pytest.importorskip("sklearn")
    ctx = _synthetic_ctx(signal=False)
    res = rd._evaluate(ctx, 0.95, ("log",), n_boot=20, seed=0, light=True)
    for r in rd.REGIONS:
        assert res["regions"][r]["1"]["models"]["log"]["bss_clim"]["value"] < 0.1


def test_lightgbm_runs_and_reports_info():
    pytest.importorskip("sklearn")
    pytest.importorskip("lightgbm")
    ctx = _synthetic_ctx(n_leads=1)
    res = rd._evaluate(ctx, 0.95, ("log", "lgbm"), n_boot=10, seed=0, light=False)
    row = res["regions"]["confluencia"]["1"]
    assert "lgbm" in row["models"] and "n_estimators" in row["lgbm_info"]
    assert row["models"]["lgbm"]["bss_clim"]["value"] > 0
    assert "bss_log" in row["models"]["lgbm"]


# --- report ----------------------------------------------------------------------------------------


def test_render_md_structure():
    pytest.importorskip("sklearn")
    ctx = _synthetic_ctx(n_leads=1)
    res = rd._clean(
        rd.analyze(ctx, n_boot=10, seed=0, quantiles=(0.95, 0.90), models=("clim", "log"))
    )
    md = rd.render_md(res, {"n_boot": 10, "seed": 0})
    assert "<!-- veredicto: lo escribe Opus -->" in md
    for h in (
        "## Veredicto",
        "## Fuente y alcance",
        "## Regla fijada antes de correr",
        "## Advertencias",
    ):
        assert h in md
    for r in rd.REGION_LABELS.values():
        assert f"\n## {r}\n" in md
    assert (
        "sin verificar" in md
    )  # synthetic test has < 20 events per mechanism somewhere or pooled flag text
    assert "SMN" in md and "Defensa Civil" in md
    assert "," in md  # decimal comma


# --- optional ENSO hook (F5.7) -----------------------------------------------------------------------


def test_enso_hook_off_by_default_and_adds_columns_when_on():
    ctx = _synthetic_ctx(n_leads=1)
    thr = {r: 5.0 for r in rd.REGIONS}
    off = rd.feature_frame(ctx["members"], "confluencia", 0, thr, ctx["dates"])
    assert not set(rd.ENSO_COLS) & set(off.columns)
    dates = pd.date_range("1999-01-01", "2020-12-01", freq="MS")
    enso = pd.DataFrame({"date": dates, "oni": np.where(dates.year % 2 == 0, 1.0, -1.0)})
    on = rd.feature_frame(ctx["members"], "confluencia", 0, thr, ctx["dates"], enso=enso, lead=1)
    pd.testing.assert_frame_equal(on[off.columns], off)
    assert set(rd.ENSO_COLS) <= set(on.columns)
    assert set(on["oni_avail"].unique()) == {1.0, -1.0}

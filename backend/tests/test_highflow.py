"""F6.7 high-flow leave-one-flood-out test: fold masks, leakage, forecast assembly, probability, scores."""

import inspect

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from clima_nqn.io import forcing, snow
from clima_nqn.stages.flood import highflow as hf
from clima_nqn.stages.flood import highflow_data as hd
from clima_nqn.stages.flood import lstm

# --- folds ------------------------------------------------------------------------------------


def test_fold_train_mask_excludes_hydro_year_and_gap():
    dates = pd.date_range("1990-01-01", "2020-12-31")
    m = hd.fold_train_mask(dates, 2006, gap_days=30)
    start, end = hd.fold_excluded_range(2006, 30)
    assert start == pd.Timestamp("2006-03-02") and end == pd.Timestamp("2007-04-30")
    d = pd.DatetimeIndex(dates)
    assert not m[(d >= "2006-04-01") & (d <= "2007-03-31")].any()  # the hydrological year itself
    assert not m[(d >= "2006-03-02") & (d < "2006-04-01")].any()  # 30 days before
    assert not m[(d > "2007-03-31") & (d <= "2007-04-30")].any()  # 30 days after
    assert m[d == "2006-03-01"].all() and m[d == "2007-05-01"].all()
    assert m.sum() == len(d) - ((end - start).days + 1)
    # the hydrological year label of every excluded day is the fold or its neighbours
    assert set(lstm.hydro_year(d[~m])) == {2005, 2006, 2007}


def test_fold_train_mask_gap_zero_is_exactly_the_hydro_year():
    d = pd.date_range("2000-01-01", "2010-12-31")
    m = hd.fold_train_mask(d, 2004, gap_days=0)
    assert set(lstm.hydro_year(d[~m])) == {2004}


def test_check_no_leak():
    ok = pd.date_range("2000-01-01", "2006-03-01")
    hd.check_no_leak(ok, 2006, what="x")
    hd.check_no_leak([], 2006)
    with pytest.raises(hd.LeakError, match="2007-04-30"):
        hd.check_no_leak(list(ok) + [pd.Timestamp("2007-04-30")], 2006, what="residuals")
    hd.check_no_leak([pd.Timestamp("2007-05-01")], 2006)
    with pytest.raises(hd.LeakError):
        hd.check_no_leak([pd.Timestamp("2006-03-02")], 2006)


def _synthetic(fold_year: int):
    d = pd.date_range("1990-01-01", "2005-12-31")
    rng = np.random.default_rng(1)
    doy = d.day_of_year.to_numpy()
    q = 100 + 80 * np.cos(2 * np.pi * (doy - 180) / 365) ** 2 + rng.gamma(2, 20, len(d))
    flow_df = pd.DataFrame({"date": d, "q_m3s": q})
    sim = q * np.exp(rng.normal(0, 0.2, len(d)))
    return d, flow_df, q, sim


@pytest.mark.parametrize("fold_year", [1998, 2003])
def test_fitted_quantities_ignore_fold_dates(fold_year):
    d, flow_df, q, sim = _synthetic(fold_year)
    area = 1000.0
    to_mm = 86.4 / area
    base = hf.fold_quantities(flow_df, fold_year, d, q * to_mm, sim * to_mm)
    out = ~hd.fold_train_mask(d, fold_year)
    assert out.sum() > 400
    for name, used in base["used"].items():
        hd.check_no_leak(used, fold_year, what=name)
    # replace everything inside the excluded range by absurd values: no fitted quantity may change
    q2, sim2 = q.copy(), sim.copy()
    q2[out], sim2[out] = 1e6, 1e-3
    pert = hf.fold_quantities(
        pd.DataFrame({"date": d, "q_m3s": q2}), fold_year, d, q2 * to_mm, sim2 * to_mm
    )
    for k in ("thr_main_m3s", "thr_p95_m3s", "train_max_m3s"):
        assert pert[k] == base[k]
    for k in ("pclim_main", "pclim_p95", "resid_gr4j"):
        np.testing.assert_array_equal(pert[k], base[k])
    assert base["train_max_m3s"] < 1e5


def test_fitted_quantities_do_react_to_training_dates():
    d, flow_df, q, sim = _synthetic(1998)
    to_mm = 0.0864
    base = hf.fold_quantities(flow_df, 1998, d, q * to_mm, sim * to_mm)
    q2 = q.copy()
    q2[d.year == 1992] *= 3
    pert = hf.fold_quantities(
        pd.DataFrame({"date": d, "q_m3s": q2}), 1998, d, q2 * to_mm, sim * to_mm
    )
    assert pert["thr_p95_m3s"] > base["thr_p95_m3s"]


def test_doy_climatology_uses_training_days_only():
    d = pd.date_range("2000-01-01", "2004-12-31")
    v = np.where(d.year == 2003, 100.0, 10.0)
    train = d.year != 2003
    c = hf.doy_climatology(d, v, train)
    assert np.nanmax(c[1:]) == 10.0 and np.isfinite(c[1:]).all()
    p = hf.exceedance_climatology(d, v, train, thr=50.0)
    assert np.nanmax(p[1:]) == 0.0


def test_fold_labels_and_val_years():
    assert hf.val_years(2006) == [2008, 2009, 2010, 2011, 2012, 2013]
    assert hf.val_years(2010) == [2007, 2008, 2012, 2013, 2014, 2015]
    assert 2023 not in hf.val_years(2023) and len(hf.val_years(2023)) == 6
    d = pd.date_range("2000-01-01", "2024-12-31")
    lab = hf.fold_labels(d, 2006)
    ex = ~hd.fold_train_mask(d, 2006)
    assert (lab[ex] == 3).all() and not (lab[~ex] == 3).any()
    hy = lstm.hydro_year(d)
    assert (lab[~ex & np.isin(hy, hf.val_years(2006))] == 2).all()
    assert (lab[~ex & (hy == 2000)] == 1).all()


# --- floods and coverage ----------------------------------------------------------------------


def test_needed_pairs():
    peak = pd.Timestamp("2006-07-12")
    pairs = hd.needed_pairs(peak)
    assert len(pairs) == 265
    lo, hi = peak - pd.Timedelta(days=15), peak + pd.Timedelta(days=15)
    for t, lead in pairs:
        v = t + pd.Timedelta(days=lead - 1)
        assert lo <= t <= hi and lo <= v <= hi and 1 <= lead <= 10
    # the pair whose valid day is the peak exists for every lead 1..10
    assert {lead for t, lead in pairs if t + pd.Timedelta(days=lead - 1) == peak} == set(
        range(1, 11)
    )


def test_coverage_rules():
    last = pd.Timestamp("2025-12-30")
    assert hd.coverage(pd.Timestamp("2006-07-12"), last)[0] == "reforecast"
    assert hd.coverage(pd.Timestamp("1991-05-29"), last)[0] is None
    gap = hd.coverage(pd.Timestamp("2020-03-01"), last)
    assert gap[0] is None and "hueco" in gap[1]
    peak = pd.Timestamp("2023-06-26")
    days = {pd.Timestamp(d) for d in hd.window_days(peak)}
    assert hd.coverage(peak, last, days)[0] == "operational"
    assert hd.coverage(peak, last, set())[0] is None
    assert hd.coverage(pd.Timestamp("2025-12-28"), last)[0] is None
    assert hd.coverage(pd.Timestamp("2019-12-20"), last)[0] is None  # window crosses the 2020 gap


# --- forecast assembly ------------------------------------------------------------------------


def _table(extra=()):
    rows = []
    for init in pd.date_range("2006-07-01", "2006-07-05"):
        for lead in hd.LEADS:
            for i, m in enumerate(hd.MEMBERS):
                rows.append(
                    (12004, init, lead, init + pd.Timedelta(days=lead - 1), m,
                     init.day * 100 + lead * 10 + i)
                )  # fmt: skip
    rows += list(extra)
    return pd.DataFrame(rows, columns=list(hd.ForecastTable.COLUMNS))


def test_forecast_table_uses_only_the_run_of_the_issue_day():
    issue = pd.Timestamp("2006-07-03")
    # decoy: a LATER init (07-04) whose valid day equals the issue run's lead 2 (07-04); different value
    t = hd.ForecastTable(_table())
    got = t.get(12004, issue, 2)
    np.testing.assert_array_equal(got, [3 * 100 + 20 + i for i in range(5)])
    later = t.get(12004, pd.Timestamp("2006-07-04"), 1)  # valid 07-04 too, different run
    assert not np.array_equal(got, later)
    # the issue day t only ever sees init == t
    allin = t.inputs_for_issue(12004, issue)
    assert sorted(allin) == list(range(1, 11))
    for lead, arr in allin.items():
        np.testing.assert_array_equal(arr, [300 + lead * 10 + i for i in range(5)])
    assert t.get(12004, pd.Timestamp("2006-07-10"), 1) is None


def test_forecast_table_lead_mapping_is_checked():
    bad = _table(
        extra=[(12004, pd.Timestamp("2006-07-01"), 3, pd.Timestamp("2006-07-05"), "c00", 1.0)]
    )
    with pytest.raises(ValueError, match="valid_date = init_date"):
        hd.ForecastTable(bad)
    missing = _table().drop(columns=["member"])
    with pytest.raises(ValueError, match="lacks columns"):
        hd.ForecastTable(missing)


def test_forecast_table_needs_all_members():
    df = _table()
    df = df[~((df["init_date"] == "2006-07-02") & (df["lead"] == 1) & (df["member"] == "p03"))]
    t = hd.ForecastTable(df)
    assert t.get(12004, pd.Timestamp("2006-07-02"), 1) is None
    assert t.get(12004, pd.Timestamp("2006-07-02"), 2) is not None


def test_box_mean_grid_matches_field_mean():
    lat = np.arange(-41.25, -35.99, 0.25)
    lon = np.arange(-72.0, -67.49, 0.25)
    rng = np.random.default_rng(0)
    arr = rng.random((3, len(lat), len(lon)))
    box = snow.UPSTREAM_BOXES[12004]
    ilat, ilon, w = hd.box_weights(lat, lon, box)
    assert abs(w.sum() - 1) < 1e-12
    got = hd.box_mean_grid(arr, ilat, ilon, w)
    for k in range(3):
        da = xr.DataArray(arr[k], dims=("lat", "lon"), coords={"lat": lat, "lon": lon})
        assert got[k] == pytest.approx(forcing.field_mean(da, box), rel=1e-9)


# --- operational archive ----------------------------------------------------------------------


def _fake_fetcher(calls, fail=()):
    def fetch(init, member, step, area):
        calls.append((init, member, step))
        from clima_nqn.ops.ingest import NotAvailable

        if (member, step) in fail:
            raise NotAvailable("not published")
        north, west, south, east = area
        lat = np.arange(south, north + 0.01, 0.25)
        lon = np.arange(west, east + 0.01, 0.25)
        v = float(step // 6 + hd.MEMBERS.index(member) * 100)
        return xr.DataArray(
            np.full((len(lat), len(lon)), v), dims=("lat", "lon"), coords={"lat": lat, "lon": lon}
        )

    return fetch


def test_fetch_init_writes_cache_and_is_idempotent(tmp_path):
    calls = []
    side = hd.fetch_init("2023-06-20", tmp_path, workers=4, fetcher=_fake_fetcher(calls), wait=0)
    assert side["status"] == "ok" and side["n_missing"] == 0 and len(calls) == 200
    df = pd.read_parquet(tmp_path / "20230620.parquet")
    assert set(df["member"]) == set(hd.MEMBERS) and set(df["lead"]) == set(hd.LEADS)
    assert (df["valid_date"] == df["init_date"] + pd.to_timedelta(df["lead"] - 1, unit="D")).all()
    # lead L of c00 = sum of the buckets ending at 24(L-1)+6 .. 24L, bucket at step s = s // 6
    g = df[(df["member"] == "c00") & (df["station_id"] == 12004) & (df["lead"] == 2)]
    assert g["precip_mm"].iloc[0] == pytest.approx(sum(s // 6 for s in (30, 36, 42, 48)))
    assert hd.ops_inits_available(tmp_path) == {pd.Timestamp("2023-06-20")}
    hd.fetch_init("2023-06-20", tmp_path, fetcher=_fake_fetcher(calls))
    assert len(calls) == 200  # cached: nothing downloaded again
    tab = hd.ForecastTable(hd.read_ops_table(tmp_path, [pd.Timestamp("2023-06-20")]))
    assert tab.get(12004, pd.Timestamp("2023-06-20"), 10) is not None


def test_fetch_init_records_missing_files_without_failing(tmp_path):
    calls = []
    fail = {("p02", 30), ("p02", 36)}
    side = hd.fetch_init(
        "2023-06-21", tmp_path, workers=4, fetcher=_fake_fetcher(calls, fail), wait=0
    )
    assert side["n_missing"] == 2 and side["n_missing_errors"] == 0
    df = pd.read_parquet(tmp_path / "20230621.parquet")
    lost = df[(df["member"] == "p02") & (df["lead"] == 2)]
    assert lost.empty  # a lead with a missing bucket is dropped
    tab = hd.ForecastTable(df)
    assert tab.get(12004, pd.Timestamp("2023-06-21"), 2) is None  # incomplete members -> unusable
    assert tab.get(12004, pd.Timestamp("2023-06-21"), 3) is not None


# --- no flow input ----------------------------------------------------------------------------


def _norm():
    return lstm.Norm(np.zeros(5), np.ones(5), np.zeros(3), np.ones(3), 0.0, 1.0)


def test_lstm_window_has_no_flow_channel_and_no_future_history():
    for fn in (hf.build_lstm_windows, hf.forecast_gr4j, hf.forecast_lstm, hf.forcing_for_leads):
        names = set(inspect.signature(fn).parameters)
        assert not {n for n in names if n.startswith(("q", "flow", "obs"))} - {"q"}, fn
    rng = np.random.default_rng(0)
    dyn = rng.random((800, 5))
    static = np.array([1.0, 2.0, 3.0])
    fc = rng.random((5, 4, 5))
    pos = 500
    x = hf.build_lstm_windows(dyn, static, pos, fc, _norm())
    assert x.shape == (5, 4, 365, lstm.n_inputs("sim")) and lstm.n_inputs("sim") == 8
    poisoned = dyn.copy()
    poisoned[pos:] = np.nan  # nothing at or after the issue day may be read from the history
    x2 = hf.build_lstm_windows(poisoned, static, pos, fc, _norm())
    np.testing.assert_array_equal(x, x2)
    # lead 1 window ends with the first forecast day; lead 3 has 3 forecast days at its end
    np.testing.assert_allclose(x[2, 0, -1, :5], fc[2, 0])
    np.testing.assert_allclose(x[2, 2, -3:, :5], fc[2, :3])
    np.testing.assert_allclose(x[2, 2, : 365 - 3, :5], dyn[pos - 362 : pos])
    np.testing.assert_allclose(x[0, 0, :, 5:], np.tile(static, (365, 1)))
    with pytest.raises(ValueError):
        hf.build_lstm_windows(dyn, static, 100, fc, _norm())


def test_forcing_for_leads_climatology_vs_perfect():
    d = pd.date_range("2000-01-01", "2010-12-31")
    x = np.column_stack([np.zeros(len(d)), np.full(len(d), 10.0), np.full(len(d), 5.0),
                         np.full(len(d), 15.0), np.full(len(d), 2.0)])  # fmt: skip
    basin = lstm.Basin("1", d, x, np.zeros(len(d)), np.array([0.0, 0.0, 0.0]), "neuquen")
    st = hf.Station(1, basin, 1000.0, -37.5, pd.DataFrame({"date": d, "q_m3s": 1.0}))
    clim = {k: np.full(366, v) for k, v in (("tmean", 8.0), ("tmin", 3.0), ("tmax", 13.0))}
    issue = pd.Timestamp("2005-07-01")
    c = hf.forcing_for_leads(st, issue, 3, clim)
    p = hf.forcing_for_leads(st, issue, 3, None)
    assert np.isnan(c[:, 0]).all() and np.isnan(p[:, 0]).all()
    np.testing.assert_allclose(c[:, 1:4], [[8, 3, 13]] * 3)
    np.testing.assert_allclose(p[:, 1:], [[10, 5, 15, 2]] * 3)
    np.testing.assert_allclose(
        c[:, 4],
        forcing.oudin_pet(
            np.full(3, 8.0), -37.5, pd.date_range(issue, periods=3).day_of_year.to_numpy()
        ),
    )


# --- probability and scores -------------------------------------------------------------------


def test_dress_and_probability():
    zero = np.zeros(10)
    s = hf.dress([5.0, 15.0], zero)
    np.testing.assert_allclose(sorted(s), [5.0] * 10 + [15.0] * 10)
    assert hf.exceed_probability(s, 10.0) == 0.5
    assert hf.exceed_probability(s, 20.0) == 0.0
    # a residual of +log 2 doubles the flow (eps-form): (sim + eps) * 2 - eps
    s2 = hf.dress([5.0], np.array([np.log(2.0)]))
    assert s2[0] == pytest.approx((5.0 + hf.EPS_MM) * 2 - hf.EPS_MM)
    # members x residuals mixture and the 90 % interval
    grid = hf.residual_grid(np.log(np.linspace(0.5, 2.0, 501)))
    assert len(grid) == hf.N_RESID and np.all(np.diff(grid) >= 0)
    mix = hf.dress([10.0, 20.0, 30.0, 40.0, 50.0], grid)
    assert len(mix) == 5 * hf.N_RESID
    lo, hi = hf.interval90(mix)
    assert lo == pytest.approx(np.quantile(mix, 0.05)) and hi == pytest.approx(
        np.quantile(mix, 0.95)
    )
    assert lo < 10.0 * 1.2 and hi > 50.0 * 0.9
    # never negative
    assert (hf.dress([0.0], np.array([-20.0])) >= 0).all()


def test_log_residuals_mask_and_nan():
    obs = np.array([1.0, 2.0, np.nan, 4.0])
    sim = np.array([1.0, 1.0, 1.0, np.nan])
    r = hf.log_residuals(obs, sim, np.array([True, True, True, True]))
    assert len(r) == 2 and r[0] == pytest.approx(0.0)
    assert len(hf.log_residuals(obs, sim, np.array([False, True, True, True]))) == 1


def test_brier_wilson_bootstrap():
    assert hf.brier([1.0, 0.0], [1, 0]) == 0.0
    assert hf.brier([0.5, 0.5], [1, 0]) == 0.25
    lo, hi = hf.wilson(9, 10)
    assert lo < 0.9 < hi and 0 <= lo and hi <= 1
    assert hf.wilson(0, 0) == (0.0, 1.0)
    rng = np.random.default_rng(3)
    ref = rng.random(20) + 0.5
    better = ref * 0.4
    r = hf.bss_bootstrap(better, ref, n_boot=1000, seed=1)
    assert r["bss"] == pytest.approx(0.6) and r["n_floods"] == 20
    assert 0 < r["lo"] <= r["bss"] <= r["hi"] <= 1
    assert r == hf.bss_bootstrap(better, ref, n_boot=1000, seed=1)  # fixed seed, reproducible
    same = hf.bss_bootstrap(ref, ref)
    assert same["bss"] == 0.0 and same["lo"] == 0.0 and same["hi"] == 0.0
    worse = hf.bss_bootstrap(ref * 2, ref)
    assert worse["hi"] < 0
    nan = hf.bss_bootstrap(np.zeros(3), np.zeros(3))
    assert np.isnan(nan["bss"])


def _pairs(n_floods: int, skill: bool) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(0)
    for f in range(n_floods):
        peak = pd.Timestamp("2006-07-12") + pd.Timedelta(days=400 * f)
        for t in hd.window_days(peak):
            for lead in range(1, 11):
                v = t + pd.Timedelta(days=lead - 1)
                if abs((v - peak).days) > 15:
                    continue
                o = float(v >= peak - pd.Timedelta(days=1) and v <= peak + pd.Timedelta(days=1))
                p = (0.8 if o else 0.02) if skill else 0.1
                rows.append(
                    {
                        "fold": 2006 + f, "station_id": 12004, "hydro_year": 2006 + f,
                        "peak_date": peak, "q_peak_m3s": 100.0, "out_of_range": False,
                        "issue": t, "lead": lead, "valid": v, "model": "gr4j", "variant": "main",
                        "thr_m3s": 50.0, "p": p + (rng.normal(0, 0.005) if skill else 0.0), "lo_m3s": 60.0,
                        "hi_m3s": 140.0, "p_clim": 0.1, "obs_m3s": 100.0 if o else 10.0,
                        "is_peak": v == peak, "outcome": o,
                    }
                )  # fmt: skip
    return pd.DataFrame(rows)


def test_lead_metrics_skill_and_no_skill():
    good = hf.lead_metrics(_pairs(8, True), n_boot=200)["main"]["gr4j"]
    assert sorted(good) == list(range(1, 11))
    assert all(e["n_floods"] == 8 and e["rises"] == 8 for e in good.values())
    assert all(e["coverage"] == 1.0 for e in good.values())
    assert all(e["bss_clim"]["bss"] > 0.5 and e["passes"] for e in good.values())
    bad = hf.lead_metrics(_pairs(8, False), n_boot=200)["main"]["gr4j"]
    assert not any(e["passes"] for e in bad.values())  # p == p_clim: BSS = 0, CI not above 0


def test_contiguous_leads_rule():
    pairs = _pairs(8, True)
    # break lead 3: probability equal to climatology there -> BSS 0 -> L >= 3 must all fail
    m = pairs["lead"] == 3
    pairs.loc[m, "p"] = pairs.loc[m, "p_clim"]
    res = hf.lead_metrics(pairs, n_boot=200)["main"]["gr4j"]
    assert res[1]["passes"] and res[2]["passes"]
    assert not res[3]["passes"] and not res[3]["passes_alone"]
    assert res[4]["passes_alone"] and not res[4]["passes"]  # a shorter lead fails
    assert res[10]["passes_alone"] and not res[10]["passes"]


def test_flood_lead_table_verdicts():
    t = hf.flood_lead_table(_pairs(2, True))
    assert len(t) == 2 * 10
    assert (t["verdict_gr4j"] == hf.V_RISES).all() and t["inside_gr4j"].all()
    t2 = hf.flood_lead_table(_pairs(2, False))
    assert (t2["verdict_gr4j"] == hf.V_NOT).all()


# --- sharded LSTM training (pretrain / fine-tune per seed, assemble from saved weights) ----------


def _tiny(group: str, seed: int = 0) -> lstm.Basin:
    d = pd.date_range("2003-01-01", "2016-12-31")
    rng = np.random.default_rng(seed)
    doy = d.day_of_year.to_numpy()
    p = rng.gamma(0.5, 6, len(d))
    x = np.column_stack(
        [p, 8 + 8 * np.cos(2 * np.pi * (doy - 15) / 365), 3 + np.zeros(len(d)), 14 + np.zeros(len(d)),
         2 + np.zeros(len(d))]
    )  # fmt: skip
    q = 0.5 + 0.1 * np.convolve(p, np.ones(5) / 5, "same") + rng.normal(0, 0.02, len(d)).clip(0)
    return lstm.Basin(
        id="1" if group == "neuquen" else "c1", dates=d, x=x, q=q,
        static=np.array([5.0, 7.0, 0.3]), group=group,
    )  # fmt: skip


def _tiny_stations() -> dict[int, hf.Station]:
    b = _tiny("neuquen")
    flow_df = pd.DataFrame({"date": b.dates, "q_m3s": b.q * 100.0})
    return {1: hf.Station(sid=1, basin=b, area_km2=100.0, lat=-37.0, flow=flow_df)}


@pytest.fixture
def fast_train(monkeypatch):
    """Few validation windows per epoch so that the tiny LSTM runs take seconds."""
    import dataclasses

    orig = hf.RunConfig.train_config
    monkeypatch.setattr(
        hf.RunConfig,
        "train_config",
        lambda self, p: dataclasses.replace(orig(self, p), val_samples=32),
    )


def _same_state(a, b) -> bool:
    return all(np.array_equal(a[k].numpy(), b[k].numpy()) for k in a)


@pytest.mark.slow
def test_sharded_pretrain_and_fold_training_match_unsharded(tmp_path, fast_train):
    pytest.importorskip("torch")
    rc = hf.RunConfig(seeds=2, epochs=1, pretrain_epochs=1, samples_per_epoch=64)
    camels = [_tiny("camels", 5)]
    stations = _tiny_stations()
    fold = 2010
    quiet = lambda *_: None

    # unsharded: everything in one process
    pre_a = hf.pretrain_once(camels, rc, tmp_path / "a" / "pretrain", quiet)
    run_a, grids_a, info_a = hf.train_lstm_fold(
        stations, fold, rc, pre_a, quiet, out_dir=tmp_path / "a" / f"fold-{fold}"
    )

    # sharded: one seed per call, the fine-tuning from the saved pretraining only
    for k in (0, 1):
        hf.pretrain_once(camels, rc, tmp_path / "b" / "pretrain", quiet, seed_list=[k])
    pre_b = hf.load_pretrained(rc, tmp_path / "b" / "pretrain")
    assert (tmp_path / "b" / "pretrain" / "norm.json").read_text() == (
        tmp_path / "a" / "pretrain" / "norm.json"
    ).read_text()
    for k in (0, 1):
        assert hf.train_lstm_fold(
            stations, fold, rc, pre_b, quiet, out_dir=tmp_path / "b" / f"fold-{fold}",
            seed_list=[k], train_only=True,
        ) is None  # fmt: skip
    # assemble: loads the saved weights and refuses to train anything
    calls = []
    run_b, grids_b, info_b = hf.train_lstm_fold(
        stations, fold, rc, pre_b, calls.append, out_dir=tmp_path / "b" / f"fold-{fold}",
        allow_train=False,
    )  # fmt: skip
    assert not any("fine-tuning" in c for c in calls) and sum("loaded" in c for c in calls) == 2
    for ma, mb in zip(run_a.models, run_b.models, strict=True):
        assert _same_state(ma.state_dict(), mb.state_dict())
    np.testing.assert_array_equal(grids_a[1], grids_b[1])
    assert info_a["best_epochs"] == info_b["best_epochs"]


def test_saved_weights_are_required_and_config_is_checked(tmp_path, fast_train):
    pytest.importorskip("torch")
    rc = hf.RunConfig(seeds=1, epochs=1, pretrain_epochs=1, samples_per_epoch=64)
    stations = _tiny_stations()
    out = tmp_path / "fold-2010"
    with pytest.raises(FileNotFoundError, match="no saved weights"):
        hf.train_lstm_fold(stations, 2010, rc, None, print, out_dir=out, allow_train=False)
    hf.train_lstm_fold(stations, 2010, rc, None, print, out_dir=out, train_only=True, seed_list=[0])
    other = hf.RunConfig(seeds=1, epochs=2, pretrain_epochs=1, samples_per_epoch=64)
    with pytest.raises(ValueError, match="another configuration"):
        hf.train_lstm_fold(stations, 2010, other, None, print, out_dir=out)
    with pytest.raises(FileNotFoundError, match="pretraining"):
        hf.load_pretrained(rc, tmp_path / "nothing")
    hf.pretrain_once([_tiny("camels")], rc, tmp_path / "pre", lambda *_: None)
    with pytest.raises(ValueError, match="another configuration"):
        hf.load_pretrained(other.__class__(seeds=1, epochs=1, pretrain_epochs=3), tmp_path / "pre")

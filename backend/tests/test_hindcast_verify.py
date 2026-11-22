"""F5.2: verification scores and ERA5 observed days, all offline."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import observe, store
from clima_nqn.stages.hindcast import verify as v

SPEC = fc.MODELS["gefs-reforecast"]


# --- scores ----------------------------------------------------------------------------------


def test_fair_crps_hand_values():
    # members [0, 2], obs 1: mean|x-y| = 1; pair sum 4 / (2*2*1) = 1 -> 0
    assert v.fair_crps(np.array([[0.0, 2.0]]), np.array([1.0]))[0] == pytest.approx(0.0)
    # members [0, 1, 2], obs 0: 1 - 8/12
    assert v.fair_crps(np.array([[0.0, 1.0, 2.0]]), np.array([0.0]))[0] == pytest.approx(1 / 3)
    # NaN member dropped: [0, nan, 2] -> same as [0, 2]
    out = v.fair_crps(np.array([[0.0, np.nan, 2.0]]), np.array([1.0]))
    assert out[0] == pytest.approx(0.0)
    assert np.isnan(v.fair_crps(np.array([[np.nan, np.nan]]), np.array([1.0]))[0])


def test_fair_crps_single_member_is_abs_error():
    x, y = np.array([[3.0], [1.0]]), np.array([5.0, 1.0])
    assert list(v.fair_crps(x, y)) == [2.0, 0.0]


def test_crps_vs_empirical_leave_one_out():
    obs = np.array([0.0, 1.0, 2.0])
    out = v.crps_vs_empirical(obs)
    # case 0: reference [1, 2], y=0 -> 1.5 - 2/(2*2*1)... pair sum = 2*|1-2| = 2 -> 1.5 - 0.5 = 1.0
    assert out[0] == pytest.approx(1.0)
    direct = v.fair_crps(np.array([[1.0, 2.0]]), np.array([0.0]))[0]
    assert out[0] == pytest.approx(direct)
    assert out[1] == pytest.approx(v.fair_crps(np.array([[0.0, 2.0]]), np.array([1.0]))[0])


def test_contingency_perfect_and_counts():
    obs = np.array([0.0, 6.0, 7.0, 1.0])
    ct = v.contingency(obs, obs, 5.0)
    assert ct["ets"] == pytest.approx(1.0) and ct["pod"] == 1 and ct["far"] == 0
    ct = v.contingency(np.array([6.0, 6.0, 0.0, 0.0]), obs, 5.0)
    assert (ct["hits"], ct["misses"], ct["false_alarms"], ct["correct_neg"]) == (1, 1, 1, 1)
    assert ct["freq_bias"] == pytest.approx(1.0)
    assert ct["ets"] == pytest.approx((1 - 1.0) / (3 - 1.0))  # no skill beyond chance
    assert np.isnan(v.contingency(np.zeros(3), np.zeros(3), 5.0)["pod"])


def test_brier_bss():
    o = np.array([1, 0, 1, 0])
    assert v.brier(o.astype(float), o) == 0
    assert v.bss(o.astype(float), o) == pytest.approx(1.0)
    assert np.isnan(v.bss(np.zeros(3), np.zeros(3)))  # no event: reference has no error


def test_roc_auc_ties_and_empty():
    assert v.roc_auc(np.array([1, 2, 3, 4.0]), np.array([0, 0, 1, 1])) == 1.0
    assert v.roc_auc(np.array([1, 1, 1, 1.0]), np.array([0, 0, 1, 1])) == 0.5
    assert v.roc_auc(np.array([1, 2, 2, 3.0]), np.array([0, 1, 0, 1])) == pytest.approx(0.875)
    assert np.isnan(v.roc_auc(np.array([1.0, 2.0]), np.array([1, 1])))


def test_episodes_group_by_gap():
    d = pd.to_datetime(["2020-01-10", "2020-01-01", "2020-01-03", "2020-01-20", "2020-01-13"])
    ids = v.episodes(d, gap_days=3)
    assert ids[1] == ids[2]  # Jan 1 and Jan 3
    assert ids[0] != ids[1] and ids[4] != ids[0] or ids[0] == ids[4]
    assert ids[0] == ids[4]  # Jan 10 and Jan 13: gap 3 is still the same episode
    assert len(set(ids)) == 3


def test_box_mean_cos_weighting_and_nan():
    lat, lon = np.array([0.0, 60.0]), np.array([0.0, 1.0])
    da = xr.DataArray(
        [[1.0, 1.0], [3.0, 3.0]], coords={"lat": lat, "lon": lon}, dims=("lat", "lon")
    )
    assert float(v.box_mean(da)) == pytest.approx((1 * 1 + 3 * 0.5) / 1.5)
    nan = da.copy(data=np.full((2, 2), np.nan))
    assert np.isnan(float(v.box_mean(nan)))
    part = da.copy(data=[[np.nan, np.nan], [3.0, 3.0]])
    assert float(v.box_mean(part)) == pytest.approx(3.0)


def test_bootstrap_reproducible():
    ids = np.array([0, 0, 1, 2, 2, 3, 4, 4])
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    fn = lambda i: x[i].mean()
    a = v.bootstrap_ci(fn, ids, n=200, seed=3)
    assert a == v.bootstrap_ci(fn, ids, n=200, seed=3)
    assert a != v.bootstrap_ci(fn, ids, n=200, seed=4)
    assert a[0] < x.mean() < a[1]
    assert all(np.isnan(v.bootstrap_ci(lambda i: np.nan, ids, n=10)))


# --- verify_model ----------------------------------------------------------------------------


def _synthetic(perfect: bool = True):
    n = 12
    dates = pd.date_range("2005-01-05", periods=n, freq="10D")
    cases = pd.DataFrame(
        {
            "case_id": [f"c{i:02d}" for i in range(n)],
            "kind": ["event", "control"] * (n // 2),
            "event_id": [None] * n,
            "valid_date": dates,
        }
    )
    ds = store.empty_store(SPEC, cases, (1, 2))
    obs = np.where(np.arange(n) % 2 == 0, 12.0, 0.5)
    for i in range(n):
        ds["precip_mm"].values[i] = obs[i] if perfect else 6.0
    ds["status"].values[:] = fc.STATUS_OK
    ds.attrs["model"] = "gefs-reforecast"
    return ds, pd.Series(obs, index=dates), obs


def _get(df, lead, kind, metric, thr=np.nan):
    s = df[(df.lead == lead) & (df.kind == kind) & (df.metric == metric)]
    s = s[s.threshold.isna()] if np.isnan(thr) else s[s.threshold == thr]
    return s.iloc[0]


def test_verify_model_perfect_forecast():
    ds, obs, _ = _synthetic()
    df = v.verify_model(ds, obs, n_boot=30)
    assert list(df.columns) == v.COLUMNS
    assert set(df["lead"]) == {1, 2}
    for lead in (1, 2):
        assert _get(df, lead, "all", "n")["value"] == 12
        assert _get(df, lead, "all", "crps")["value"] == pytest.approx(0, abs=1e-6)
        assert _get(df, lead, "all", "crpss")["value"] == pytest.approx(1, abs=1e-6)
        assert _get(df, lead, "event", "bias")["value"] == pytest.approx(0, abs=1e-6)
        assert _get(df, lead, "all", "ets", 5.0)["value"] == pytest.approx(1.0)
        assert _get(df, lead, "all", "ets", 5.0)["lo"] == pytest.approx(1.0)
        assert _get(df, lead, "all", "auc", 5.0)["value"] == 1.0
        assert _get(df, lead, "all", "bss", 5.0)["value"] == pytest.approx(1.0)
    assert v.useful_horizon(df, 5.0) == {"gefs-reforecast": {"ets": 2, "auc": 2, "both": 2}}


def test_verify_model_flat_forecast_and_missing_status():
    ds, obs, o = _synthetic(perfect=False)
    ds["status"].values[0, 0, :] = fc.STATUS_MISSING  # case 0 (event) lacks lead 1
    df = v.verify_model(ds, obs, n_boot=30)
    assert _get(df, 1, "all", "n")["value"] == 11
    assert _get(df, 2, "all", "n")["value"] == 12
    assert _get(df, 1, "event", "n")["value"] == 5
    assert _get(df, 2, "all", "auc", 5.0)["value"] == 0.5  # flat score: no discrimination
    assert _get(df, 2, "all", "mae")["value"] == pytest.approx(np.abs(6.0 - o).mean())
    assert v.useful_horizon(df, 5.0)["gefs-reforecast"]["both"] == 0


def test_verify_model_cell_level():
    ds, obs, o = _synthetic(perfect=False)
    dates = obs.index
    cells = xr.DataArray(
        np.broadcast_to(o[:, None, None], (len(o), len(fc.LAT), len(fc.LON))).copy(),
        coords={"date": dates, "lat": fc.LAT, "lon": fc.LON},
        dims=("date", "lat", "lon"),
    )
    df = v.verify_model(ds, obs, n_boot=10, obs_cells=cells)
    assert _get(df, 1, "all", "cell_mae")["value"] == pytest.approx(np.abs(6.0 - o).mean())
    assert _get(df, 1, "all", "cell_bias")["value"] == pytest.approx((6.0 - o).mean())
    assert df[(df.kind == "control") & (df.metric == "cell_mae")].empty


def _horizon_df(ets_lo, auc_lo):
    rows = []
    for lead, (e, a) in enumerate(zip(ets_lo, auc_lo, strict=True), start=1):
        for metric, lo in (("ets", e), ("auc", a)):
            rows.append(
                {"model": "m", "lead": lead, "kind": "all", "threshold": 5.0, "metric": metric,
                 "value": 0.0, "lo": lo, "hi": 1.0, "n": 10}
            )  # fmt: skip
    return pd.DataFrame(rows, columns=v.COLUMNS)


def test_useful_horizon_requires_consecutive_leads():
    df = _horizon_df([0.2, 0.1, -0.1, 0.3], [0.6, 0.6, 0.6, 0.6])
    assert v.useful_horizon(df, 5.0) == {"m": {"ets": 2, "auc": 4, "both": 2}}
    df = _horizon_df([0.2, 0.1, 0.1], [0.6, 0.5, 0.7])  # AUC lo must be strictly > 0.5
    assert v.useful_horizon(df, 5.0) == {"m": {"ets": 3, "auc": 1, "both": 1}}
    assert v.useful_horizon(df, 1.0) == {}


def test_render_md_sections():
    ds, obs, _ = _synthetic()
    df = v.verify_model(ds, obs, n_boot=10)
    hz = {t: v.useful_horizon(df, t) for t in (5.0, 1.0, 10.0)}
    meta = {
        "models": {"gefs-reforecast": {"source": "s", "period": "p", "n_event": 6, "n_control": 6}}
    }
    md = v.render_md(df, hz, meta)
    for head in (
        "## Veredicto",
        "## Fuente y alcance",
        "## Regla fijada antes de correr",
        "## Advertencias",
    ):
        assert head in md
    assert "<!-- veredicto: lo escribe Opus -->" in md
    assert "1,00 [1,00; 1,00]" in md


# --- observe ---------------------------------------------------------------------------------

T0 = pd.Timestamp("2020-01-01")


def fake_arco(stop: str = "2026-06-30"):
    """ARCO-like store: 0..360 lon, descending lat; tp (m) at every step = hour index * 1e-3."""
    times = pd.date_range(T0, "2020-01-10", freq="h")
    lat = np.arange(-30.0, -45.0 - 1e-6, -0.25)
    lon = np.arange(280.0, 300.0 + 1e-6, 0.25)
    hours = np.arange(len(times), dtype="float32") * 1e-3
    tp = np.broadcast_to(hours[:, None, None], (len(times), len(lat), len(lon))).copy()
    ds = xr.Dataset(
        {"total_precipitation": (("time", "latitude", "longitude"), tp)},
        coords={"time": times, "latitude": lat, "longitude": lon},
        attrs={"valid_time_stop": stop},
    )
    return ds


def test_observed_days_uses_hours_d1_to_d1_midnight():
    logs: list[str] = []
    ds = observe.observed_days(
        ["2020-01-03", "2020-01-03", pd.Timestamp("2020-01-05")],
        opener=fake_arco,
        workers=4,
        retries=1,
        log_fn=logs.append,
    )
    assert list(ds["date"].values.astype("datetime64[D]")) == [
        np.datetime64("2020-01-03"),
        np.datetime64("2020-01-05"),
    ]
    assert ds["precip_mm"].dtype == np.float32
    assert np.allclose(ds["lat"], fc.LAT) and np.allclose(ds["lon"], fc.LON)
    # day 2020-01-03: hour indices 49..72 (D 01:00 .. D+1 00:00), sum = 1452
    assert np.allclose(ds["precip_mm"].sel(date="2020-01-03").values, 1452.0)
    assert np.allclose(ds["precip_mm"].sel(date="2020-01-05").values, sum(range(97, 121)))
    assert ds.attrs["era5t"] is False and "01:00" in ds.attrs["window"]
    assert ds.attrs["source"] and ds.attrs["license"] == "CC-BY 4.0"
    assert logs


def test_observed_days_flags_era5t_and_roundtrip(tmp_path):
    ds = observe.observed_days(["2020-01-03"], opener=lambda: fake_arco("2020-01-02"), retries=1)
    assert ds.attrs["era5t"] is True
    observe.write_obs(ds, tmp_path / "obs.zarr")
    back = observe.read_obs(tmp_path / "obs.zarr")
    assert np.array_equal(back["precip_mm"].values, ds["precip_mm"].values)
    assert not (tmp_path / "obs.zarr.tmp").exists()
    observe.write_obs(ds, tmp_path / "obs.zarr")  # replace in place


def test_eligible_dates_union_of_model_periods():
    days = ["1990-05-05", "2005-03-03", "2005-03-03", "2019-12-31", "2020-06-01", "2023-01-10",
            "2024-06-01", "2026-02-01"]  # fmt: skip
    cases = pd.DataFrame(
        {
            "case_id": [f"c{i}" for i in range(len(days))],
            "kind": "event",
            "event_id": "e",
            "valid_date": pd.to_datetime(days),
        }
    )
    got = observe.eligible_dates(cases)
    # 1990 / 2020-06 / 2023-01-10 (before IFS start 2023-01-28) / 2026 are outside every model period
    assert got == [pd.Timestamp(d) for d in ("2005-03-03", "2019-12-31", "2024-06-01")]

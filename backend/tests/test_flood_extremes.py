import json

import numpy as np
import pandas as pd
import pytest
from scipy.stats import genextreme

from clima_nqn.stages.flood import extremes

N_BOOT = 20  # small bootstrap: tests only check structure, not CI width


def daily(start, end, value=10.0, drop=()):
    """Daily frame like ``read_flow`` output; ``drop`` dates become NaN."""
    dates = pd.date_range(start, end, freq="D", name="date")
    q = pd.Series(value, index=dates, dtype=float)
    q.loc[[pd.Timestamp(d) for d in drop]] = np.nan
    return pd.DataFrame({"date": dates, "q_m3s": q.to_numpy()})


def synthetic_maxima(c, loc, scale, n=2000, seed=0):
    x = genextreme.rvs(c, loc=loc, scale=scale, size=n, random_state=seed)
    return pd.Series(x, index=pd.date_range("1000-06-01", periods=n, freq="365D"))


# --- annual_maxima ---------------------------------------------------------------------------


def test_annual_maxima_assigns_hydro_year_and_crosses_new_year():
    df = daily("2000-04-01", "2003-03-31")  # 3 complete hydro years: 2000, 2001, 2002
    df.loc[df["date"] == "2001-02-10", "q_m3s"] = 99.0  # belongs to hydro year 2000
    df.loc[df["date"] == "2001-04-01", "q_m3s"] = 50.0  # first day of hydro year 2001
    df.loc[df["date"] == "2002-12-31", "q_m3s"] = 70.0  # hydro year 2002
    maxima, excluded = extremes.annual_maxima(df, start_month=4, min_valid=330)
    assert list(maxima["hydro_year"]) == [2000, 2001, 2002]
    assert list(maxima["q_m3s"]) == [99.0, 50.0, 70.0]
    assert list(maxima["date"].dt.strftime("%Y-%m-%d")) == [
        "2001-02-10",
        "2001-04-01",
        "2002-12-31",
    ]
    assert excluded.empty


def test_annual_maxima_330_day_rule_boundary():
    df = daily("2000-04-01", "2003-03-31")
    year2000 = df[(df["date"] >= "2000-04-01") & (df["date"] < "2001-04-01")]
    year2001 = df[(df["date"] >= "2001-04-01") & (df["date"] < "2002-04-01")]
    # keep 329 valid days in 2000 and exactly 330 in 2001 (366 / 365 days each)
    n_drop_2000 = len(year2000) - 329
    n_drop_2001 = len(year2001) - 330
    drop = list(year2000["date"].iloc[:n_drop_2000]) + list(year2001["date"].iloc[:n_drop_2001])
    df.loc[df["date"].isin(drop), "q_m3s"] = np.nan
    maxima, excluded = extremes.annual_maxima(df, start_month=4, min_valid=330)
    assert list(maxima["hydro_year"]) == [2001, 2002]
    assert list(excluded["hydro_year"]) == [2000]
    assert list(excluded["valid_days"]) == [329]


# --- empirical return period -----------------------------------------------------------------


def test_empirical_return_period_weibull():
    t = extremes.empirical_return_period(np.array([5.0, 9.0, 1.0, 7.0]))
    # n = 4: ranks of [5, 9, 1, 7] are [3, 1, 4, 2] -> T = 5 / rank
    assert t.tolist() == pytest.approx([5 / 3, 5.0, 5 / 4, 5 / 2])
    assert t.max() == 5.0  # max of n years gets n + 1


# --- GEV fit ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("c", "label"),
    [(-0.2, "heavy tail (xi = +0.2)"), (0.2, "bounded tail (xi = -0.2)")],
)
def test_fit_gev_recovers_synthetic_parameters(c, label):
    # n = 2000, fixed seed. Tolerance: loc and scale within 5 %, shape within 0.05 absolute.
    loc, scale = 500.0, 120.0
    res = extremes.fit_gev(synthetic_maxima(c, loc, scale), n_samples=N_BOOT)
    assert res["loc"] == pytest.approx(loc, rel=0.05), label
    assert res["scale"] == pytest.approx(scale, rel=0.05), label
    assert abs(res["shape_xi"] - (-c)) < 0.05, label
    assert res["shape_c_scipy"] == pytest.approx(-res["shape_xi"])


def test_return_levels_increase_and_ci_brackets_estimate():
    maxima = synthetic_maxima(-0.1, 300.0, 80.0, n=40, seed=3)
    res = extremes.fit_gev(maxima, n_samples=50)  # enough resamples for stable percentiles
    levels = res["return_levels"]
    assert [r["return_period"] for r in levels] == [2, 5, 10, 25, 50, 100]
    values = [r["value"] for r in levels]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    for r in levels:
        assert r["ci95_low"] <= r["value"] <= r["ci95_high"]
    assert res["n_samples"] == 50
    assert 0.0 <= res["ks_pvalue"] <= 1.0


def test_fit_gev_is_deterministic_with_seed():
    maxima = synthetic_maxima(-0.1, 300.0, 80.0, n=30, seed=5)
    a = extremes.fit_gev(maxima, n_samples=N_BOOT)
    b = extremes.fit_gev(maxima, n_samples=N_BOOT)
    assert a["return_levels"] == b["return_levels"]


# --- station level -----------------------------------------------------------------------------


def test_station_result_json_roundtrip(tmp_path):
    rng = np.random.default_rng(1)
    years = range(1990, 2030)
    parts = []
    for y in years:
        d = daily(f"{y}-04-01", f"{y + 1}-03-31")
        d.loc[rng.integers(0, len(d)), "q_m3s"] = 100 + rng.gamma(2, 50)
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df.attrs.update({"fetched": "2026-11-09", "source": extremes.flow.SOURCE})
    meta = {"id": 1, "name": "X", "river": "R", "area_km2": 10.0, "hydro_year_start_month": 4}
    res = extremes.station_result(df, meta, n_samples=N_BOOT)
    assert res["n_years"] == 40
    assert res["fetched"] == "2026-11-09"
    top = res["annual_maxima"][0]
    assert top["empirical_T"] == 41.0
    path = extremes.write_station_json(res, tmp_path)
    loaded = json.loads(path.read_text())
    assert loaded["station_id"] == 1
    assert loaded["source"] == extremes.flow.SOURCE


def test_station_json_has_no_infinite_values(tmp_path):
    result = {"station_id": 1, "annual_maxima": [{"gev_T": float("inf")}], "x": float("-inf")}
    path = extremes.write_station_json(result, tmp_path)
    data = json.loads(path.read_text())
    assert data["annual_maxima"][0]["gev_T"] is None
    assert data["x"] is None


def test_report_t_formats_missing_return_period():
    assert extremes._t(None) == "> 10 000"

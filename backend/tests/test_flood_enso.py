import json
import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import genextreme
from typer.testing import CliRunner

from clima_nqn.cli import app
from clima_nqn.io import flow
from clima_nqn.stages.flood import enso as fe
from clima_nqn.stages.flood import extremes

PLAIN = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "COLUMNS": "200",
}  # plain, unwrapped help on any runner (CI forces colour)


def monthly_oni(first_year, last_year, fn):
    """Monthly ONI table like ``read_enso``; ``fn(date)`` gives the value."""
    dates = pd.date_range(f"{first_year}-01-01", f"{last_year}-12-01", freq="MS")
    return pd.DataFrame({"date": dates, "oni": [fn(d) for d in dates]})


def daily(start, end, value=10.0, peaks=()):
    """Daily frame like ``read_flow``; ``peaks`` is a list of (date, value)."""
    dates = pd.date_range(start, end, freq="D", name="date")
    q = pd.Series(value, index=dates, dtype=float)
    for d, v in peaks:
        q.loc[pd.Timestamp(d)] = v
    return pd.DataFrame({"date": dates, "q_m3s": q.to_numpy()})


# --- covariate ---------------------------------------------------------------------------------


def test_hydro_covariate_is_amjjas_mean_of_the_hydro_year():
    # ONI = month number for 2000 -> Apr..Sep = 4..9, mean 6.5; other months must not leak in
    enso = monthly_oni(1999, 2001, lambda d: float(d.month) if d.year == 2000 else 99.0)
    assert fe.hydro_covariate(enso, 2000) == pytest.approx(6.5)
    assert math.isnan(fe.hydro_covariate(enso, 2002))  # year not in the table


def test_hydro_covariate_nan_when_a_month_is_missing():
    enso = monthly_oni(2000, 2000, lambda d: 1.0)
    enso = enso[enso["date"].dt.month != 7]
    assert math.isnan(fe.hydro_covariate(enso, 2000))


# --- phase grouping ----------------------------------------------------------------------------


def hand_built():
    # hydro years 2000 (Nino-like), 2001 (neutral), 2002 (Nina-like) complete; 2003 incomplete
    oni = {2000: 1.0, 2001: 0.0, 2002: -1.0, 2003: -1.0}
    enso = monthly_oni(2000, 2003, lambda d: oni[d.year])
    df = daily(
        "2000-04-01",
        "2003-05-31",
        peaks=[
            ("2000-06-10", 40.0),
            ("2001-11-05", 30.0),
            ("2002-09-20", 20.0),
            ("2003-05-01", 99.0),
        ],
    )
    df.loc[(df["date"] >= "2003-04-01") & (df["date"] < "2003-04-20"), "q_m3s"] = np.nan
    df = df[~((df["date"] >= "2003-04-01") & (df["date"] < "2003-04-20"))]  # 2003: 42 days only
    return df, enso


def test_station_table_maxima_phase_and_seasonal_mean():
    df, enso = hand_built()
    t = fe.station_table(df, enso)
    assert list(t["hydro_year"]) == [2000, 2001, 2002]  # 2003 incomplete -> excluded
    assert list(t["q_max"]) == [40.0, 30.0, 20.0]
    assert list(t["phase"]) == ["nino", "neutral", "nina"]
    assert list(t["oni_amjjas"]) == pytest.approx([1.0, 0.0, -1.0])
    # AMJJAS mean flow of 2000: 183 days, one at 40 and the rest at 10
    assert t["q_mean_amjjas"].iloc[0] == pytest.approx((182 * 10 + 40) / 183)
    # peaks in June (JJA), November (SON) and September (SON), as in ar.enso.SEASONS
    assert list(t["peak_season"]) == ["JJA", "SON", "SON"]
    assert list(t["oni_peak"]) == pytest.approx([1.0, 0.0, -1.0])


def test_phase_tests_report_n_per_phase_and_effects():
    df, enso = hand_built()
    t = fe.station_table(df, enso)
    res = fe.phase_tests(t, n_perm=200, seed=1)
    m = res["q_max"]
    assert m["n"] == {"nino": 1, "neutral": 1, "nina": 1}
    assert m["means"]["nino"] == 40.0 and m["means"]["nina"] == 20.0
    assert m["diff_nino_nina"] == 20.0
    assert math.isnan(m["p"])  # N <= number of groups: no test, as in F1.8


# --- GEV with covariate --------------------------------------------------------------------------


def draw(mu1, n=300, seed=7, z_seed=11):
    z = np.random.default_rng(z_seed).normal(0, 1, n)
    y = genextreme.rvs(-0.1, loc=100 + mu1 * z, scale=15, size=n, random_state=seed)
    return y, z


def test_nonstationary_fit_recovers_mu1_and_lrt_rejects():
    y, z = draw(mu1=20.0)
    r = fe.compare_gev(y, z)
    assert r["nonstationary"]["mu1"] == pytest.approx(20.0, abs=4.0)
    assert r["nonstationary"]["mu1_se"] > 0
    assert r["lrt"]["p"] < 0.001
    assert r["delta_aic"] < -10  # AIC(nonstationary) - AIC(stationary)


def test_lrt_does_not_reject_with_unrelated_covariate():
    y, z = draw(mu1=0.0)
    r = fe.compare_gev(y, z)
    assert r["lrt"]["p"] > 0.05
    assert r["lrt"]["statistic"] >= 0  # nested: the extra parameter never lowers the likelihood
    assert r["stationary"]["loglik"] <= r["nonstationary"]["loglik"] + 1e-9


def test_stationary_fit_matches_f22_gev():
    y, _ = draw(mu1=0.0)
    r = fe.compare_gev(y, np.zeros_like(y) + np.arange(len(y)) % 3)
    ref = extremes.fit_gev(
        pd.Series(y, index=pd.date_range("1000-01-01", periods=len(y), freq="365D")), n_samples=5
    )
    assert r["stationary"]["xi"] == pytest.approx(ref["shape_xi"], abs=1e-3)


# --- CLI -----------------------------------------------------------------------------------------


def write_world(tmp_path):
    flow_dir = tmp_path / "flow"
    flow_dir.mkdir()
    rng = np.random.default_rng(3)
    oni_by_year = {y: float(rng.normal()) for y in range(1950, 1990)}
    enso = monthly_oni(1950, 1989, lambda d: oni_by_year[d.year])
    enso.attrs.update({"source": "NOAA CPC ONI", "url": "https://example.test/oni"})
    enso_path = tmp_path / "oni.parquet"
    enso.to_parquet(enso_path, index=False)
    stations = []
    for sid, years in ((1001, 30), (1002, 30), (1003, 12)):
        parts = []
        for k in range(years):
            y = 1950 + k
            peak = 100 + 30 * oni_by_year[y] + rng.gumbel(0, 10)
            parts.append(
                daily(f"{y}-04-01", f"{y + 1}-03-31", peaks=[(f"{y}-07-15", max(peak, 11.0))])
            )
        df = pd.concat(parts, ignore_index=True)
        df.attrs.update({"source": flow.SOURCE, "url": flow.SNIH_URL, "fetched": "2026-11-09"})
        flow.write_flow(df, flow_dir / f"{sid}.parquet")
        stations.append(
            {
                "id": sid,
                "name": f"S{sid}",
                "river": "R",
                "area_km2": None,
                "hydro_year_start_month": 4,
            }
        )
    (flow_dir / "stations.json").write_text(
        json.dumps({"fetched": "2026-11-09", "stations": stations})
    )
    return flow_dir, enso_path


def test_cli_flow_enso_writes_report_json_flag_and_verdict(tmp_path):
    flow_dir, enso_path = write_world(tmp_path)
    out, report = tmp_path / "enso.json", tmp_path / "F2.7.md"
    res = CliRunner().invoke(
        app,
        ["flow", "enso", "--flow-dir", str(flow_dir), "--enso", str(enso_path), "--out", str(out),
         "--report", str(report), "--station", "1001", "--station", "1002", "--station", "1003",
         "--analysis-station", "1001", "--analysis-station", "1002", "--n-perm", "300"],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    data = json.loads(out.read_text())
    by_id = {s["station_id"]: s for s in data["stations"]}
    assert by_id[1003]["unreliable"] is True and by_id[1001]["unreliable"] is False
    s = by_id[1001]
    assert s["n_years"] == 30
    assert set(s["primary"]) >= {"stationary", "nonstationary", "lrt", "delta_aic"}
    assert (
        0 <= s["primary"]["lrt"]["p_bh"] <= 1
        and s["primary"]["lrt"]["p"] <= s["primary"]["lrt"]["p_bh"]
    )
    assert "alternate" in s and "phase_tests" in s
    assert data["verdict"] in ("señal", "sin señal")
    text = report.read_text()
    assert "sin verificar" in text and "NOAA CPC" in text
    assert "Veredicto F6.2: " + data["verdict"] in text
    assert "poco confiable" in text  # the short record is flagged in the report


def test_cli_flow_enso_missing_oni_is_a_clean_error(tmp_path):
    flow_dir, _ = write_world(tmp_path)
    res = CliRunner().invoke(
        app, ["flow", "enso", "--flow-dir", str(flow_dir), "--enso", str(tmp_path / "no.parquet")]
    )
    assert res.exit_code != 0 and "enso fetch" in res.output


def test_cli_flow_gev_help_unchanged():
    res = CliRunner().invoke(app, ["flow", "gev", "--help"], env=PLAIN)
    assert res.exit_code == 0 and "--flow-dir" in res.output and "--station" in res.output
    assert "--analysis-station" not in res.output


# --- addendum (L12): lagged covariate, permutation p, trend control, gate -----------------------


def test_jfm_covariate_is_jan_mar_of_the_same_calendar_year():
    # ONI = 10 * year-offset + month: Jan-Mar of 2000 -> mean of 1, 2, 3 = 2; other months must not leak in
    enso = monthly_oni(1999, 2001, lambda d: float(d.month) if d.year == 2000 else 99.0)
    assert fe.jfm_covariate(enso, 2000) == pytest.approx(2.0)
    assert math.isnan(fe.jfm_covariate(enso, 2002))
    enso = enso[enso["date"] != pd.Timestamp("2000-02-01")]
    assert math.isnan(fe.jfm_covariate(enso, 2000))  # a missing month -> NaN


def test_permutation_lrt_small_p_for_dependent_and_large_for_unrelated_covariate():
    y, z = draw(mu1=20.0, n=60)
    dep = fe.permutation_lrt(y, z, n_perm=99, seed=1)
    assert dep["p"] == pytest.approx(1 / 100)  # (0 + 1) / (99 + 1): no permutation reaches it
    assert dep["n_perm"] == 99 and dep["stat"] > 10
    y, z = draw(mu1=0.0, n=60)
    assert fe.permutation_lrt(y, z, n_perm=99, seed=1)["p"] > 0.05


def test_permutation_lrt_is_reproducible_and_matches_compare_gev_statistic():
    y, z = draw(mu1=10.0, n=60)
    a, b = fe.permutation_lrt(y, z, 30, seed=5), fe.permutation_lrt(y, z, 30, seed=5)
    assert a == b
    assert a["stat"] == pytest.approx(fe.compare_gev(y, z)["lrt"]["statistic"], rel=1e-3, abs=1e-3)


def draw_trend(mu1, slope, n=200, seed=7):
    year = np.arange(n, dtype=float)
    z = np.random.default_rng(11).normal(0, 1, n)  # unrelated to the year
    y = genextreme.rvs(
        -0.1, loc=100 + mu1 * z + slope * (year - n / 2), scale=15, size=n, random_state=seed
    )
    return y, z, year


def test_trend_control_pure_trend_does_not_reject_mu1():
    y, z, year = draw_trend(mu1=0.0, slope=0.8)
    assert fe.compare_gev(y, year)["lrt"]["p"] < 0.001  # sanity: the trend is real
    r = fe.trend_control(y, z, year)
    assert r["lrt"]["p"] > 0.05
    assert r["nonstationary"]["mu2"] == pytest.approx(0.8, abs=0.2)


def test_trend_control_recovers_mu1_with_oni_effect_plus_trend():
    y, z, year = draw_trend(mu1=20.0, slope=0.8)
    r = fe.trend_control(y, z, year)
    assert r["nonstationary"]["mu1"] == pytest.approx(20.0, abs=5.0)
    assert r["lrt"]["p"] < 0.001
    assert r["year_scaling"] == "centered and scaled for fitting; mu2 reported per year"


def test_f62_gate_needs_permutation_p_below_alpha_and_same_sign():
    assert fe.f62_gate(0.01, 120.0, 191.0) is True
    assert fe.f62_gate(0.01, -120.0, 191.0) is False  # opposite sign, even with small p
    assert fe.f62_gate(0.05, 120.0, 191.0) is False  # p must be strictly < 0.05
    assert fe.f62_gate(0.30, 120.0, 191.0) is False
    assert fe.f62_gate(math.nan, 120.0, 191.0) is False


def _res(sid, p_bh, pt_bh=(0.5, 0.5)):
    lrt = {"p_bh": p_bh}
    return {
        "station_id": sid,
        "primary": {"lrt": lrt},
        "phase_tests": {"q_max": {"p_bh": pt_bh[0]}, "q_mean_amjjas": {"p_bh": pt_bh[1]}},
    }


def test_reading_line_only_when_signal_and_exactly_one_analysis_station_passes():
    one = [_res(12004, 0.08), _res(12010, 0.02), _res(12012, 0.01)]
    assert fe.reading_line(one, "señal", (12004, 12010)) == fe.READING
    both = [_res(12004, 0.01), _res(12010, 0.02)]
    assert fe.reading_line(both, "señal", (12004, 12010)) is None
    none = [_res(12004, 0.08), _res(12010, 0.09)]
    assert fe.reading_line(none, "sin señal", (12004, 12010)) is None
    assert fe.reading_line(one, "sin señal", (12004, 12010)) is None  # verdict not "señal"
    assert fe.READING == "Lectura: señal débil, concurrente, sostenida por una estación"


def write_world_12k(tmp_path):
    """Like write_world but with the real analysis station ids so the addendum runs."""
    flow_dir = tmp_path / "flow"
    flow_dir.mkdir()
    rng = np.random.default_rng(3)
    oni_by_year = {y: float(rng.normal()) for y in range(1950, 1990)}
    enso = monthly_oni(1950, 1989, lambda d: oni_by_year[d.year])
    enso.attrs.update({"source": "NOAA CPC ONI", "url": "https://example.test/oni"})
    enso_path = tmp_path / "oni.parquet"
    enso.to_parquet(enso_path, index=False)
    stations = []
    for sid in (12004, 12010):
        parts = []
        for k in range(30):
            y = 1953 + k
            peak = 100 + 30 * oni_by_year[y] + rng.gumbel(0, 10)
            parts.append(
                daily(f"{y}-04-01", f"{y + 1}-03-31", peaks=[(f"{y}-07-15", max(peak, 11.0))])
            )
        df = pd.concat(parts, ignore_index=True)
        df.attrs.update({"source": flow.SOURCE, "url": flow.SNIH_URL, "fetched": "2026-11-09"})
        flow.write_flow(df, flow_dir / f"{sid}.parquet")
        stations.append({"id": sid, "name": f"S{sid}", "river": "R", "area_km2": None,
                         "hydro_year_start_month": 4})  # fmt: skip
    (flow_dir / "stations.json").write_text(
        json.dumps({"fetched": "2026-11-09", "stations": stations})
    )
    return flow_dir, enso_path


def test_run_addendum_does_not_change_verdict_or_bh_family(tmp_path):
    flow_dir, enso_path = write_world_12k(tmp_path)
    kw = {"flow_dir": flow_dir, "enso_path": enso_path, "stations": [12004, 12010], "n_perm": 100}
    base = fe.run(out=tmp_path / "a.json", report=tmp_path / "a.md", addendum=False, **kw)
    full = fe.run(out=tmp_path / "b.json", report=tmp_path / "b.md", addendum=True,
                  addendum_n_perm=20, **kw)  # fmt: skip
    assert full["meta"]["verdict"] == base["meta"]["verdict"]
    assert (
        full["meta"] == base["meta"] and full["meta"]["n_tests"] == 8
    )  # 2 stations x 4 tests: family untouched
    assert full["stations"] == base["stations"]  # pre-existing numbers identical, BH p included
    a = json.loads((tmp_path / "b.json").read_text())["addendum"]
    assert set(a["stations"]) == {"12004", "12010"}
    st = a["stations"]["12010"]
    assert {"permutation_primary", "lagged", "trend", "restricted"} <= set(st)
    assert {"mu1", "lrt_p", "permutation_p", "corr_with_amjjas"} <= set(st["lagged"])
    assert a["gate"]["outcome"] in ("pasa", "no pasa")
    assert "addendum" not in json.loads((tmp_path / "a.json").read_text())
    text = (tmp_path / "b.md").read_text()
    assert "Veredicto F6.2: " + full["meta"]["verdict"] in text
    assert "Adenda de robustez (posterior al resultado, no cambia el veredicto)" in text
    assert "Compuerta para F6.2" in text and "sin verificar" in text
    assert "(tests por fase y los dos LRT" in text  # BH family text kept, addendum p raw
    assert "no entran en la familia BH" in text
    assert "sin verificar" in text and "F1.8" in text
    assert "sin registro previo" in text
    assert "Adenda de robustez" not in (tmp_path / "a.md").read_text()


def test_existing_json_keys_are_pinned(tmp_path):
    flow_dir, enso_path = write_world(tmp_path)
    res = fe.run(flow_dir, enso_path, tmp_path / "o.json", tmp_path / "o.md",
                 stations=[1001], analysis=(1001,), n_perm=50)  # fmt: skip
    data = json.loads((tmp_path / "o.json").read_text())
    assert list(data) == ["verdict", "meta", "stations"]  # no addendum for non-12004/12010 stations
    assert data["meta"]["n_tests"] == 4 and data["meta"]["analysis_stations"] == [1001]
    s = data["stations"][0]
    assert s["primary"]["lrt"]["df"] == 1 and "p_bh" in s["primary"]["lrt"]
    assert res["meta"]["verdict"] == data["verdict"]

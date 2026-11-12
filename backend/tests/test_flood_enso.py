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
    res = CliRunner().invoke(app, ["flow", "gev", "--help"])
    assert res.exit_code == 0 and "--flow-dir" in res.output and "--station" in res.output
    assert "--analysis-station" not in res.output

"""F6.5 prospective verification: scores, skill table, bootstrap."""

import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from clima_nqn.forecast import baselines, scoring
from clima_nqn.forecast.registry import InputSource, PredictionRegistry, RegistryTamperError

TRAIN = "2015-01-01/2020-12-31"
INPUTS = [InputSource(name="SNIH QMD", latency_hours=24.0)]


def make_flow(end="2021-12-31", spike=None) -> pd.DataFrame:
    dates = pd.date_range("2015-01-01", end, freq="D")
    doy = baselines.day_of_year(dates)
    q = 100 + 50 * np.sin(2 * np.pi * doy / 365) + 5 * np.cos(np.arange(len(dates)) * 1.3)
    df = pd.DataFrame({"date": dates, "q_m3s": q})
    for d, v in (spike or {}).items():
        df.loc[df["date"] == pd.Timestamp(d), "q_m3s"] = v
    return df


def emit_many(tmp_path, days, flow):
    """Emit one issue day at a time (registry clock set per day); return all records."""
    path = tmp_path / "reg.jsonl"
    for day in days:
        now = datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=12)
        reg = PredictionRegistry(path, clock=lambda now=now: now)
        baselines.emit(
            reg, "12004", flow[flow["date"] < pd.Timestamp(day)], day, "v1", TRAIN, INPUTS
        )
    return PredictionRegistry(path)


def obs_of(flow) -> pd.Series:
    return flow.set_index("date")["q_m3s"]


def test_crps_perfect_forecast_is_zero() -> None:
    q = {f"{t:g}": 7.0 for t in baselines.LEVELS}
    assert scoring.crps_from_quantiles(7.0, q) == pytest.approx(0.0)


def test_crps_known_values() -> None:
    q = {f"{t:g}": 0.0 for t in baselines.LEVELS}  # point forecast at 0 -> CRPS = |y|
    assert scoring.crps_from_quantiles(1.0, q) == pytest.approx(1.0)
    # median-only forecast: 2 * 0.5 * |y - m|
    assert scoring.crps_from_quantiles(3.0, {"0.5": 1.0}) == pytest.approx(2.0)
    # asymmetric spread: tau=.25 at 0, tau=.75 at 2, y=1 -> 2*mean(.25*1, .25*1)=0.5
    assert scoring.crps_from_quantiles(1.0, {"0.25": 0.0, "0.75": 2.0}) == pytest.approx(0.5)


def test_brier_known_values() -> None:
    assert scoring.brier(0.3, True) == pytest.approx(0.49)
    assert scoring.brier(0.3, False) == pytest.approx(0.09)
    assert scoring.brier(1.0, True) == 0.0 and scoring.brier(0.0, True) == 1.0


def test_pending_without_observation(tmp_path) -> None:
    flow = make_flow(end="2021-03-10")
    reg = emit_many(tmp_path, [date(2021, 3, 10)], flow)
    s = scoring.score(reg.read(), obs_of(flow))
    assert len(s) == 40 and (s["status"] == "pending").all()
    assert s["crps"].isna().all() and s["brier"].isna().all()
    full = make_flow(end="2021-03-13")  # leads 1-3 now observed
    s = scoring.score(reg.read(), obs_of(full))
    scored = s[s["status"] == "scored"]
    assert set(scored["lead"]) == {1, 2, 3} and len(scored) == 3 * 4
    assert (s[s["lead"] > 3]["status"] == "pending").all()
    assert scored[scored["variable"] == "caudal_diario"]["crps"].notna().all()
    assert scored[scored["variable"] == "p_caudal_alto"]["brier"].between(0, 1).all()


def test_score_uses_only_registry(tmp_path) -> None:
    flow = make_flow(end="2021-03-20")
    reg = emit_many(tmp_path, [date(2021, 3, 10)], flow)
    assert reg.verify() is not None
    s = scoring.score_registry(reg, obs_of(flow))
    assert len(s) == len(reg.read())
    lines = reg.path.read_text().splitlines()
    reg.path.write_text("\n".join(lines[:5] + [lines[6], lines[5]] + lines[7:]) + "\n")
    with pytest.raises(RegistryTamperError):
        scoring.score_registry(reg, obs_of(flow))


@pytest.fixture(scope="module")
def scores(tmp_path_factory) -> pd.DataFrame:
    tmp = tmp_path_factory.mktemp("sk")
    days = [date(2021, 1, 1) + timedelta(days=9 * i) for i in range(10)]
    spikes = {
        d: 500.0 for d in (date(2021, 1, 20), date(2021, 1, 21), date(2021, 2, 5), date(2021, 3, 1))
    }
    flow = make_flow(spike=spikes)
    reg = emit_many(tmp, days, flow)
    return scoring.score(reg.read(), obs_of(flow))


def test_skill_zero_for_climatology(scores) -> None:
    t = scoring.skill_table(scores, n_boot=200, seed=1)
    c = t[t["model"] == "climatologia"]
    assert len(c) == 2 * 10 and (c["skill"] == 0).all()
    assert (c["skill_ci_low"].fillna(0) == 0).all() and (c["skill_ci_high"].fillna(0) == 0).all()


def test_skill_table_shape_and_flags(scores) -> None:
    t = scoring.skill_table(scores, n_boot=200, seed=1)
    p = t[(t["model"] == "persistencia") & (t["variable"] == "caudal_diario")]
    assert len(p) == 10 and (p["n"] > 0).all() and p["skill"].notna().all()
    assert (p["skill_ci_low"] <= p["skill"]).all() and (p["skill"] <= p["skill_ci_high"]).all()
    assert (t["status"] == "insuficiente").all()  # fewer than 10 events
    pb = t[(t["model"] == "persistencia") & (t["variable"] == "p_caudal_alto")]
    assert {"pod", "far", "n_events"} <= set(pb.columns)
    assert "insuficiente" in scoring.to_markdown(t, pending=3)


def test_pod_far_values() -> None:
    base = {
        "status": "scored", "model": "m", "variable": "p_caudal_alto", "station": "1", "lead": 1,
        "issue_date": date(2021, 1, 1),
    }  # fmt: skip
    rows = []
    for i, (p, ev) in enumerate([(0.9, 1), (0.8, 0), (0.2, 1), (0.1, 0)]):
        rows.append({**base, "valid_date": date(2021, 1, 1) + timedelta(days=10 * i), "p": p,
                     "event": float(ev), "brier": scoring.brier(p, bool(ev))})  # fmt: skip
    t = scoring.skill_table(pd.DataFrame(rows), n_boot=10, seed=0)
    assert t.loc[0, "pod"] == pytest.approx(0.5) and t.loc[0, "far"] == pytest.approx(0.5)
    assert t.loc[0, "n_events"] == 2


def test_independent_events_group_consecutive_days() -> None:
    days = pd.Series([date(2021, 2, 1), date(2021, 2, 2), date(2021, 2, 3), date(2021, 2, 9)])
    assert scoring._independent_events(days) == 2


def test_bootstrap_reproducible_with_seed(scores) -> None:
    a = scoring.skill_table(scores, n_boot=300, seed=42)
    b = scoring.skill_table(scores, n_boot=300, seed=42)
    c = scoring.skill_table(scores, n_boot=300, seed=43)
    pd.testing.assert_frame_equal(a, b)
    assert not a["skill_ci_low"].equals(c["skill_ci_low"])


# --- p_dia_riesgo (regional observed series) -----------------------------------------------------

RISK_TODAY = date(2026, 11, 22)
RISK_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
REGIONS = ("cordillera_norte", "cordillera_sur", "confluencia")


def _risk_toy_model() -> dict:
    coef = [1.0, 2.0, 0.0, 0.0]
    entry = {
        "scaler_mean": [0.5, 0.1, 0.0, 0.0], "scaler_scale": [1.0] * 4, "coef": coef,
        "intercept": -2.0, "boot_coef": [coef] * 3, "boot_intercept": [-2.0] * 3,
        "threshold_mm": 10.0, "clim_rates": [0.1] * 12, "clim_n": [300] * 12, "prob_cap": None,
    }  # fmt: skip
    return {"regions": {r: {str(lead): entry for lead in range(1, 11)} for r in REGIONS}}


def _risk_registry(tmp_path):
    from clima_nqn.forecast import riskday_model as rm

    rows = [
        {"init_date": RISK_TODAY, "lead": lead, "valid_date": RISK_TODAY + timedelta(days=lead - 1),
         "member": m, "region": r, "tp_mm": 4.0 + lead, "available_on": datetime(2026, 11, 22, 9)}
        for r in REGIONS for lead in range(1, 11) for m in ("c00", "p01", "p02")
    ]  # fmt: skip
    snap = tmp_path / "2026-11-22.parquet"
    pd.DataFrame(rows).to_parquet(snap)
    reg = PredictionRegistry(tmp_path / "risk.jsonl", clock=lambda: RISK_NOW)
    rm.emit(reg, _risk_toy_model(), "ab" * 32, snap, RISK_TODAY)
    return reg


def test_score_risk_day_brier_against_regional_series(tmp_path) -> None:
    reg = _risk_registry(tmp_path)
    # observed regional rain: lead 1 (today) >= threshold (event), lead 2 below, rest unobserved
    obs = pd.Series({pd.Timestamp("2026-11-22"): 10.0, pd.Timestamp("2026-11-23"): 9.9})
    recs = [r for r in reg.read() if r.region == "confluencia"]
    s = scoring.score(recs, obs)
    done = s[s["status"] == "scored"]
    assert len(done) == 2 * 2 and set(done["lead"]) == {1, 2}  # lead = GEFS lead, 2 models
    assert len(s) == 20 and (s[s["status"] == "pending"]["brier"].isna()).all()
    c = done[done["model"] == "climatologia"].set_index("lead")
    assert c.loc[1, "event"] == 1.0 and c.loc[1, "brier"] == pytest.approx((0.1 - 1) ** 2)
    assert c.loc[2, "event"] == 0.0 and c.loc[2, "brier"] == pytest.approx(0.1**2)
    lg = done[done["model"] == "logistica"].set_index("lead")
    rec = {(r.model_name, r.details["gefs_lead"]): r for r in recs}
    assert lg.loc[1, "brier"] == pytest.approx((rec["logistica", 1].value - 1) ** 2)
    assert lg.loc[2, "brier"] == pytest.approx(rec["logistica", 2].value ** 2)
    assert (done["threshold"] == 10.0).all()


def test_read_regional_observations_newest_snapshot_wins(tmp_path) -> None:
    d = tmp_path / "era5t"
    d.mkdir()
    day = pd.Timestamp("2026-11-20")
    old = pd.DataFrame({"date": [day, day], "region": ["confluencia", "cordillera_sur"],
                        "tp_mm": [1.0, 2.0], "available_on": pd.Timestamp("2026-11-27")})  # fmt: skip
    new = pd.DataFrame({"date": [day], "region": ["confluencia"], "tp_mm": [5.0],
                        "available_on": pd.Timestamp("2026-11-28")})  # fmt: skip
    old.to_parquet(d / "2026-11-27.parquet")
    new.to_parquet(d / "2026-11-28.parquet")
    obs = scoring.read_regional_observations(d)
    assert obs["confluencia"][day] == 5.0 and obs["cordillera_sur"][day] == 2.0


def test_skill_table_for_risk_day_and_flow_cli(tmp_path) -> None:
    from typer.testing import CliRunner

    from clima_nqn.forecast.cli import forecast_app

    reg = _risk_registry(tmp_path)
    era5t = tmp_path / "era5t"
    era5t.mkdir()
    days = pd.date_range("2026-11-22", periods=10)
    rows = [
        {"date": d, "region": r, "tp_mm": 12.0 if i in (0, 1) else 1.0,
         "available_on": pd.Timestamp("2026-12-05")}
        for r in REGIONS for i, d in enumerate(days)
    ]  # fmt: skip
    pd.DataFrame(rows).to_parquet(era5t / "2026-12-05.parquet")
    res = CliRunner().invoke(
        forecast_app,
        ["score", "--registry", str(reg.path), "--era5t-regions", str(era5t),
         "--out", str(tmp_path / "out"), "--n-boot", "20"],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    payload = json.loads((tmp_path / "out.json").read_text())
    table = pd.DataFrame(payload["table"])
    assert payload["pending"] == 0 and set(table["variable"]) == {"p_dia_riesgo"}
    assert len(table) == 2 * 3 * 10 and set(table["station"]) == set(REGIONS)
    lg = table[(table["model"] == "logistica") & (table["station"] == "confluencia")]
    assert lg["pod"].notna().sum() >= 1 and (lg["n"] == 1).all()
    clim = table[table["model"] == "climatologia"]
    assert (clim["skill"] == 0).all()


def _toy_scores(rows) -> pd.DataFrame:
    base = {"model": "m", "variable": "p_dia_riesgo", "lead": 1, "status": "scored", "p": 0.5}
    out = []
    for region, day, event, model in rows:
        d = date.fromisoformat(day)
        out.append(
            {**base, "station": region, "valid_date": d, "issue_date": d, "event": float(event),
             "brier": (0.5 - event) ** 2 if model == "m" else (0.1 - event) ** 2, "model": model}
        )  # fmt: skip
    return pd.DataFrame(out)


def test_pooled_events_not_sum_of_regions() -> None:
    # same system hits two regions on consecutive days -> 1 pooled event (per-region sum would be 2);
    # a later separate system -> 2; October event is outside any season but counts overall
    sc = _toy_scores(
        [("a", "2027-06-01", 1, "m"), ("a", "2027-06-02", 1, "m"), ("b", "2027-06-02", 1, "m"),
         ("b", "2027-06-03", 1, "m"), ("a", "2027-07-10", 1, "m"), ("a", "2027-10-05", 1, "m")]
    )  # fmt: skip
    ev = scoring.pooled_events(sc)["p_dia_riesgo"]["1"]
    assert ev == {"overall": 3, "2027": 2}


def test_season_table_excludes_off_season_and_flags_complete() -> None:
    rows = []
    for i in range(1, 31):  # June days, 10 separated events
        rows.append(("a", f"2027-06-{i:02d}", int(i % 3 == 0), "m"))
        rows.append(("a", f"2027-06-{i:02d}", int(i % 3 == 0), "climatologia"))
    rows.append(("a", "2027-11-01", 1, "m"))  # outside May-Sept: excluded
    rows.append(("a", "2027-11-01", 1, "climatologia"))
    t, pooled = scoring.season_table(_toy_scores(rows), today=date(2027, 10, 1), n_boot=50)
    assert set(t["season"]) == {2027} and t["complete"].all()
    m = t[t["model"] == "m"].iloc[0]
    assert m["n"] == 30 and m["n_events"] == 10 and m["n_events_pooled"] == 10
    assert pooled["p_dia_riesgo"]["1"]["overall"] == 11
    early, _ = scoring.season_table(_toy_scores(rows), today=date(2027, 9, 30), n_boot=50)
    assert not early["complete"].any()  # season end must be < today

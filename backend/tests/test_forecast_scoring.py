"""F6.5 prospective verification: scores, skill table, bootstrap."""

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

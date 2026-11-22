"""F6.4 baseline emission: climatology and persistence."""

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from clima_nqn.forecast import baselines
from clima_nqn.forecast.registry import DuplicatePredictionError, InputSource, PredictionRegistry

ISSUE = datetime(2021, 3, 10, 12, 0, tzinfo=UTC)
TRAIN = "2015-01-01/2020-12-31"
INPUTS = [InputSource(name="SNIH QMD", latency_hours=72.0)]


def sine_flow(start="2015-01-01", end="2021-03-07") -> pd.DataFrame:
    dates = pd.date_range(start, end, freq="D")
    doy = baselines.day_of_year(dates)
    q = 100 + 50 * np.sin(2 * np.pi * doy / 365)
    return pd.DataFrame({"date": dates, "q_m3s": q})


def make_registry(tmp_path) -> PredictionRegistry:
    return PredictionRegistry(tmp_path / "reg.jsonl", clock=lambda: ISSUE)


def test_climatology_quantiles_on_seasonal_sine() -> None:
    clim = baselines.fit_climatology(sine_flow(), TRAIN)
    for day in (date(2021, 1, 15), date(2021, 4, 20), date(2021, 9, 1)):
        q, _, n = clim.at(day)
        doy = int(baselines.day_of_year(pd.DatetimeIndex([day]))[0])
        truth = 100 + 50 * np.sin(2 * np.pi * doy / 365)
        assert q[2] == pytest.approx(truth, abs=1.0)
        assert np.all(np.diff(q) >= 0) and q[0] < q[2] < q[-1]
        assert n in (90, 91, 92)  # 15-day window x 6 years (+ leap days)
    assert clim.threshold == pytest.approx(np.quantile(sine_flow()[:2192]["q_m3s"], 0.95))


def test_feb29_folded() -> None:
    idx = pd.DatetimeIndex(["2020-02-28", "2020-02-29", "2020-03-01", "2021-03-01"])
    assert list(baselines.day_of_year(idx)) == [59, 59, 60, 60]


def test_no_training_row_after_period_end() -> None:
    flow = sine_flow()
    poisoned = flow.copy()
    poisoned.loc[poisoned["date"] > "2020-12-31", "q_m3s"] = 1e6
    a, b = baselines.fit_climatology(flow, TRAIN), baselines.fit_climatology(poisoned, TRAIN)
    assert a.threshold == b.threshold and a.n_train == b.n_train == 2192
    assert np.array_equal(a.quantiles, b.quantiles, equal_nan=True)
    pa, pb = baselines.fit_persistence(flow, TRAIN), baselines.fit_persistence(poisoned, TRAIN)
    assert pa.threshold == pb.threshold
    assert np.array_equal(pa.ratios(3)[1], pb.ratios(3)[1])
    assert pa.series.index.max() == pd.Timestamp("2020-12-31")


def test_persistence_uses_last_obs_and_horizon_includes_lag(tmp_path) -> None:
    recs = baselines.emit(make_registry(tmp_path), "12004", sine_flow(), ISSUE, "v1", TRAIN, INPUTS)
    obs_q = float(sine_flow().iloc[-1]["q_m3s"])
    p1 = next(
        r
        for r in recs
        if r.model_name == "persistencia" and r.variable == "caudal_diario" and r.lead_days == 1
    )
    assert p1.details["lag_days"] == 3 and p1.details["effective_horizon_days"] == 4
    assert p1.details["last_obs_date"] == "2021-03-07"
    assert p1.value == pytest.approx(obs_q)  # median = last observed value
    p10 = next(
        r
        for r in recs
        if r.model_name == "persistencia" and r.variable == "caudal_diario" and r.lead_days == 10
    )
    assert p10.details["effective_horizon_days"] == 13
    assert (p10.interval_high - p10.interval_low) > (p1.interval_high - p1.interval_low) - 1e-9


def test_emit_appends_valid_records(tmp_path) -> None:
    reg = make_registry(tmp_path)
    recs = baselines.emit(reg, "12004", sine_flow(), ISSUE.date(), "v1", TRAIN, INPUTS)
    assert len(recs) == 10 * 2 * 2
    assert reg.verify() == recs[-1].record_hash
    assert len(reg.read()) == 40
    keys = {(r.model_name, r.variable, r.lead_days) for r in recs}
    assert len(keys) == 40
    for r in recs:
        assert r.region == "12004" and r.training_period == TRAIN
        assert r.inputs[0].latency_hours == 72.0
        assert r.model_version == f"{r.model_name}-v1"
        if r.variable == "caudal_diario":
            assert r.kind == "value" and set(r.details["quantiles"]) == {
                "0.05",
                "0.25",
                "0.5",
                "0.75",
                "0.95",
            }
            assert r.interval_low <= r.value <= r.interval_high
        else:
            assert r.kind == "probability" and 0 <= r.details["clim_prob"] <= 1
            assert r.interval_low <= r.value <= r.interval_high
        assert r.details["threshold_m3s"] > 0
    with pytest.raises(DuplicatePredictionError):  # re-emitting the same day is a duplicate
        baselines.emit(reg, "12004", sine_flow(), ISSUE, "v1", TRAIN, INPUTS)


def test_train_period_after_issue_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        baselines.emit(
            make_registry(tmp_path), "1", sine_flow(), ISSUE, "v1", "2015-01-01/2021-06-01", INPUTS
        )

"""F5.8 evidence gate: event pooling, contiguity, Markov persistence without leakage, probability cap, CSV loader."""

import numpy as np
import pandas as pd

from clima_nqn.stages.hindcast import gate
from clima_nqn.stages.hindcast import riskday as rd

# --- event pooling ------------------------------------------------------------------------------


def test_one_system_in_two_regions_is_one_event():
    d = pd.date_range("2015-06-01", periods=12)
    a = np.zeros(12, bool)
    b = np.zeros(12, bool)
    a[[2, 3]] = True
    b[[3, 4]] = True  # same system seen in the second region one day later
    ev = gate.pooled_events(
        d, {"cordillera_norte": a, "cordillera_sur": b, "confluencia": a & False}
    )
    assert ev["pooled"] == 1
    assert ev["cordillera_norte"] == 1 and ev["cordillera_sur"] == 1 and ev["confluencia"] == 0
    # a separate system later in region b only: 2 pooled events, never a sum of regional counts
    b[9] = True
    ev = gate.pooled_events(
        d, {"cordillera_norte": a, "cordillera_sur": b, "confluencia": a & False}
    )
    assert ev["pooled"] == 2
    assert ev["cordillera_norte"] + ev["cordillera_sur"] > ev["pooled"]


def test_events_per_season_counts_may_sep_by_first_day():
    d = pd.date_range("2018-01-01", "2019-12-31")
    risk = np.zeros(len(d), bool)
    for day in ("2018-06-10", "2018-06-11", "2018-07-01", "2019-01-05", "2019-09-30", "2019-10-01"):
        risk[d.get_loc(pd.Timestamp(day))] = True
    out = gate.events_per_season(d, {"confluencia": risk})
    # events: Jun 10-11 (in), Jul 1 (in), Jan 5 (out), Sep 30-Oct 1 starts Sep 30 (in)
    assert out["pooled"]["n_events"] == 3
    assert out["n_seasons"] == 2
    assert out["pooled"]["per_season"] == 1.5


# --- contiguity / verdict -----------------------------------------------------------------------


def _ci(lo):
    return {"value": lo + 0.1, "lo": lo, "hi": lo + 0.2}


def test_contiguity_cuts_after_first_failure():
    raw = {lead: True for lead in range(1, 11)}
    raw[4] = False  # lead 4 fails; 5..10 would pass on their own
    out = gate.contiguous(raw)
    assert [out[k] for k in range(1, 11)] == [True, True, True] + [False] * 7
    assert gate.status(out[3]) == gate.STATE_PASS
    assert gate.status(out[7]) == gate.STATE_EXP


def test_lead_passes_needs_both_cis_and_enough_pooled_events():
    assert gate.lead_passes(_ci(0.05), _ci(0.01), 20)
    assert not gate.lead_passes(_ci(0.05), _ci(-0.01), 50)  # fails vs persistence
    assert not gate.lead_passes(_ci(-0.05), _ci(0.3), 50)  # fails vs climatology
    assert not gate.lead_passes(_ci(0.05), _ci(0.01), 19)  # too few pooled events
    assert not gate.lead_passes(_ci(float("nan")), _ci(0.01), 50)


# --- Markov persistence -------------------------------------------------------------------------


def _risk_series(seed=0, end="2019-12-31"):
    idx = pd.date_range("2000-01-01", end)
    rng = np.random.default_rng(seed)
    return pd.Series((rng.random(len(idx)) < 0.1).astype(float), index=idx)


def test_markov_table_values_on_handmade_series():
    idx = pd.date_range("2000-01-01", "2000-01-10")
    s = pd.Series([1, 1, 0, 0, 1, 0, 0, 0, 1, 1], index=idx, dtype=float)
    t = gate.markov_table(s, lead=1, fit_end="2000-01-10")
    # pairs (D -> V) in January: 1->1, 1->0, 0->0, 0->1, 1->0, 0->0, 0->0, 0->1, 1->1
    assert t[0, 1] == 2 / 4  # from risk: 1->1, 1->0, 1->0, 1->1
    assert t[0, 0] == 2 / 5
    assert np.isclose(t[5, 1], t[0, 1])  # empty month falls back to the state's overall rate


def test_markov_uses_no_data_after_2014():
    s = _risk_series()
    t1 = gate.markov_table(s, lead=3)
    s2 = s.copy()
    rng = np.random.default_rng(1)
    after = s2.index > pd.Timestamp("2014-12-31")
    s2[after] = (rng.random(after.sum()) < 0.9).astype(float)  # wildly different future
    t2 = gate.markov_table(s2, lead=3)
    np.testing.assert_array_equal(t1, t2)
    # whereas changing a fit-period day does move it
    s3 = s.copy()
    s3.loc["2005-03-01":"2005-03-20"] = 1.0
    assert not np.array_equal(gate.markov_table(s3, lead=3), t1)


def test_markov_predict_uses_issue_day_state_and_binary_is_raw():
    s = _risk_series()
    lead = 2
    t = gate.markov_table(s, lead)
    v_dates = pd.to_datetime(["2016-03-10", "2016-07-21"])
    p = gate.markov_predict(t, s, lead, v_dates)
    for pi, vd in zip(p, v_dates):
        state = int(s.loc[vd - pd.Timedelta(days=lead)])
        assert pi == t[vd.month - 1, state]
    b = gate.binary_persistence(s, lead, v_dates)
    np.testing.assert_array_equal(b, [s.loc[x - pd.Timedelta(days=lead)] for x in v_dates])


# --- reliability cap, POD / FAR -----------------------------------------------------------------


def test_probability_cap_is_upper_edge_of_highest_populated_bin():
    rel = [
        {"bin": b, "mean_p": b / 10, "obs_freq": b / 10, "n": n}
        for b, n in enumerate([500, 200, 90, 60, 40, 30, 25, 19, 5, 0])
    ]
    assert (
        gate.probability_cap(rel) == 0.7
    )  # bin 6 (0.6-0.7) is the highest with >= 20 days; bin 7 has 19
    rel[9]["n"] = 20
    assert gate.probability_cap(rel) == 1.0
    assert gate.probability_cap([{"bin": 0, "mean_p": 0.0, "obs_freq": 0.0, "n": 3}]) is None


def test_cap_from_real_reliability_bins():
    p = np.concatenate([np.full(100, 0.05), np.full(25, 0.55), np.full(3, 0.95)])
    y = np.zeros(len(p))
    assert gate.probability_cap(rd.reliability(p, y)) == 0.6


def _rel(ns):
    return [{"bin": b, "mean_p": b / 10, "obs_freq": b / 10, "n": n} for b, n in enumerate(ns)]


def test_pooled_cap_uses_neighbour_leads_and_pools_two_at_edges():
    # lead 1: top populated bin 3 alone; with lead 2 pooled (edge: only L=1,2) it reaches 20 days
    rel = {
        1: _rel([100, 50, 20, 12, 0, 0, 0, 0, 0, 0]),
        2: _rel([100, 50, 20, 9, 0, 0, 0, 0, 0, 0]),
        3: _rel([100, 50, 20, 0, 0, 0, 0, 0, 0, 0]),
    }
    out = gate.pooled_caps(rel)
    assert out[1]["cap_pooled"] == 0.4  # 12 + 9 = 21 >= 20 (leads 1, 2 only)
    assert out[2]["cap_pooled"] == 0.4  # 12 + 9 + 0 pooled over 1..3
    assert out[3]["cap_pooled"] == 0.3  # leads 2, 3 only: bin 3 has 9
    # own-lead cap kept for comparison
    assert out[1]["cap_lead"] == 0.3 and out[2]["cap_lead"] == 0.3


def test_pooled_cap_edge_lead_10_pools_two_leads():
    rel = {9: _rel([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), 10: _rel([50, 0, 0, 0, 0, 0, 0, 0, 0, 12])}
    rel[9][9]["n"] = 8
    out = gate.pooled_caps(rel)
    assert out[10]["cap_pooled"] == 1.0  # 12 + 8 = 20 in the top bin
    assert out[10]["cap_lead"] == 0.1


def test_pooled_cap_in_force_is_non_increasing_in_lead():
    rel = {
        1: _rel([100, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
        2: _rel([100, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
        3: _rel([100, 0, 0, 0, 0, 0, 0, 0, 30, 0]),  # pooling alone would raise the cap at L=2..4
        4: _rel([100, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    }
    rel[1][5]["n"] = 25  # L=1 cap 0.6 only
    out = gate.pooled_caps(rel)
    caps = [out[L]["cap"] for L in sorted(out)]
    assert all(a >= b for a, b in zip(caps, caps[1:], strict=False))
    assert out[3]["cap_pooled"] == 0.9 and out[3]["cap"] <= out[2]["cap"]


def test_pooled_cap_ignores_bins_below_20_days():
    out = gate.pooled_caps(
        {
            1: _rel([100, 10, 5, 4, 0, 0, 0, 0, 0, 0]),
            2: _rel([100, 9, 5, 0, 0, 0, 0, 0, 0, 0]),
        }
    )
    assert out[1]["cap_pooled"] == 0.1  # bin 1 has 10 + 9 = 19 pooled days: ignored; bin 0 only
    assert out[1]["cap"] == 0.1


def test_pod_far():
    p = np.array([0.9, 0.6, 0.4, 0.7, 0.1])
    y = np.array([1, 0, 1, 1, 0])
    r = gate.pod_far(p, y, 0.5)
    assert (r["hits"], r["false_alarms"], r["n_yes"]) == (2, 1, 3)
    assert np.isclose(r["pod"], 2 / 3) and np.isclose(r["far"], 1 / 3)


# --- CSV loader ---------------------------------------------------------------------------------


def test_obs_csv_loader_gives_the_same_regional_series(tmp_path):
    idx = pd.date_range("2000-01-01", periods=6, name="date")
    rng = np.random.default_rng(0)
    cols = {}
    for r in rd.REGIONS:
        cols[f"{r}_tp_mm"] = np.round(rng.gamma(1, 3, 6), 3)
        cols[f"{r}_cp_mm"] = np.round(rng.gamma(1, 1, 6), 3)
    df = pd.DataFrame(cols, index=idx)
    path = tmp_path / "obs.csv"
    df.to_csv(path)
    tp, cp = rd.obs_from_csv(path)
    for r in rd.REGIONS:
        np.testing.assert_allclose(tp[r].to_numpy(), df[f"{r}_tp_mm"].to_numpy())
        np.testing.assert_allclose(cp[r].to_numpy(), df[f"{r}_cp_mm"].to_numpy())
    assert list(tp.index) == list(idx)

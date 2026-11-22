"""F5.7: ONI lag / phase mappings, skill by ENSO phase (Part A) and ENSO as classifier input (Part B)."""

import numpy as np
import pandas as pd
import pytest

from clima_nqn.io import enso as enso_io
from clima_nqn.stages.hindcast import enso_skill as es
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import riskday as rd
from clima_nqn.stages.hindcast import store
from clima_nqn.stages.hindcast import verify as v

SPEC = fc.MODELS["gefs-reforecast"]
SEASONS = list(enso_io.SEASON_CENTER_MONTH)


def _oni_text(first_year: int, last_year: int, value) -> str:
    """CPC-style ascii; ``value(center_year, center_month)`` is the ANOM of each season."""
    lines = ["SEAS  YR  TOTAL  ANOM"]
    for y in range(first_year, last_year + 1):
        for s in SEASONS:
            m = enso_io.SEASON_CENTER_MONTH[s]
            lines.append(f"{s} {y} 27.00 {value(y, m):.2f}")
    return "\n".join(lines) + "\n"


def _id_enso() -> pd.DataFrame:
    """ONI whose value identifies the center month: year + month / 100."""
    return enso_io.parse_oni(_oni_text(1999, 2012, lambda y, m: y + m / 100))


# --- mappings -------------------------------------------------------------------------------------


def test_lagged_oni_is_season_centered_two_months_before_init():
    enso = _id_enso()
    f = lambda d, lead=1: float(es.oni_available([pd.Timestamp(d)], lead, enso)[0])
    # init in July -> season centered on May = AMJ (ends in June, the latest fully ended before July)
    assert f("2010-07-05") == pytest.approx(2010.05)
    assert enso_io.SEASON_CENTER_MONTH["AMJ"] == 5
    # month boundaries: first and last day of the month map to the same season
    assert f("2010-07-01") == pytest.approx(2010.05)
    assert f("2010-07-31") == pytest.approx(2010.05)
    assert f("2010-06-30") == pytest.approx(2010.04)  # MAM
    assert f("2010-08-01") == pytest.approx(2010.06)  # MJJ
    # January -> centered on November of the previous year = OND (ends in December)
    assert f("2010-01-15") == pytest.approx(2009.11)
    assert enso_io.SEASON_CENTER_MONTH["OND"] == 11
    # February -> centered on December of the previous year = NDJ (ends in January)
    assert f("2010-02-10") == pytest.approx(2009.12)
    assert enso_io.SEASON_CENTER_MONTH["NDJ"] == 12
    # the init date is valid date - (lead - 1): valid 2010-08-01 at lead 2 was initialised on July 31
    assert f("2010-08-01", lead=2) == pytest.approx(2010.05)
    assert f("2010-08-01", lead=1) == pytest.approx(2010.06)


def test_lagged_oni_matches_named_seasons_from_ascii():
    text = _oni_text(2009, 2010, lambda y, m: 0.0)
    # give AMJ 2010 and OND 2009 recognisable values
    text = text.replace("AMJ 2010 27.00 0.00", "AMJ 2010 27.00 1.70").replace(
        "OND 2009 27.00 0.00", "OND 2009 27.00 -1.30"
    )
    enso = enso_io.parse_oni(text)
    assert es.oni_available([pd.Timestamp("2010-07-05")], 1, enso)[0] == pytest.approx(1.7)
    assert es.oni_available([pd.Timestamp("2010-01-20")], 1, enso)[0] == pytest.approx(-1.3)


def test_missing_oni_is_nan_and_unknown_phase():
    enso = _id_enso()
    assert np.isnan(es.oni_available([pd.Timestamp("1999-01-10")], 1, enso)[0])  # needs Nov 1998
    assert es.phase_by_valid_date([pd.Timestamp("2030-01-01")], enso)[0] == "sin dato"


def test_valid_date_phase_uses_season_centered_on_valid_month():
    vals = {(2010, 3): 0.8, (2010, 4): -0.6, (2010, 5): 0.5, (2010, 6): -0.5, (2010, 7): 0.49}
    enso = enso_io.parse_oni(_oni_text(2010, 2010, lambda y, m: vals.get((y, m), 0.0)))
    ph = es.phase_by_valid_date(
        pd.to_datetime(
            ["2010-03-31", "2010-04-01", "2010-05-15", "2010-06-30", "2010-07-02", "2010-08-02"]
        ),
        enso,
    )
    assert list(ph) == ["nino", "nina", "nino", "nina", "neutral", "neutral"]  # +-0.5 inclusive


# --- Part A ---------------------------------------------------------------------------------------


def _phase_enso() -> pd.DataFrame:
    def val(y, m):
        return {2001: 1.0, 2002: -1.0}.get(y, 0.0)

    return enso_io.parse_oni(_oni_text(1999, 2005, val))


def _cases_ds(good: dict[str, bool], leads=(1, 2, 3), seed=0):
    """Cases every 5 days in 2001 (Niño), 2002 (Niña), 2003 (neutral); events alternate with controls.
    ``good[phase]``: forecast = observation (perfect) vs. unrelated random."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2001-01-02", "2003-12-30", freq="5D")
    n = len(dates)
    kind = np.where(np.arange(n) % 2 == 0, "event", "control")
    cases = pd.DataFrame(
        {
            "case_id": [f"c{i:03d}" for i in range(n)],
            "kind": kind,
            "event_id": [None] * n,
            "valid_date": dates,
        }
    )
    ds = store.empty_store(SPEC, cases, leads)
    obs = (
        np.round(np.where(kind == "event", rng.gamma(2.0, 4.0, n) + 1.0, 0.5) * 4) / 4
    )  # float32-exact
    phase = es.phase_by_valid_date(dates, _phase_enso())
    for i in range(n):
        for li in range(len(leads)):
            for mi in range(len(SPEC.members)):
                perfect = good[phase[i]]
                ds["precip_mm"].values[i, li, mi] = obs[i] if perfect else rng.gamma(2.0, 4.0)
    ds["status"].values[:] = fc.STATUS_OK
    ds.attrs["model"] = "gefs-reforecast"
    return ds, pd.Series(obs, index=dates), phase, kind


def test_part_a_subset_counts_and_matches_verify_model():
    ds, obs, phase, kind = _cases_ds({"nino": True, "nina": True, "neutral": True})
    a = es.part_a(ds, obs, _phase_enso(), n_boot=20, seed=0)
    for ph in es.PHASES:
        assert a["phase_counts"][ph]["n_event"] == int(((phase == ph) & (kind == "event")).sum())
        assert a["phase_counts"][ph]["n_control"] == int(
            ((phase == ph) & (kind == "control")).sum()
        )
    assert sum(c["n_event"] for c in a["phase_counts"].values()) == int((kind == "event").sum())
    assert len(a["rows"]) == 3 * 3  # phases x leads
    row = next(r for r in a["rows"] if r["phase"] == "nina" and r["lead"] == 2)
    sub = ds.isel(case=np.flatnonzero(phase == "nina"))
    df = v.verify_model(sub, obs, (5.0,), 5.0, n_boot=20, seed=0, model="m")
    want = v._get(df, "m", 2, "event", "crpss")
    assert row["crpss_event"]["value"] == pytest.approx(want[0])
    assert row["crpss_event"]["lo"] == pytest.approx(want[1])
    assert row["n_event"] == a["phase_counts"]["nina"]["n_event"]
    assert row["n_control"] == a["phase_counts"]["nina"]["n_control"]
    ets = v._get(df, "m", 2, "all", "ets", 5.0)
    assert row["ets"]["value"] == pytest.approx(ets[0])


def test_part_a_difference_sign_and_signal_rule():
    enso = _phase_enso()
    ds, obs, _, _ = _cases_ds({"nino": True, "nina": False, "neutral": True})
    a = es.part_a(ds, obs, enso, n_boot=100, seed=0)
    for d in a["diff"]:
        assert d["crpss_nino"] == pytest.approx(1.0)
        assert d["diff"] > 0.5 and d["lo"] > 0  # El Niño better than La Niña
        assert d["excludes_zero"] and not d["sin_verificar"]
    assert a["longest_run"] == 3 and a["signal"]
    # reversed roles flip the sign
    ds, obs, _, _ = _cases_ds({"nino": False, "nina": True, "neutral": True})
    b = es.part_a(ds, obs, enso, n_boot=100, seed=0)
    assert all(d["diff"] < -0.5 and d["hi"] < 0 for d in b["diff"]) and b["signal"]
    # same skill in both phases: no signal
    ds, obs, _, _ = _cases_ds({"nino": True, "nina": True, "neutral": True})
    c = es.part_a(ds, obs, enso, n_boot=100, seed=0)
    assert all(d["diff"] == pytest.approx(0, abs=1e-6) for d in c["diff"])
    assert not any(d["excludes_zero"] for d in c["diff"]) and not c["signal"]


def test_part_a_small_groups_are_sin_verificar():
    enso = _phase_enso()
    ds, obs, _, _ = _cases_ds({"nino": True, "nina": False, "neutral": True})
    a = es.part_a(ds, obs, enso, n_boot=20, seed=0, min_events=1000)
    assert all(r["sin_verificar"] for r in a["rows"])
    assert all(d["sin_verificar"] and not d["excludes_zero"] for d in a["diff"])
    assert not a["signal"]


def test_longest_run_requires_contiguous_leads():
    assert es.longest_run([1, 2, 3, 4, 5], [True, True, False, True, True]) == 2
    assert es.longest_run([1, 2, 3, 4, 5], [True, True, True, False, False]) == 3
    assert es.longest_run([1, 3, 4], [True, True, True]) == 2  # lead 2 missing breaks the run
    assert es.longest_run([1, 2], [False, False]) == 0


def test_render_md_part_a_only():
    ds, obs, _, _ = _cases_ds({"nino": True, "nina": False, "neutral": True})
    a = es.part_a(ds, obs, _phase_enso(), n_boot=20, seed=0)
    md = es.render_md(
        a, None, {"n_boot": 20, "seed": 0, "oni_url": enso_io.ONI_URL, "oni_origin": "x"}
    )
    for h in (
        "## Veredicto",
        "## Fuente y alcance",
        "## Regla fijada antes de correr",
        "## Parte A",
        "## Parte B",
        "## Advertencias",
    ):
        assert h in md
    assert "<!-- veredicto: lo escribe Opus -->" in md
    assert "El Niño" in md and "La Niña" in md
    assert "retroactiv" in md and "SMN" in md and "Defensa Civil" in md
    assert "no corrida" in md.lower()


# --- Part B ---------------------------------------------------------------------------------------


def _enso_ctx(seed=0, informative=True):
    """Region rain depends on the lagged ONI (informative) while the forecast members are pure noise,
    so only the ENSO inputs can add skill."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2000-01-01", "2019-12-31")
    n = len(dates)

    # multi-year ENSO blocks
    def val(y, m):
        return [1.2, 0.0, -1.2, 0.0][(y // 2) % 4]

    enso = enso_io.parse_oni(_oni_text(1999, 2020, val))
    oni = rd.oni_available(dates, 1, enso)
    boost = np.where(oni >= 0.5, 6.0, 1.0) if informative else np.ones(n)
    tp = {r: rng.gamma(0.4, 3.0, n) * boost for r in rd.REGIONS}
    members = {r: rng.gamma(0.4, 3.0, (n, 1, 5)) for r in rd.REGIONS}
    tp_df = pd.DataFrame(tp, index=dates)
    cp_df = tp_df * rng.uniform(0, 1, tp_df.shape)
    ev = pd.DataFrame(
        {
            "event_id": range(3),
            "start": pd.to_datetime(["2005-02-01", "2010-02-01", "2016-02-01"]),
            "end": pd.to_datetime(["2005-02-01 18:00", "2010-02-01 18:00", "2016-02-01 18:00"]),
        }
    )
    return rd.build_context(dates, [1], members, tp_df, cp_df, ev), enso


def test_feature_frame_hook_off_unchanged_and_on_adds_three_columns():
    ctx, enso = _enso_ctx()
    thr = {r: 5.0 for r in rd.REGIONS}
    dates = ctx["dates"]
    off = rd.feature_frame(ctx["members"], "confluencia", 0, thr, dates)
    on = rd.feature_frame(ctx["members"], "confluencia", 0, thr, dates, enso=enso, lead=1)
    assert not set(rd.ENSO_COLS) & set(off.columns)
    pd.testing.assert_frame_equal(on[off.columns], off)
    assert list(on.columns[len(off.columns) :]) == list(rd.ENSO_COLS)
    oni = on["oni_avail"].to_numpy()
    assert (on["nino_avail"].to_numpy() == (oni >= 0.5)).all()
    assert (on["nina_avail"].to_numpy() == (oni <= -0.5)).all()
    # lagged: 2000-07-05 uses AMJ 2000 (centered May)
    got = on.loc["2000-07-05", "oni_avail"]
    assert got == pytest.approx(rd.oni_at([pd.Timestamp("2000-05-01")], enso)[0])
    with pytest.raises(ValueError):
        rd.feature_frame(ctx["members"], "confluencia", 0, thr, dates, enso=enso)


def test_feature_frame_uses_init_date_for_longer_leads():
    ctx, enso = _enso_ctx()
    thr = {r: 5.0 for r in rd.REGIONS}
    dates = pd.DatetimeIndex(["2005-08-01"])
    m = {r: a[:1] for r, a in ctx["members"].items()}
    f = rd.feature_frame(m, "confluencia", 0, thr, dates, enso=enso, lead=2)
    # valid Aug 1 at lead 2 -> init Jul 31 -> season centered on May
    assert f["oni_avail"].iloc[0] == pytest.approx(rd.oni_at([pd.Timestamp("2005-05-01")], enso)[0])


def test_hook_off_gives_identical_riskday_outputs():
    pytest.importorskip("sklearn")
    ctx, enso = _enso_ctx(informative=False)
    models = ("clim", "log", "lgbm") if rd.lightgbm_available() else ("clim", "log")
    base = rd._evaluate(ctx, 0.95, models, n_boot=10, seed=0, light=False)
    off = rd._evaluate(ctx, 0.95, models, n_boot=10, seed=0, light=False, enso=None)
    on = rd._evaluate(ctx, 0.95, models, n_boot=10, seed=0, light=False, enso=enso)
    assert rd._clean(base) == rd._clean(off)
    for r in rd.REGIONS:
        assert "enso" not in base["regions"][r]["1"]
        assert "enso" in on["regions"][r]["1"]
    # the "sin ENSO" outputs do not change when the hook is on
    strip = lambda res: {
        r: {k: x for k, x in row.items() if k != "enso"}
        for r, rows in res["regions"].items()
        for k, row in rows.items()
    }
    assert rd._clean(strip(base)) == rd._clean(strip(on))


def test_informative_oni_gives_positive_bss_con_vs_sin():
    pytest.importorskip("sklearn")
    ctx, enso = _enso_ctx(informative=True)
    b = es.part_b(ctx, enso, n_boot=30, seed=0)
    assert b["n_total"] == 3 and len(b["cells"]) == 3
    for c in b["cells"]:
        log = c["models"]["log"]["bss_con_vs_sin"]
        assert log["value"] > 0 and log["lo"] > 0
        assert c["models"]["log"]["brier_con"] < c["models"]["log"]["brier_sin"]
        assert set(c["by_phase"]) == set(es.PHASES)
        assert sum(p["n_days"] for p in c["by_phase"].values()) == c["n_days"]
        assert sum(p["n_risk_days"] for p in c["by_phase"].values()) == c["n_risk_days"]
    if rd.lightgbm_available():
        assert all(c["models"]["lgbm"]["bss_con_vs_sin"]["value"] > 0 for c in b["cells"])
        assert b["n_pass"] >= 1
    md = es.render_md(
        {
            "phase_counts": {p: {"n_event": 0, "n_control": 0} for p in es.PHASES},
            "rows": [],
            "diff": [],
            "longest_run": 0,
            "signal": False,
        },
        b,
        {"n_boot": 30, "seed": 0},
    )
    assert "BSS log. con vs sin" in md and "30 comparaciones" in md


def test_uninformative_oni_does_not_pass_rule():
    pytest.importorskip("sklearn")
    ctx, enso = _enso_ctx(informative=False)
    b = es.part_b(ctx, enso, n_boot=30, seed=0)
    assert b["n_total"] == 3
    for c in b["cells"]:
        assert abs(c["models"]["log"]["bss_con_vs_sin"]["value"]) < 0.1


def _entry(log_lo, lgbm_lo):
    mk = lambda lo: {"bss_con_vs_sin": {"value": 0.1, "lo": lo, "hi": 0.2}}
    return {"models": {"log": mk(log_lo), "lgbm": mk(lgbm_lo)}}


def test_enso_aporta_requires_both_models():
    assert es.enso_passes(_entry(0.01, 0.02))
    assert not es.enso_passes(_entry(0.01, -0.02))
    assert not es.enso_passes(_entry(-0.01, 0.02))
    assert not es.enso_passes(_entry(0.01, float("nan")))
    assert not es.enso_passes(
        {"models": {"log": _entry(0.01, 0.01)["models"]["log"]}}
    )  # no LightGBM
    assert not es.enso_passes(_entry(0.0, 0.5))  # lower bound must be strictly > 0

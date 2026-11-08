import json
import math

import numpy as np
import pandas as pd
import pytest

from clima_nqn.io import enso as io_enso
from clima_nqn.stages.ar import enso as ar_enso


def oni_table(values_by_month: dict[str, float]) -> pd.DataFrame:
    dates = pd.to_datetime([f"{k}-01" for k in values_by_month])
    return pd.DataFrame({"date": dates, "oni": list(values_by_month.values())})


def flat_oni(start: str, end: str, value: float) -> pd.DataFrame:
    months = pd.period_range(start, end, freq="M")
    return pd.DataFrame({"date": months.to_timestamp(), "oni": value})


# --- seasons -------------------------------------------------------------------------------


def test_december_belongs_to_following_year_djf():
    dates = pd.to_datetime(["1980-12-15", "1981-01-10", "1981-02-28", "1981-03-01", "1981-12-01"])
    names, years = ar_enso.season_year(dates)
    assert names.tolist() == ["DJF", "DJF", "DJF", "MAM", "DJF"]
    assert years.tolist() == [1981, 1981, 1981, 1981, 1982]


def make_events(rows):
    cols = ["start", "end", "ivt_max", "tp_sum_mm"]
    df = pd.DataFrame(rows, columns=cols)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    return df


def test_season_table_metrics_and_edges_dropped():
    days = pd.date_range("1980-01-01", "1982-12-31", freq="D")
    daily = pd.Series(1.0, index=days)  # 1 mm/day everywhere
    events = make_events(
        [
            ("1980-12-30 00:00", "1980-12-31 00:00", 400.0, 5.0),  # DJF 1981 (December rule)
            ("1981-01-10 00:00", "1981-01-12 00:00", 600.0, 10.0),  # DJF 1981
            ("1981-07-05 00:00", "1981-07-05 12:00", 300.0, 2.0),  # JJA 1981
        ]
    )
    table = ar_enso.season_table(events, daily, flat_oni("1979-01", "1983-12", 0.0))
    keys = set(zip(table["season"], table["year"], strict=True))
    assert ("DJF", 1980) not in keys  # lacks Dec 1979
    assert ("DJF", 1981) in keys and ("DJF", 1982) in keys and ("DJF", 1983) not in keys
    assert ("MAM", 1980) in keys and ("SON", 1982) in keys
    djf = table[(table["season"] == "DJF") & (table["year"] == 1981)].iloc[0]
    assert djf["n_events"] == 2
    assert djf["ivt_mean"] == pytest.approx(500.0)
    assert djf["ivt_max"] == pytest.approx(600.0)
    assert djf["ar_precip_mm"] == pytest.approx(15.0)
    assert djf["total_precip_mm"] == pytest.approx(31 + 31 + 28)  # Dec 1980, Jan, Feb 1981
    assert djf["ar_share"] == pytest.approx(15.0 / 90.0)
    assert djf["ar_days"] == 3  # Dec 30, Jan 10, Jan 11 (events end at 00:00, excluded)
    jja = table[(table["season"] == "JJA") & (table["year"] == 1981)].iloc[0]
    assert jja["n_events"] == 1 and jja["ar_days"] == 1
    empty = table[(table["season"] == "JJA") & (table["year"] == 1982)].iloc[0]
    assert empty["n_events"] == 0 and math.isnan(empty["ivt_mean"]) and empty["ar_share"] == 0.0


def test_season_table_drops_season_with_missing_days():
    days = pd.date_range("1990-01-01", "1990-12-31", freq="D").delete(100)  # a gap in April
    table = ar_enso.season_table(
        make_events([]), pd.Series(1.0, index=days), flat_oni("1989-01", "1991-01", 0.0)
    )
    assert "MAM" not in set(table["season"])
    assert {"JJA", "SON"} <= set(table["season"])


# --- ENSO classification -------------------------------------------------------------------


def test_seasonal_oni_uses_io_thresholds():
    assert io_enso.NINO_THRESHOLD == 0.5 and io_enso.NINA_THRESHOLD == -0.5
    # JJA 1990 months: Jun, Jul, Aug -> mean 0.5 exactly = Niño (inclusive)
    enso = oni_table({"1990-06": 0.4, "1990-07": 0.5, "1990-08": 0.6})
    mean, phase = ar_enso.seasonal_oni(enso, "JJA", 1990)
    assert mean == pytest.approx(0.5) and phase == "nino"
    enso = oni_table({"1990-06": -0.4, "1990-07": -0.5, "1990-08": -0.6})
    assert ar_enso.seasonal_oni(enso, "JJA", 1990)[1] == "nina"
    enso = oni_table({"1990-06": 0.2, "1990-07": -0.3, "1990-08": 0.1})
    assert ar_enso.seasonal_oni(enso, "JJA", 1990)[1] == "neutral"
    # phase agrees with the shared classifier for the same mean
    assert (
        ar_enso.seasonal_oni(enso, "JJA", 1990)[1]
        == io_enso.classify_phase(pd.Series([0.0])).iloc[0]
    )


def test_seasonal_oni_djf_uses_previous_december_and_missing_month():
    enso = oni_table({"1980-12": 1.0, "1981-01": 1.0, "1981-02": 1.0})
    assert ar_enso.seasonal_oni(enso, "DJF", 1981)[1] == "nino"
    mean, phase = ar_enso.seasonal_oni(enso, "DJF", 1982)
    assert math.isnan(mean) and phase is None


# --- permutation test ----------------------------------------------------------------------


def test_permutation_identical_groups_p_near_one():
    v = np.tile(np.arange(10.0), 2)
    lab = ["a"] * 10 + ["b"] * 10
    res = ar_enso.permutation_test(v, lab, "a", "b", n_perm=2000)
    assert res["diff"] == pytest.approx(0.0)
    assert res["p"] == pytest.approx(1.0)


def test_permutation_shifted_group_is_significant_and_p_never_zero():
    rng = np.random.default_rng(1)
    v = np.concatenate([rng.normal(0, 1, 30), rng.normal(5, 1, 30)])
    lab = ["a"] * 30 + ["b"] * 30
    res = ar_enso.permutation_test(v, lab, "a", "b", n_perm=2000)
    assert res["p"] < 0.01
    assert res["p"] >= 1 / 2001
    assert res["diff"] < 0
    # perfectly separated -> k = 0 permutations beat it except the observed one
    sep = ar_enso.permutation_test([0, 0, 0, 10, 10, 10], list("aaabbb"), "a", "b", n_perm=500)
    assert 0 < sep["p"] < 0.2  # 2 of the 20 splits are this extreme (about 0.1)


def test_permutation_deterministic_with_seed_and_counts():
    v = [1.0, 2.0, 3.0, 4.0, 9.0, 8.0, 7.0, 0.5, 5.0]
    lab = ["a", "a", "a", "a", "b", "b", "b", "c", "c"]
    r1 = ar_enso.permutation_test(v, lab, "a", "b", n_perm=500, seed=3)
    r2 = ar_enso.permutation_test(v, lab, "a", "b", n_perm=500, seed=3)
    assert r1 == r2
    assert (r1["n_a"], r1["n_b"]) == (4, 3)  # the "c" units are not counted
    nan_run = ar_enso.permutation_test([1, np.nan, 3, 8, 9], list("aaabb"), "a", "b", n_perm=200)
    assert (nan_run["n_a"], nan_run["n_b"]) == (2, 2)  # NaN dropped
    empty = ar_enso.permutation_test([1, 2], ["a", "a"], "a", "b", n_perm=10)
    assert math.isnan(empty["p"]) and empty["n_b"] == 0


def test_three_group_permutation():
    rng = np.random.default_rng(2)
    v = np.concatenate([rng.normal(0, 1, 15), rng.normal(0, 1, 15), rng.normal(6, 1, 15)])
    lab = ["nino"] * 15 + ["neutral"] * 15 + ["nina"] * 15
    res = ar_enso.permutation_test_groups(v, lab, n_perm=1000)
    assert res["p"] < 0.01 and res["n"] == {"nino": 15, "neutral": 15, "nina": 15}
    same_lab = ["nino"] * 9 + ["neutral"] * 9 + ["nina"] * 9
    same = ar_enso.permutation_test_groups(np.tile(np.arange(9.0), 3), same_lab, n_perm=500)
    assert same["p"] > 0.5
    assert ar_enso.permutation_test_groups(v, lab, n_perm=300, seed=5) == (
        ar_enso.permutation_test_groups(v, lab, n_perm=300, seed=5)
    )
    missing = ar_enso.permutation_test_groups([1.0, 2.0, 3.0, 4.0], list("aabb"), n_perm=50)
    assert math.isnan(missing["p"])


# --- multiplicity --------------------------------------------------------------------------


def test_bh_adjust_known_vector():
    p = [0.01, 0.04, 0.03, 0.005]
    # sorted 0.005,0.01,0.03,0.04 -> *4/rank: 0.02, 0.02, 0.04, 0.04
    assert ar_enso.bh_adjust(p) == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert ar_enso.bh_adjust([0.9, 0.95]) == pytest.approx([0.95, 0.95])
    out = ar_enso.bh_adjust([0.01, math.nan, 0.02])
    assert out[0] == pytest.approx(0.02) and math.isnan(out[1]) and out[2] == pytest.approx(0.02)


# --- results and report --------------------------------------------------------------------


def synthetic_table(shift: float) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    phases = ["nino"] * 8 + ["neutral"] * 12 + ["nina"] * 8
    for season in ar_enso.SEASONS:
        for i, ph in enumerate(phases):
            ev = rng.poisson(3 + (shift if ph == "nino" else 0))
            rows.append(
                {
                    "season": season, "year": 1980 + i, "n_events": ev, "ar_days": ev + 1,
                    "ivt_mean": 400.0 + rng.normal(0, 20), "ivt_max": 500.0,
                    "ar_precip_mm": 10.0, "total_precip_mm": 100.0,
                    "ar_share": 0.1 + rng.normal(0, 0.01), "oni_mean": 0.0, "phase": ph,
                }
            )  # fmt: skip
    return pd.DataFrame(rows)


def test_report_has_n_per_phase_and_no_label_when_not_significant(tmp_path):
    table = synthetic_table(0.0)
    res = ar_enso.compute_results(table, n_perm=500)
    assert len(res["rows"]) == 16
    meta = {"period": "1980-01-01/2025-12-31", "n_events": 123, "bard_threshold": 0.67,
            "polygon": [[-71.95, -36.0]], "table": table}  # fmt: skip
    path = ar_enso.write_report(res, tmp_path / "F1.8.md", meta)
    text = path.read_text(encoding="utf-8")
    assert "F1.8 — Ríos atmosféricos por fase ENSO (cordillera neuquina)" in text
    assert "| DJF | 8 | 12 | 8 | 28 |" in text
    assert "(n=8)" in text and "(n=12)" in text
    assert "ERA5" in text and "TECA BARD 6.0.0" in text and "NOAA CPC ONI" in text
    assert "sin verificar" in text and "Benjamini-Hochberg" in text
    row = next(r for r in res["rows"] if r["metric"] == "ar_share")
    assert row["p"] >= 0.05 and not row["sustained"]
    assert ar_enso.label_sustained(row["p"]) == "no"
    result_rows = [x for x in text.splitlines() if x.startswith("| ") and "(n=" in x]
    assert len(result_rows) == 16 and all(x.endswith("| no |") for x in result_rows)
    data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert len(data["results"]["rows"]) == 16 and len(data["season_years"]) == 112


def test_results_flag_large_difference_as_sustained(tmp_path):
    table = synthetic_table(30.0)  # Niño years with ~10x more events
    res = ar_enso.compute_results(table, n_perm=1000)
    ev = next(r for r in res["rows"] if r["season"] == "JJA" and r["metric"] == "n_events")
    assert ev["p"] < 0.05 and ev["sustained"] and ev["p_bh"] <= 1.0
    assert ev["diff_nino_nina"] > 0
    assert ev["groups"]["nino"]["n"] == 8 and ev["groups"]["nina"]["n"] == 8
    text = ar_enso.write_report(res, tmp_path / "F1.8.md", {}).read_text(encoding="utf-8")
    result_rows = [x for x in text.splitlines() if x.startswith("| ") and "(n=" in x]
    assert any(x.endswith("| sí (p<0.05) |") for x in result_rows)

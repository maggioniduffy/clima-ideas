import json
import math

import numpy as np
import pandas as pd
import pytest

from clima_nqn.stages.ar import catalog
from clima_nqn.stages.ar import enso_extremes as ex

# --- fixtures ------------------------------------------------------------------------------


def oni_by_month(per_month: dict[str, float], default: float = 0.0) -> pd.DataFrame:
    months = pd.period_range("1979-01", "2026-12", freq="M")
    vals = [per_month.get(str(m), default) for m in months]
    return pd.DataFrame({"date": months.to_timestamp(), "oni": vals})


def zeros(start="1980-01-01", end="1983-12-31") -> pd.Series:
    return pd.Series(0.0, index=pd.date_range(start, end, freq="D"))


def djf_enso() -> pd.DataFrame:
    """DJF 1981 Niño (+1), DJF 1982 Niña (-1), DJF 1983 neutral."""
    per = {"1980-12": 1.0, "1981-01": 1.0, "1981-02": 1.0}
    per |= {"1981-12": -1.0, "1982-01": -1.0, "1982-02": -1.0}
    return oni_by_month(per)


def djf_row(table: pd.DataFrame, year: int) -> pd.Series:
    return table[(table["season"] == "DJF") & (table["year"] == year)].iloc[0]


# --- season table --------------------------------------------------------------------------


def test_counts_per_season_year_and_december_rule():
    daily = zeros()
    daily["1981-01-05"] = 10.0
    daily["1981-01-06"] = 12.0  # two extremes in DJF 1981
    daily["1982-02-01"] = 11.0  # one in DJF 1982
    daily["1982-12-31"] = 15.0  # December -> DJF 1983
    table = ex.season_table(daily, djf_enso(), threshold=10.0)
    r81, r82, r83 = (djf_row(table, y) for y in (1981, 1982, 1983))
    assert (r81["n_extreme_days"], r82["n_extreme_days"], r83["n_extreme_days"]) == (2, 1, 1)
    assert bool(r81["any_extreme"]) and bool(r83["any_extreme"])
    assert (r81["phase"], r82["phase"], r83["phase"]) == ("nino", "nina", "neutral")
    assert r81["oni_mean"] == pytest.approx(1.0)


def test_threshold_is_inclusive():
    daily = zeros()
    daily["1981-01-05"] = 10.0  # exactly the threshold
    daily["1981-01-06"] = 9.99
    table = ex.season_table(daily, djf_enso(), threshold=10.0)
    assert djf_row(table, 1981)["n_extreme_days"] == 1


def test_incomplete_edge_seasons_dropped():
    table = ex.season_table(zeros(), djf_enso(), threshold=10.0)
    keys = set(zip(table["season"], table["year"], strict=True))
    assert ("DJF", 1980) not in keys  # lacks Dec 1979
    assert ("DJF", 1984) not in keys  # only Dec 1983
    assert ("DJF", 1981) in keys and ("SON", 1983) in keys


def test_threshold_from_quantile_matches_numpy():
    rng = np.random.default_rng(1)
    daily = pd.Series(rng.gamma(0.5, 5.0, size=len(zeros())), index=zeros().index)
    assert ex.threshold_of(daily, 0.99) == float(np.quantile(daily.to_numpy(), 0.99))


# --- statistics ----------------------------------------------------------------------------


def test_spearman_perfect_monotone():
    out = ex.spearman([1, 2, 3, 4, 5, 6], [10, 20, 30, 40, 50, 60], n_perm=500, seed=0)
    assert out["rho"] == pytest.approx(1.0)
    assert 0 < out["p"] < 0.05
    out = ex.spearman([1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1], n_perm=500, seed=0)
    assert out["rho"] == pytest.approx(-1.0)


def test_spearman_ties_use_average_ranks():
    out = ex.spearman([1, 1, 2, 3], [1, 2, 3, 4], n_perm=200, seed=0)
    ranks = pd.Series([1, 1, 2, 3]).rank().to_numpy()
    expected = np.corrcoef(ranks, [1, 2, 3, 4])[0, 1]
    assert out["rho"] == pytest.approx(expected)


def test_spearman_constant_is_nan():
    out = ex.spearman([0, 0, 0, 0], [1, 2, 3, 4], n_perm=100, seed=0)
    assert math.isnan(out["rho"]) and math.isnan(out["p"])


def test_spearman_is_deterministic_with_seed():
    x = [3, 1, 4, 1, 5, 9, 2, 6]
    y = [2, 7, 1, 8, 2, 8, 1, 8]
    assert ex.spearman(x, y, 300, 0) == ex.spearman(x, y, 300, 0)


# --- variants and payload --------------------------------------------------------------------


def long_daily(seed=0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1979-01-01", "2002-12-31", freq="D")
    return pd.Series(rng.gamma(0.4, 6.0, size=len(idx)), index=idx)


def long_enso(seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    months = pd.period_range("1979-01", "2002-12", freq="M")
    return pd.DataFrame({"date": months.to_timestamp(), "oni": rng.normal(0, 1, len(months))})


def test_group_counts_and_rows_on_known_series():
    daily = zeros()
    daily["1981-01-05"] = 10.0
    daily["1981-01-06"] = 12.0
    daily["1982-02-01"] = 11.0
    table = ex.season_table(daily, djf_enso(), threshold=10.0)
    rows = ex.compute_results(table, n_perm=200, seed=0)
    djf = next(r for r in rows if r["season"] == "DJF")
    assert djf["phase_years"] == {"nino": 1, "neutral": 1, "nina": 1}
    assert djf["groups"]["nino"] == {
        "n": 1, "years_with_extreme": 1, "total_days": 2, "mean_days": 2.0
    }  # fmt: skip
    assert djf["groups"]["nina"]["total_days"] == 1
    assert djf["groups"]["neutral"]["years_with_extreme"] == 0
    assert djf["diff_nino_nina"] == pytest.approx(1.0)


def test_payload_matches_contract():
    daily, enso = long_daily(), long_enso()
    payload = ex.build_payload(
        {"polygon": daily, "rectangle": daily * 1.1}, enso, n_perm=100, seed=0, source="src"
    )
    assert set(payload) == {"meta", "variants", "robust"}
    assert set(payload["meta"]) == {
        "period", "season_years_period", "source", "n_perm", "seed", "alpha"
    }  # fmt: skip
    assert payload["meta"]["period"] == "1979-01-01/2002-12-31"
    assert payload["meta"]["season_years_period"] == "1980-2025"
    assert set(payload["variants"]) == {"main", "p95", "rectangle"}
    v = payload["variants"]["main"]
    assert set(v) == {
        "label", "quantile", "region", "threshold_mm", "n_extreme_days_total", "rows",
        "season_years",
    }  # fmt: skip
    assert v["label"] == "p99, polígono" and v["quantile"] == 0.99 and v["region"] == "polygon"
    assert payload["variants"]["p95"]["label"] == "p95, polígono"
    assert payload["variants"]["rectangle"]["label"] == "p99, rectángulo"
    assert payload["variants"]["rectangle"]["region"] == "rectangle"
    assert v["threshold_mm"] == pytest.approx(float(np.quantile(daily.to_numpy(), 0.99)))
    assert v["n_extreme_days_total"] == int((daily >= v["threshold_mm"]).sum())
    assert [r["season"] for r in v["rows"]] == ["DJF", "MAM", "JJA", "SON"]
    assert set(v["rows"][0]) == {
        "season", "phase_years", "groups", "diff_nino_nina", "p", "p_bh", "p_3group",
        "p_3group_bh", "spearman_rho", "p_oni", "p_oni_bh", "sustained_bh",
    }  # fmt: skip
    assert set(v["rows"][0]["groups"]["nino"]) == {
        "n", "years_with_extreme", "total_days", "mean_days"
    }  # fmt: skip
    assert set(v["season_years"][0]) == {
        "season", "year", "oni_mean", "phase", "n_extreme_days", "any_extreme"
    }  # fmt: skip
    assert set(payload["robust"]) == {"DJF", "MAM", "JJA", "SON"}


def test_payload_is_deterministic():
    daily, enso = long_daily(), long_enso()
    args = ({"polygon": daily, "rectangle": daily}, enso)
    a = ex.build_payload(*args, n_perm=100, seed=0, source="s")
    b = ex.build_payload(*args, n_perm=100, seed=0, source="s")
    assert json.dumps(ex._clean(a)) == json.dumps(ex._clean(b))


def test_robust_flag_logic():
    def v(diff, sus):
        return {"rows": [{"season": "DJF", "diff_nino_nina": diff, "sustained_bh": sus}]}

    same = {"main": v(1.0, True), "p95": v(0.5, True), "rectangle": v(2.0, True)}
    assert ex.robust_flags(same, ["DJF"]) == {"DJF": True}
    flip_sign = {**same, "p95": v(-0.5, True)}
    assert ex.robust_flags(flip_sign, ["DJF"]) == {"DJF": False}
    flip_bh = {**same, "rectangle": v(2.0, False)}
    assert ex.robust_flags(flip_bh, ["DJF"]) == {"DJF": False}
    all_null = {k: v(0.5, False) for k in same}
    assert ex.robust_flags(all_null, ["DJF"]) == {"DJF": True}
    nan = {**same, "p95": v(math.nan, True)}
    assert ex.robust_flags(nan, ["DJF"]) == {"DJF": False}


# --- report --------------------------------------------------------------------------------


def test_count_sentence_format():
    row = {
        "season": "JJA",
        "groups": {
            "nino": {"n": 7, "years_with_extreme": 5},
            "nina": {"n": 7, "years_with_extreme": 3},
        },
    }
    s = ex.count_sentence(row)
    assert s == ("5 de 7 inviernos Niño y 3 de 7 inviernos Niña tuvieron al menos un día extremo")
    for season, noun in (("DJF", "veranos"), ("MAM", "otoños"), ("SON", "primaveras")):
        assert noun in ex.count_sentence({**row, "season": season})


def test_report_and_json_written(tmp_path):
    daily, enso = long_daily(), long_enso()
    payload = ex.build_payload(
        {"polygon": daily, "rectangle": daily * 1.1}, enso, n_perm=100, seed=0, source="src"
    )
    path = ex.write_report(payload, tmp_path / "F1.9.md")
    md = path.read_text(encoding="utf-8")
    assert "de cada" not in md
    assert "tuvieron al menos un día extremo" in md
    assert "29,2" in md and "Sensibilidad" in md and "Salvedades" in md
    assert str(catalog.CORDILLERA_POLYGON[0]) not in md  # vertices are not printed
    data = json.loads((tmp_path / "F1.9.json").read_text(encoding="utf-8"))
    assert set(data) == {"meta", "variants", "robust"}


def test_run_writes_both_files(tmp_path, monkeypatch):
    daily, enso = long_daily(), long_enso()
    from clima_nqn.io import enso as io_enso

    enso_path = tmp_path / "enso.parquet"
    enso.assign(phase=io_enso.classify_phase(enso["oni"])).to_parquet(enso_path)
    monkeypatch.setattr(ex.catalog, "read_metadata", lambda p: {})
    calls = []

    def fake_daily(paths, polygon):
        calls.append(polygon)
        return (daily if len(calls) == 1 else daily * 1.1), None

    monkeypatch.setattr(ex.extremes, "daily_precip", fake_daily)
    out = ex.run(tmp_path / "events.parquet", [], enso_path, tmp_path / "out", n_perm=100)
    assert len(calls) == 2  # one read per region
    assert calls[1] == catalog.LEGACY_RECTANGLE
    assert (tmp_path / "out" / "F1.9.md").is_file() and (tmp_path / "out" / "F1.9.json").is_file()
    assert set(out["variants"]) == {"main", "p95", "rectangle"}


def _payload_for_report(tmp_path):
    daily, enso = long_daily(), long_enso()
    return ex.build_payload({"polygon": daily, "rectangle": daily * 1.1}, enso, n_perm=100, seed=0)


def test_threshold_note_is_computed(tmp_path):
    payload = _payload_for_report(tmp_path)
    payload["variants"]["main"]["threshold_mm"] = 29.21
    md = ex.write_report(payload, tmp_path / "a.md").read_text(encoding="utf-8")
    assert "Coincide con el umbral de F1.4 (29,2 mm/día)." in md
    payload["variants"]["main"]["threshold_mm"] = 31.0
    md = ex.write_report(payload, tmp_path / "b.md").read_text(encoding="utf-8")
    assert "No coincide con F1.4 (29,2 mm/día): revisar." in md


def test_reading_labels():
    on, off = {"sustained_bh": True}, {"sustained_bh": False}
    assert ex.reading([off, off, off], False) == "ninguna variante sostiene diferencia"
    assert ex.reading([on, on, on], True) == "diferencia sostenida en las tres"
    assert ex.reading([on, off, on], False) == "cambia según la variante"
    assert ex.reading([on, on, on], False) == "cambia según la variante"


def test_sensitivity_table_and_note(tmp_path):
    md = ex.write_report(_payload_for_report(tmp_path), tmp_path / "a.md").read_text(
        encoding="utf-8"
    )
    assert "p BH Niño − Niña (p99 pol. / p95 pol. / p99 rect.)" in md
    assert "| ¿Robusto? (regla fijada) | Lectura |" in md
    assert "cambia alrededor de 0" in md


def test_summary_bullets_and_closing_line(tmp_path):
    payload = _payload_for_report(tmp_path)
    for v in payload["variants"].values():
        for r in v["rows"]:
            r["p"] = r["p_bh"] = r["p_3group"] = r["p_3group_bh"] = r["p_oni"] = r["p_oni_bh"] = 0.5
    son = next(r for r in payload["variants"]["main"]["rows"] if r["season"] == "SON")
    payload["robust"]["SON"] = True  # as in the real run: same sign, no variant sustained
    son.update(p=0.047, p_bh=0.19, spearman_rho=0.38, p_oni_bh=0.043)
    for name, val in (("p95", 0.055), ("rectangle", 0.06)):
        next(r for r in payload["variants"][name]["rows"] if r["season"] == "SON")["p_oni_bh"] = val
    md = ex.write_report(payload, tmp_path / "a.md").read_text(encoding="utf-8")
    resumen = md.split("## Resumen")[1].split("## Salvedades")[0]
    assert resumen.count("\n- ") == 2  # SON bullet + closing line
    assert (
        "Niño − Niña p 0,047 sin ajustar, p BH 0,19 (no sostenido; igual en las tres variantes)"
        in resumen
    )
    assert (
        "ρ con el ONI 0,38, p BH 0,043 con p99 en el polígono, 0,055 con p95 y 0,060 con el rectángulo"
        in resumen
    )
    # The ONI result is significant only in the main variant: not robust, whatever the pair rule says.
    assert "primaveras Niño y" in resumen and "con el rectángulo: no robusto." in resumen
    for name in ("p95", "rectangle"):
        next(r for r in payload["variants"][name]["rows"] if r["season"] == "SON")["p_oni_bh"] = (
            0.01
        )
    payload["robust"]["SON"] = False
    md = ex.write_report(payload, tmp_path / "b.md").read_text(encoding="utf-8")
    assert "(no sostenido; cambia según la variante)" in md
    assert "con el rectángulo: se sostiene en las tres variantes." in md
    assert resumen.rstrip().endswith(
        "ENSO se informa como contexto de los extremos, no como predictor."
    )


def test_write_report_accepts_loaded_json(tmp_path):
    payload = _payload_for_report(tmp_path)
    first = ex.write_report(payload, tmp_path / "a.md")
    loaded = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    second = ex.write_report(loaded, tmp_path / "b.md")
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    assert (tmp_path / "a.json").read_text() == (tmp_path / "b.json").read_text()

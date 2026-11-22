"""F5.4: AIFS vs. IFS paired comparison, synthetic and offline."""

import numpy as np
import pandas as pd
import pytest

from clima_nqn.stages.hindcast import compare as c
from clima_nqn.stages.hindcast import forecasts as fc
from clima_nqn.stages.hindcast import store

IFS_SPEC, AIFS_SPEC = fc.MODELS["ifs"], fc.MODELS["aifs"]


def _cases(ids, kinds=None, start="2024-03-10", step=10):
    dates = pd.date_range(start, periods=len(ids), freq=f"{step}D")
    kinds = kinds or ["event"] * len(ids)
    return pd.DataFrame(
        {
            "case_id": ids,
            "kind": kinds,
            "event_id": [f"ev-{i}" if k == "event" else None for i, k in zip(ids, kinds)],
            "valid_date": dates,
        }
    )


def _store(spec, cases, values, leads=(1, 2)):
    """values: scalar or (case, lead) array of the (constant) forecast over the box."""
    ds = store.empty_store(spec, cases, leads)
    vals = np.broadcast_to(np.asarray(values, dtype="float32"), (len(cases), len(leads)))
    ds["precip_mm"].values[:] = vals[:, :, None, None, None]
    ds["status"].values[:] = fc.STATUS_OK
    return ds


def _obs(cases, value=5.0):
    return pd.Series(value, index=pd.to_datetime(cases["valid_date"]))


def _table_rows(ae_ifs, ae_aifs, kind="event", lead=1):
    """Hand-made paired table with the given absolute errors (obs = 10)."""
    n = len(ae_ifs)
    dates = pd.date_range("2024-03-10", periods=n, freq="10D")
    ifs = 10 + np.asarray(ae_ifs, float)
    aifs = 10 + np.asarray(ae_aifs, float)
    t = pd.DataFrame(
        {
            "case": [f"c{i}" for i in range(n)],
            "kind": kind,
            "event_id": "e",
            "valid_date": dates,
            "lead": lead,
            "obs": 10.0,
            "ifs": ifs,
            "aifs": aifs,
            "ae_ifs": np.abs(ifs - 10),
            "ae_aifs": np.abs(aifs - 10),
        }
    )
    d = (t["ae_aifs"] - t["ae_ifs"]).abs()
    t["winner"] = np.where(
        d < c.TIE_MM, "empate", np.where(t["ae_aifs"] < t["ae_ifs"], "aifs", "ifs")
    )
    return t


# --- paired table -----------------------------------------------------------------------------


def test_inner_join_rows_and_values():
    ci = _cases(["a", "b", "c"], ["event", "control", "event"])
    ca = _cases(["b", "c", "d"], ["control", "event", "event"], start="2024-03-20")
    ifs, aifs = _store(IFS_SPEC, ci, 6.0), _store(AIFS_SPEC, ca, 8.0)
    aifs["status"].values[1, 1, :] = fc.STATUS_MISSING  # case "c", lead 2
    t = c.paired_table(ifs, aifs, _obs(ci, 5.0))
    assert set(t["case"]) == {"b", "c"}  # "a" only in IFS, "d" only in AIFS
    assert set(zip(t["case"], t["lead"])) == {("b", 1), ("b", 2), ("c", 1)}
    r = t[(t["case"] == "b") & (t["lead"] == 1)].iloc[0]
    assert r["kind"] == "control" and r["obs"] == 5.0
    assert r["ifs"] == pytest.approx(6.0) and r["aifs"] == pytest.approx(8.0)
    assert r["ae_ifs"] == pytest.approx(1.0) and r["ae_aifs"] == pytest.approx(3.0)
    assert r["winner"] == "ifs"
    assert r["valid_date"] == pd.Timestamp("2024-03-20")


def test_winner_and_tie_rule():
    ci = _cases(["a", "b", "c"])
    ifs = _store(IFS_SPEC, ci, 6.0, (1, 2))
    aifs = _store(AIFS_SPEC, ci, [[5.2, 6.04], [6.9, 4.04], [8.0, 4.0]])
    t = c.paired_table(ifs, aifs, _obs(ci, 5.0))
    w = t.set_index(["case", "lead"])["winner"]
    assert w[("a", 1)] == "aifs"  # 0.2 vs 1.0
    assert w[("a", 2)] == "empate"  # 1.04 vs 1.00: diff 0.04 < 0.05
    assert w[("b", 1)] == "ifs"  # 1.9 vs 1.0
    assert w[("b", 2)] == "empate"  # 0.96 vs 1.0
    assert w[("c", 1)] == "ifs"  # 3.0 vs 1.0
    assert w[("c", 2)] == "empate"  # 1.0 vs 1.0


# --- summary ----------------------------------------------------------------------------------


def test_sign_test_known_configuration():
    assert c.sign_test_p(10, 0) == pytest.approx(2 * 0.5**10)
    assert c.sign_test_p(5, 5) == pytest.approx(1.0)
    assert c.sign_test_p(8, 2) == pytest.approx(0.109375)
    assert np.isnan(c.sign_test_p(0, 0))


def test_summary_diff_sign_counts_and_bias():
    # AIFS better in every pair: AE 1 vs 3
    t = _table_rows([3.0] * 12, [1.0] * 12)
    s = c.paired_summary(t, n_boot=200)
    r = s[(s["lead"] == "1") & (s["kind"] == "event")].iloc[0]
    assert r["n"] == 12 and r["diff"] == pytest.approx(-2.0)
    assert (r["wins_aifs"], r["wins_ifs"], r["ties"]) == (12, 0, 0)
    assert r["mae_ifs"] == pytest.approx(3.0) and r["mae_aifs"] == pytest.approx(1.0)
    assert r["bias_ifs"] == pytest.approx(3.0) and r["bias_aifs"] == pytest.approx(1.0)
    assert r["p_sign"] == pytest.approx(2 * 0.5**12)
    assert r["hi"] < 0 and r["verdict"] == "AIFS mejor"
    assert set(s["kind"]) == {"event", "all"}  # no control rows in this table
    assert ((s["lead"] == "1–3") & (s["kind"] == "event")).any()


def test_summary_groups_pool_leads():
    t = pd.concat([_table_rows([3.0] * 4, [1.0] * 4, lead=L) for L in (1, 2, 3, 4)])
    s = c.paired_summary(t, n_boot=50)
    g = s[(s["lead"] == "1–3") & (s["kind"] == "event")].iloc[0]
    assert g["n"] == 12
    assert s[(s["lead"] == "4–7") & (s["kind"] == "event")].iloc[0]["n"] == 4
    assert s[(s["lead"] == "8–10")].empty


def test_verdict_requires_ci_and_sign_test():
    assert c.verdict(-3.0, -1.0, 0.01, -2.0) == "AIFS mejor"
    assert c.verdict(1.0, 3.0, 0.01, 2.0) == "AIFS peor"
    assert c.verdict(-3.0, 1.0, 0.001, -1.0) == "sin diferencia detectable"  # CI crosses 0
    assert c.verdict(-3.0, -1.0, 0.2, -2.0) == "sin diferencia detectable"  # p >= 0.05
    assert c.verdict(-3.0, -1.0, 0.05, -2.0) == "sin diferencia detectable"
    assert c.verdict(np.nan, np.nan, np.nan, np.nan) == "sin diferencia detectable"
    # CI excludes 0 but the sign test does not: 6 clear wins vs 4 small losses
    t = _table_rows([4, 4, 4, 4, 4, 4, 1.0, 1.0, 1.0, 1.0], [0.0] * 6 + [1.2] * 4)
    r = c.paired_summary(t, n_boot=300).query("kind == 'event' and lead == '1'").iloc[0]
    assert r["p_sign"] > 0.05 and r["verdict"] == "sin diferencia detectable"


# --- report -----------------------------------------------------------------------------------


def test_render_md_placeholder_and_one_section_per_event():
    ci = _cases(["a", "b", "c"], ["event", "event", "control"])
    ifs, aifs = _store(IFS_SPEC, ci, 6.0), _store(AIFS_SPEC, ci, 7.0)
    t = c.paired_table(ifs, aifs, _obs(ci, 5.0))
    s = c.paired_summary(t, n_boot=50)
    meta = {"n_event": 2, "n_control": 1, "first": "2024-03-10", "last": "2024-03-30",
            "native_025": c.native_025(t), "n_boot": 50, "seed": 0}  # fmt: skip
    md = c.render_md(t, s, meta)
    assert c.PLACEHOLDER in md
    for h in ("## Veredicto", "## Fuente y alcance", "## Regla fijada antes de correr",
              "## Tabla por evento", "## Advertencias"):  # fmt: skip
        assert h in md
    section = md.split("## Tabla por evento")[1].split("## Advertencias")[0]
    assert section.count("### ") == 2 and "ev-a" in section and "ev-b" in section
    assert "ev-c" not in section  # controls only in the summary
    assert "≥ 2024-02-29" in md and "Potencia baja" in md
    assert "1,00" in md  # decimal comma


def test_native_025_flags_early_dates():
    t = _table_rows([1.0], [1.0])
    assert c.native_025(t)
    t["valid_date"] = pd.Timestamp("2024-02-28")
    assert not c.native_025(t)

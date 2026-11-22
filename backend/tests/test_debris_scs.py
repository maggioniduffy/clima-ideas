import math

import pytest

from clima_nqn.stages.debris import scs

IN = 25.4


def test_runoff_depth_tr55_table_2_1_cn80():
    # USDA NRCS TR-55 (1986), Table 2-1 "Runoff depth for selected CN's and rainfall amounts": CN 80, P = 5.0 in
    # -> Q = 2.89 in. Cell value recalled from the table, page number sin verificar; the number is also
    # reproduced by the formula: S = 1000/80 - 10 = 2.5 in, Ia = 0.5 in, Q = 4.5**2 / (4.5 + 2.5) = 2.893 in.
    q_mm = scs.runoff_depth_mm(5.0 * IN, 80)
    assert q_mm / IN == pytest.approx(2.893, abs=0.005)
    assert q_mm / IN == pytest.approx(4.5**2 / 7.0, rel=1e-9)  # hand formula in US units


def test_retention_si():
    assert scs.retention_mm(80) == pytest.approx(63.5)  # 25400/80 - 254
    assert scs.retention_mm(100) == pytest.approx(0.0)


def test_no_runoff_below_initial_abstraction():
    assert scs.runoff_depth_mm(10.0, 80) == 0.0  # Ia = 12.7 mm
    assert scs.peak_discharge_m3s(1.0, 80, 10.0, 1.0, 0.5) == 0.0


def test_scs_lag_and_tc_us_equation_reproduced():
    # NEH-4 ch.15 / TR-55 lag: Tl = L^0.8 (S+1)^0.7 / (1900 Y^0.5), L ft, S = 1000/CN-10 in, Y %.
    # Hand calc for L = 3000 ft (914.4 m), CN 80, Y = 4 %: 3000^0.8 = 604.4..., (3.5)^0.7 = 2.404...,
    # den = 3800 -> Tl = 0.3824 h; reproduced here from the formula, not from a book table (sin verificar).
    tl = scs.scs_lag_h(914.4, 80, 4.0)
    expect = 3000**0.8 * (1000 / 80 - 10 + 1) ** 0.7 / (1900 * 4.0**0.5)
    assert tl == pytest.approx(expect, rel=1e-6)
    assert scs.time_of_concentration_h(914.4, 80, 4.0) == pytest.approx(expect / 0.6, rel=1e-6)


def test_unit_hydrograph_constant_0_208():
    # qp = 0.208 A Q / Tp (A km2, Q mm, Tp h): triangular UH with base 2.67 Tp, so
    # V = A*Q = 0.5 * qp * 2.67 Tp -> qp = 1000 m3 / (0.5*... ) : 1 km2 * 1 mm = 1000 m3, Tp = 1 h
    # qp = 2 V / (2.67 * 3600 s) = 0.2081 m3/s.
    assert scs.PEAK_RATE_CONSTANT == 0.208
    assert 2 * 1000 / (2.67 * 3600) == pytest.approx(0.208, abs=0.001)
    # direct: A = 2 km2, P such that Q is known, D/2 + Tl = Tp
    q = scs.runoff_depth_mm(100.0, 80)
    peak = scs.peak_discharge_m3s(2.0, 80, 100.0, duration_h=1.0, lag_h=0.5)  # Tp = 0.5 + 0.5 = 1 h
    assert peak == pytest.approx(0.208 * 2.0 * q / 1.0)


def test_design_table_picks_critical_duration():
    rains = {(10, 1.0): 30.0, (10, 3.0): 50.0, (10, 24.0): 90.0}
    rows = scs.design_peaks(area_km2=5.0, cn=80, length_m=3000, slope_pct=5.0, rains=rains)
    assert [r.return_period for r in rows] == [10]
    r = rows[0]
    assert r.peak_m3s == max(
        scs.peak_discharge_m3s(5.0, 80, p, d, scs.scs_lag_h(3000, 80, 5.0))
        for (_, d), p in rains.items()
    )
    assert math.isfinite(r.critical_duration_h)

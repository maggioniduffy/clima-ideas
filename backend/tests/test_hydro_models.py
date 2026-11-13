import numpy as np
import pytest

from clima_nqn.stages.flood import hydro_models as hm


def forcing(n, seed=0):
    """Seasonal synthetic forcing: precip (mm/d), temperature (degC), PET (mm/d)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    season = np.cos(2 * np.pi * t / 365.25)
    temp = 6 - 10 * season + rng.normal(0, 2, n)
    wet = rng.random(n) < 0.35
    precip = np.where(wet, rng.gamma(0.8, 9.0, n), 0.0) * (1.2 + 0.5 * season)
    pet = np.clip(1.6 - 1.4 * season + 0.1 * rng.normal(size=n), 0, None)
    return precip, temp, pet


# --- metrics ---------------------------------------------------------------


def test_nse_hand_computed():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    sim = np.array([1.0, 3.0, 3.0, 5.0])
    # SSE = 2, SST = 5
    assert hm.nse(obs, sim) == pytest.approx(1 - 2 / 5)


def test_kge_hand_computed():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    sim = np.array([1.0, 3.0, 3.0, 5.0])
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = sim.std() / obs.std()
    beta = sim.mean() / obs.mean()
    expected = 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    assert hm.kge(obs, sim) == pytest.approx(expected)
    # literal numbers: r=0.8528..., alpha=sqrt(1.5/1.25)... guard against swapped alpha/beta
    assert hm.kge(obs, 2 * obs) == pytest.approx(1 - np.sqrt((2 - 1) ** 2 + (2 - 1) ** 2))


def test_perfect_sim_gives_one():
    obs = np.array([0.5, 2.0, 7.0, 1.0, 3.0])
    assert hm.nse(obs, obs) == pytest.approx(1.0)
    assert hm.kge(obs, obs) == pytest.approx(1.0)


def test_metrics_ignore_nan_pairs():
    obs = np.array([1.0, 2.0, np.nan, 3.0, 4.0, 9.0])
    sim = np.array([1.0, 3.0, 5.0, 3.0, 5.0, np.nan])
    clean = (np.array([1.0, 2.0, 3.0, 4.0]), np.array([1.0, 3.0, 3.0, 5.0]))
    assert hm.nse(obs, sim) == pytest.approx(hm.nse(*clean))
    assert hm.kge(obs, sim) == pytest.approx(hm.kge(*clean))


def test_metrics_nan_when_degenerate():
    assert np.isnan(hm.nse([1.0], [1.0]))
    assert np.isnan(hm.kge([np.nan, 1.0], [1.0, np.nan]))
    assert np.isnan(hm.nse([2.0, 2.0, 2.0], [1.0, 2.0, 3.0]))  # zero variance of obs
    assert np.isnan(hm.kge([2.0, 2.0, 2.0], [1.0, 2.0, 3.0]))


# --- persistence -----------------------------------------------------------


def test_persistence_shifts_by_lead():
    q = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = hm.persistence(q, 2)
    assert np.isnan(out[:2]).all()
    np.testing.assert_array_equal(out[2:], q[:-2])
    np.testing.assert_array_equal(hm.persistence(q, 0), q)


def test_persistence_lead_longer_than_series():
    assert np.isnan(hm.persistence(np.ones(3), 5)).all()


# --- CemaNeige -------------------------------------------------------------


def test_cemaneige_cold_keeps_everything_as_snow():
    p = np.full(60, 5.0)
    res = hm.cemaneige(p, np.full(60, -10.0), ctg=0.5, kf=3.0)
    assert res.melt.sum() == 0
    np.testing.assert_allclose(res.liquid, 0.0)
    assert res.snowpack[-1] == pytest.approx(p.sum())


def test_cemaneige_warm_everything_liquid():
    p = np.full(60, 5.0)
    res = hm.cemaneige(p, np.full(60, 10.0), ctg=0.5, kf=3.0)
    np.testing.assert_allclose(res.liquid, p)
    np.testing.assert_allclose(res.snowpack, 0.0)


def test_cemaneige_mass_balance_and_melt_phase():
    p, temp, _ = forcing(5 * 365)
    res = hm.cemaneige(p, temp, ctg=0.3, kf=4.0)
    assert res.snowpack[-1] + res.liquid.sum() == pytest.approx(p.sum())
    assert res.melt.sum() > 0
    assert (res.snowpack >= -1e-9).all()


def test_cemaneige_split_is_linear_between_minus1_and_3():
    res = hm.cemaneige(np.array([10.0]), np.array([1.0]), ctg=0.0, kf=0.0)
    # solid fraction (3 - 1) / 4 = 0.5, no melt with kf = 0
    assert res.liquid[0] == pytest.approx(5.0)
    assert res.snowpack[0] == pytest.approx(5.0)


# --- GR4J ------------------------------------------------------------------


def test_gr4j_water_balance_closes():
    p, _, e = forcing(10 * 365)
    res = hm.gr4j(p, e, x1=350.0, x2=-0.8, x3=90.0, x4=1.8)
    stored = res.prod_store + res.rout_store + res.uh_store
    stored0 = 0.3 * 350.0 + 0.5 * 90.0
    closure = p.sum() - res.ae.sum() - res.q.sum() + res.exchange.sum() - (stored[-1] - stored0)
    assert abs(closure) < 1e-6 * p.sum()
    assert (res.q >= 0).all()
    assert (res.ae <= e + 1e-9).all()


def test_gr4j_initial_states_configurable():
    p, _, e = forcing(30)
    a = hm.gr4j(p, e, 350.0, 0.0, 90.0, 1.8, s0=0.0, r0=0.0)
    b = hm.gr4j(p, e, 350.0, 0.0, 90.0, 1.8, s0=1.0, r0=1.0)
    assert a.q[0] != b.q[0]


def test_gr4j_unit_hydrograph_delays_pulse():
    p = np.zeros(40)
    p[0] = 50.0
    e = np.zeros(40)
    res = hm.gr4j(p, e, x1=300.0, x2=0.0, x3=80.0, x4=3.0, s0=0.0, r0=0.0)
    # the pulse is spread over the unit hydrographs: the peak is not on the rain day
    assert res.q.argmax() > 0
    assert res.q[0] < res.q.max()
    assert res.uh_store[0] > 0


# --- simulate / calibrate --------------------------------------------------

TRUE = hm.Params(x1=420.0, x2=-1.2, x3=110.0, x4=2.4, ctg=0.35, kf=4.5)


def test_simulate_chains_snow_into_gr4j():
    p, temp, e = forcing(3 * 365)
    sim = hm.simulate(TRUE, p, temp, e)
    snow = hm.cemaneige(p, temp, TRUE.ctg, TRUE.kf)
    direct = hm.gr4j(snow.liquid, e, TRUE.x1, TRUE.x2, TRUE.x3, TRUE.x4)
    np.testing.assert_allclose(sim.q, direct.q)
    assert sim.snowpack.shape == sim.q.shape


@pytest.mark.slow
def test_calibrate_recovers_known_parameters():
    p, temp, e = forcing(8 * 365, seed=3)
    qobs = hm.simulate(TRUE, p, temp, e).q
    fit = hm.calibrate(p, temp, e, qobs, warmup=365)
    assert fit.kge > 0.98
    # Noise-free synthetic flow with the same model: x1 and x3 are identifiable within 20 %.
    assert fit.params.x1 == pytest.approx(TRUE.x1, rel=0.2)
    assert fit.params.x3 == pytest.approx(TRUE.x3, rel=0.2)
    # warm-up days and NaN observations are excluded from the score
    sim = hm.simulate(fit.params, p, temp, e).q
    assert fit.kge == pytest.approx(hm.kge(qobs[365:], sim[365:]), abs=1e-6)


def test_calibrate_ignores_missing_observations():
    p, temp, e = forcing(6 * 365, seed=5)
    qobs = hm.simulate(TRUE, p, temp, e).q
    qobs[400:500] = np.nan
    fit = hm.calibrate(p, temp, e, qobs, warmup=365)
    assert fit.kge > 0.95


@pytest.mark.slow
def test_calibrate_30_years_is_fast():
    import time

    p, temp, e = forcing(30 * 365, seed=7)
    qobs = hm.simulate(TRUE, p, temp, e).q
    t0 = time.perf_counter()
    fit = hm.calibrate(p, temp, e, qobs, warmup=365)
    assert time.perf_counter() - t0 < 60
    assert fit.kge > 0.98

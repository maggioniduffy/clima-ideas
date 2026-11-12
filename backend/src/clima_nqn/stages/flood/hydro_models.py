"""Conceptual hydrological baselines for daily streamflow (plan/02, F2.5; spec S7).

Pure numpy/scipy baselines to compare an LSTM against: GR4J with the CemaNeige snow module,
persistence, and the NSE / KGE scores.

Sources:
- Perrin, C., Michel, C., Andreassian, V. (2003). Improvement of a parsimonious model for streamflow
  simulation. J. Hydrol. 279, 275-289 (GR4J).
- Valery, A., Andreassian, V., Perrin, C. (2014). "As simple as possible but not simpler": what is
  useful in a temperature-based snow-accounting routine? Part 2. J. Hydrol. 517, 1176-1187 (CemaNeige).
- USACE (1956). Snow hydrology (linear rain/snow transition on air temperature).
- Nash, J.E., Sutcliffe, J.V. (1970). River flow forecasting through conceptual models. J. Hydrol. 10.
- Gupta, H.V., Kling, H., Yilmaz, K.K., Martinez, G.F. (2009). Decomposition of the mean squared
  error and NSE performance criteria. J. Hydrol. 377, 80-91 (KGE).

Units: precipitation, PET and flow are depths in mm/d over the basin (not m3/s); temperature in degC;
x1, x3 in mm, x2 in mm/d, x4 in d, CTG dimensionless, Kf in mm/degC/d.

Assumptions (all inherited from the cited models unless noted):
- Lumped, single elevation layer (no elevation bands: the basins are modelled as one box).
- Initial unit-hydrograph stores and snowpack are zero; production and routing stores start at
  ``s0 * x1`` and ``r0 * x3`` (defaults 0.3 and 0.5). The caller discards a warm-up period.
- Forcing must be complete (no NaN); observed flow may contain NaN (those days are not scored).
- PET is an input (computed elsewhere, e.g. Oudin); this module does not derive it.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np
from scipy.optimize import differential_evolution

# CemaNeige constants (Valery et al. 2014).
SNOW_T_ALL_SOLID = -1.0  # degC: below it all precipitation is snow
SNOW_T_ALL_LIQUID = 3.0  # degC: above it all precipitation is rain
MELT_T = 0.0  # degC melt threshold on the thermal state and on the daily mean temperature
G_THRESHOLD_FRAC = 0.9  # Gthreshold = 0.9 x mean annual solid precipitation
MIN_MELT_FRAC = 0.1  # melt = (0.9 * min(G / Gthreshold, 1) + 0.1) * potential melt

# Default bounds for the calibration: x1, x2, x3, x4, CTG, Kf.
BOUNDS = ((1.0, 3000.0), (-10.0, 10.0), (1.0, 1000.0), (0.5, 10.0), (0.0, 1.0), (0.0, 20.0))
DEFAULT_SEED = 42


class Params(NamedTuple):
    x1: float  # production store capacity, mm
    x2: float  # groundwater exchange coefficient, mm/d (negative: loss)
    x3: float  # routing store capacity, mm
    x4: float  # unit hydrograph time base, d
    ctg: float  # CemaNeige thermal inertia, 0-1
    kf: float  # CemaNeige degree-day factor, mm/degC/d


class SnowResult(NamedTuple):
    liquid: np.ndarray  # rain + melt, mm/d: the input of GR4J
    solid: np.ndarray  # snowfall, mm/d
    melt: np.ndarray  # mm/d
    snowpack: np.ndarray  # end-of-day snow water equivalent, mm


class GR4JResult(NamedTuple):
    q: np.ndarray  # simulated flow, mm/d
    ae: np.ndarray  # actual evapotranspiration, mm/d
    exchange: np.ndarray  # net groundwater exchange gained by the system, mm/d (+ gain, - loss)
    prod_store: np.ndarray  # end-of-day production store, mm
    rout_store: np.ndarray  # end-of-day routing store, mm
    uh_store: np.ndarray  # water still travelling in the two unit hydrographs, mm


class SimResult(NamedTuple):
    q: np.ndarray
    ae: np.ndarray
    exchange: np.ndarray
    prod_store: np.ndarray
    rout_store: np.ndarray
    uh_store: np.ndarray
    snowpack: np.ndarray
    melt: np.ndarray


class Calibration(NamedTuple):
    params: Params
    kge: float  # KGE on the scored (post warm-up, valid) days


# --- metrics ---------------------------------------------------------------


def _valid_pairs(obs, sim):
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    ok = ~(np.isnan(obs) | np.isnan(sim))
    return obs[ok], sim[ok]


def nse(obs, sim) -> float:
    """Nash-Sutcliffe efficiency; NaN pairs are ignored. NaN if < 2 pairs or obs has zero variance."""
    o, s = _valid_pairs(obs, sim)
    if o.size < 2:
        return float("nan")
    sst = float(((o - o.mean()) ** 2).sum())
    if sst == 0.0:
        return float("nan")
    return 1.0 - float(((o - s) ** 2).sum()) / sst


def kge(obs, sim) -> float:
    """Kling-Gupta efficiency (Gupta et al. 2009): 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2).

    r is the Pearson correlation, alpha = std(sim) / std(obs), beta = mean(sim) / mean(obs). NaN pairs
    are ignored. NaN if < 2 pairs, or if obs has zero variance or zero mean. A constant sim has no
    correlation: r is taken as 0.
    """
    o, s = _valid_pairs(obs, sim)
    if o.size < 2:
        return float("nan")
    so, ss = o.std(), s.std()
    mo = o.mean()
    if so == 0.0 or mo == 0.0:
        return float("nan")
    r = 0.0 if ss == 0.0 else float(np.corrcoef(o, s)[0, 1])
    return 1.0 - math.sqrt((r - 1) ** 2 + (ss / so - 1) ** 2 + (s.mean() / mo - 1) ** 2)


def persistence(qobs, lead: int) -> np.ndarray:
    """Persistence forecast: the value for day t + lead is the observed flow at day t.

    Returned on the target-day axis, so ``out[t]`` is the forecast *for* day t (NaN for t < lead).
    """
    q = np.asarray(qobs, dtype=float)
    out = np.full(q.shape, np.nan)
    if lead < 0:
        raise ValueError("lead must be >= 0")
    if lead < q.size:
        out[lead:] = q[: q.size - lead]
    return out


# --- CemaNeige -------------------------------------------------------------
#
# The public functions run one parameter set. Internally every model works on a batch of ``k``
# parameter sets at once (arrays of shape (k,) per day, outputs (k, n)): the day loop is python, so
# running the whole differential-evolution population per step is several times faster than one set
# at a time, and a single set is just ``k = 1``.


def _solid_fraction(temp: np.ndarray) -> np.ndarray:
    return np.clip((SNOW_T_ALL_LIQUID - temp) / (SNOW_T_ALL_LIQUID - SNOW_T_ALL_SOLID), 0.0, 1.0)


def _g_threshold(solid: np.ndarray) -> float:
    n = solid.size
    return max(G_THRESHOLD_FRAC * float(solid.sum()) / (n / 365.25), 1e-6) if n else 1e-6


def _snow_batch(solid, temp, ctg, kf, g_threshold):
    """Snowpack and melt for ``k`` (CTG, Kf) pairs; ``solid`` and ``temp`` are shared (n,) series."""
    n, k = solid.size, ctg.size
    melt = np.zeros((n, k))
    pack = np.zeros((n, k))
    g = np.zeros(k)
    etg = np.zeros(k)
    one_m_ctg = 1.0 - ctg
    for i, (si, ti) in enumerate(zip(solid.tolist(), temp.tolist())):
        g = g + si
        etg = np.minimum(ctg * etg + one_m_ctg * ti, 0.0)
        if ti > MELT_T:
            pot = np.minimum(kf * (ti - MELT_T), g)
            m = (0.9 * np.minimum(g / g_threshold, 1.0) + MIN_MELT_FRAC) * pot
            m = np.where(etg == 0.0, m, 0.0)  # only a ripe pack (thermal state at 0 degC) melts
            melt[i] = m
            g = g - m
        pack[i] = g
    return melt.T, pack.T


def cemaneige(precip, temp, ctg: float, kf: float, g_threshold: float | None = None) -> SnowResult:
    """CemaNeige snow accounting (Valery et al. 2014), lumped single layer.

    - Phase split: USACE-style linear rule on the daily mean temperature, solid fraction
      ``clip((3 - T) / 4, 0, 1)``: all snow at or below -1 degC, all rain at or above 3 degC.
    - Thermal state: ``eTG = CTG * eTG + (1 - CTG) * T``, capped at 0 degC.
    - Potential melt: ``Kf * (T - 0)`` when the thermal state is at 0 degC (ripe pack) and T > 0 degC,
      limited to the available snowpack (the day's snowfall is added first).
    - Melt: ``(0.9 * min(G / Gthreshold, 1) + 0.1) * potential melt``, so a pack below the threshold
      melts more slowly (partial snow cover).
    - Gthreshold: 0.9 x mean annual solid precipitation of the input series (standard choice) unless
      ``g_threshold`` is given.
    Output ``liquid`` = rain + melt, the input of GR4J.
    """
    p = np.asarray(precip, dtype=float)
    t = np.asarray(temp, dtype=float)
    solid = p * _solid_fraction(t)
    gt = _g_threshold(solid) if g_threshold is None else max(g_threshold, 1e-6)
    melt, pack = _snow_batch(solid, t, np.array([ctg], float), np.array([kf], float), gt)
    return SnowResult(liquid=p - solid + melt[0], solid=solid, melt=melt[0], snowpack=pack[0])


# --- GR4J ------------------------------------------------------------------


def _s_curves(x4: float):
    """Discrete unit hydrographs UH1 (base x4) and UH2 (base 2 x4), S-curve exponent 2.5."""
    n1 = math.ceil(x4)
    n2 = math.ceil(2 * x4)

    def sh1(t):
        return 0.0 if t <= 0 else (1.0 if t >= x4 else (t / x4) ** 2.5)

    def sh2(t):
        if t <= 0:
            return 0.0
        if t < x4:
            return 0.5 * (t / x4) ** 2.5
        if t < 2 * x4:
            return 1.0 - 0.5 * (2.0 - t / x4) ** 2.5
        return 1.0

    uh1 = np.array([sh1(i) - sh1(i - 1) for i in range(1, n1 + 1)])
    uh2 = np.array([sh2(i) - sh2(i - 1) for i in range(1, n2 + 1)])
    return uh1, uh2


def _gr4j_batch(liquid, pet, x1, x2, x3, x4, s0, r0) -> GR4JResult:
    """GR4J for ``k`` parameter sets. ``liquid`` is (k, n), ``pet`` shared (n,); outputs are (k, n).

    The production store only depends on the forcing, so it runs first; the unit hydrographs are a
    convolution of the effective rain; the routing store runs last.
    """
    k, n = liquid.shape
    pr = np.empty((n, k))
    ae = np.empty((n, k))
    sto = np.empty((n, k))
    s = s0 * x1
    tanh = np.tanh
    for i, (pi, ei) in enumerate(zip(liquid.T, pet.tolist())):
        pn = np.maximum(pi - ei, 0.0)  # net rain (zero on days with net evaporation demand)
        en = np.maximum(ei - pi, 0.0)  # net evaporation demand
        sr = s / x1
        th = tanh(pn / x1)
        ps = x1 * (1.0 - sr * sr) * th / (1.0 + sr * th)
        the = tanh(en / x1)
        es = s * (2.0 - sr) * the / (1.0 + (1.0 - sr) * the)
        ae[i] = ei - en + es
        s = s + ps - es
        perc = s * (1.0 - (1.0 + (s / (4.25 * x1)) ** 4) ** -0.25)
        s = s - perc
        pr[i] = perc + (pn - ps)
        sto[i] = s
    pr, ae, sto = pr.T, ae.T, sto.T

    q9 = np.empty((k, n))
    q1 = np.empty((k, n))
    for j in range(k):
        uh1, uh2 = _s_curves(float(x4[j]))
        q9[j] = np.convolve(0.9 * pr[j], uh1)[:n]
        q1[j] = np.convolve(0.1 * pr[j], uh2)[:n]
    uh_store = np.cumsum(pr, axis=1) - np.cumsum(q9 + q1, axis=1)

    q = np.empty((n, k))
    exch = np.empty((n, k))
    rst = np.empty((n, k))
    r = r0 * x3
    for i, (a, b) in enumerate(zip(q9.T, q1.T)):
        f = x2 * (r / x3) ** 3.5
        r_new = np.maximum(r + a + f, 0.0)
        qd = np.maximum(b + f, 0.0)
        exch[i] = (r_new - r - a) + (qd - b)
        qr = r_new * (1.0 - (1.0 + (r_new / x3) ** 4) ** -0.25)
        r = r_new - qr
        q[i] = qr + qd
        rst[i] = r
    return GR4JResult(
        q=q.T, ae=ae, exchange=exch.T, prod_store=sto, rout_store=rst.T, uh_store=uh_store
    )


def gr4j(
    liquid, pet, x1: float, x2: float, x3: float, x4: float, s0: float = 0.3, r0: float = 0.5
) -> GR4JResult:
    """GR4J daily (Perrin et al. 2003). ``liquid`` and ``pet`` in mm/d, ``s0``/``r0`` as store fractions.

    Standard formulation: production store with percolation, effective rain split 90 % / 10 % into
    UH1 (base x4) and UH2 (base 2 x4), groundwater exchange ``F = x2 * (R / x3)^3.5`` applied to the
    routing store and to the direct branch, quadratic-law routing store. Exchange is reported as the
    water actually gained (+) or lost (-) by the system, after the non-negativity limits.
    """
    p = np.asarray(liquid, dtype=float)
    e = np.asarray(pet, dtype=float)
    res = _gr4j_batch(p[None, :], e, *(np.array([v], float) for v in (x1, x2, x3, x4, s0, r0)))
    return GR4JResult(*(a[0] for a in res))


# --- chain and calibration -------------------------------------------------


def _simulate_batch(params, precip, temp, pet, s0, r0) -> SimResult:
    """``params`` is (k, 6) in ``Params`` order; every output is (k, n)."""
    x1, x2, x3, x4, ctg, kf = (params[:, i] for i in range(6))
    solid = precip * _solid_fraction(temp)
    melt, pack = _snow_batch(solid, temp, ctg, kf, _g_threshold(solid))
    liquid = (precip - solid)[None, :] + melt
    g = _gr4j_batch(liquid, pet, x1, x2, x3, x4, s0, r0)
    return SimResult(*g, snowpack=pack, melt=melt)


def simulate(params: Params, precip, temp, pet, s0: float = 0.3, r0: float = 0.5) -> SimResult:
    """CemaNeige -> GR4J. Returns flow (mm/d) and the internal fluxes and stores."""
    x = np.array([tuple(Params(*params))], dtype=float)
    res = _simulate_batch(
        x,
        np.asarray(precip, dtype=float),
        np.asarray(temp, dtype=float),
        np.asarray(pet, dtype=float),
        s0,
        r0,
    )
    return SimResult(*(a[0] for a in res))


def calibrate(
    precip,
    temp,
    pet,
    qobs,
    warmup: int = 365,
    bounds=BOUNDS,
    seed: int = DEFAULT_SEED,
    maxiter: int = 50,
    popsize: int = 8,
) -> Calibration:
    """Calibrate ``Params`` by maximising KGE with differential evolution (fixed ``seed``).

    Only days at or after ``warmup`` with a valid ``qobs`` are scored. Default bounds: x1 [1, 3000] mm,
    x2 [-10, 10] mm/d, x3 [1, 1000] mm, x4 [0.5, 10] d, CTG [0, 1], Kf [0, 20] mm/degC/d. The population
    is evaluated in one vectorised pass per generation. No local polish (it costs as much again as the
    whole search). Caveat: GR4J has a local optimum with a small x1 and a strongly negative x2; DE can
    land there for some seeds (KGE ~0.98 instead of ~1.0 on noise-free synthetic data). The result is
    deterministic for a given ``seed``; for important runs compare a few seeds and keep the best.
    """
    precip = np.asarray(precip, dtype=float)
    temp = np.asarray(temp, dtype=float)
    pet = np.asarray(pet, dtype=float)
    qobs = np.asarray(qobs, dtype=float)
    scored = np.zeros(qobs.size, dtype=bool)
    scored[warmup:] = True
    scored &= ~np.isnan(qobs)
    if scored.sum() < 2:
        raise ValueError("fewer than 2 valid observed days after the warm-up")
    obs = qobs[scored]

    def cost(x):  # x: (6, population)
        q = _simulate_batch(x.T, precip, temp, pet, 0.3, 0.5).q[:, scored]
        out = np.empty(q.shape[0])
        for j in range(q.shape[0]):
            score = kge(obs, q[j])
            out[j] = 1e3 if np.isnan(score) else -score
        return out

    res = differential_evolution(
        cost,
        bounds,
        seed=seed,
        maxiter=maxiter,
        popsize=popsize,
        tol=1e-8,
        mutation=(0.4, 1.0),
        recombination=0.9,
        init="sobol",
        polish=False,
        vectorized=True,
        updating="deferred",
    )
    return Calibration(params=Params(*res.x), kge=-float(res.fun))

"""Conceptual hydrological baselines for daily streamflow (plan/02, F2.5; spec S7).

Pure numpy/scipy baselines to compare an LSTM against: GR4J with the CemaNeige snow module,
persistence, and the NSE / KGE scores.

Sources:
- Perrin, C., Michel, C., Andreassian, V. (2003). Improvement of a parsimonious model for streamflow
  simulation. J. Hydrol. 279, 275-289 (GR4J).
- Valery, A., Andreassian, V., Perrin, C. (2014). "As simple as possible but not simpler": what is
  useful in a temperature-based snow-accounting routine? Part 2. J. Hydrol. 517, 1176-1187 (CemaNeige).
- USACE (1956). Snow hydrology (linear rain/snow transition on air temperature).
- Coron, L. et al. (2017-2025). airGR, GR hydrological models for R, v1.7.9 (GPL-2): the rules for the
  elevation layers (``CreateInputsModel``, ``DataAltiExtrapolation_Valery``) are reimplemented from its
  documented behaviour, no code was copied.
- Valery, A. (2010). Modelisation precipitations-debit sous influence nivale. PhD thesis, AgroParisTech
  (precipitation gradient 0.00041 1/m, p. 126, as quoted in airGR).
- U.S. Standard Atmosphere 1976 (tropospheric lapse rate 6.5 degC/km).
- Nash, J.E., Sutcliffe, J.V. (1970). River flow forecasting through conceptual models. J. Hydrol. 10.
- Gupta, H.V., Kling, H., Yilmaz, K.K., Martinez, G.F. (2009). Decomposition of the mean squared
  error and NSE performance criteria. J. Hydrol. 377, 80-91 (KGE).

Units: precipitation, PET and flow are depths in mm/d over the basin (not m3/s); temperature in degC;
x1, x3 in mm, x2 in mm/d, x4 in d, CTG dimensionless, Kf in mm/degC/d.

Assumptions (all inherited from the cited models unless noted):
- Lumped basin. By default a single elevation layer. Optionally CemaNeige runs on ``N`` equal-area
  elevation bands (``LayerSpec``), as in Valery et al. (2014) and airGR:

  1. Layer elevations come from the basin hypsometric curve (101 elevations, quantiles 0..100 %):
     ``nmoy = 100 // N``, ``nreste = 100 % N``; layer ``i`` spans ``nn = nmoy + 1`` curve steps while
     ``nreste > 0`` (then ``nreste -= 1``) else ``nmoy``; its elevation is ``H[c]`` if ``nn == 1``, the
     mean of ``H[c]`` and ``H[c + 1]`` if ``nn == 2``, else ``H[int(c + nn / 2)]`` (``c`` = steps already
     used). ``N = 5`` on a uniform 0..100 curve gives 10, 30, 50, 70, 90. Every layer has fraction 1/N.
  2. Precipitation (airGR ``DataAltiExtrapolation_Valery``, Zthreshold 4000 m, gradient 0.00041 1/m):
     ``P_l = P * exp(grad_p * (z_l - z_in))`` with both elevations capped at the threshold, then rescaled
     each day so that the mean over layers equals ``P`` (``PrecipScale = TRUE``; 0/0 gives 0).
  3. Temperature: constant lapse rate, ``T_l = T + (z_in - z_l) * grad_t`` with ``grad_t`` = 0.0065
     degC/m. airGR uses a day-of-year table (Valery 2010) fitted in France; it was not used because its
     seasonality is northern-hemisphere and the table was not read. The constant rate is an assumption,
     sin verificar for the Andes.
  4. Phase split and snow accounting run per layer with the same (CTG, Kf); Gthreshold is shared by all
     layers (0.9 x the basin mean annual solid precipitation, the mean over layers); the input of GR4J
     is the mean over layers of rain + melt.

  ``N = 1`` means no extrapolation: the single layer sits at ``z_in`` (the elevation the forcing
  represents) and reproduces the single-layer model exactly.
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

# Elevation layers (airGR defaults; see the module docstring).
GRAD_P = 0.00041  # 1/m: relative precipitation increase per metre (Valery 2010, p. 126)
GRAD_T = 0.0065  # degC/m: tropospheric lapse rate (U.S. Standard Atmosphere 1976), sin verificar for the Andes
Z_THRESHOLD = 4000.0  # m: no precipitation gradient above it (airGR Zthreshold)
HYPSO_POINTS = 101  # elevations at the 0, 1, ..., 100 % quantiles of the basin area

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


class LayerSpec(NamedTuple):
    """Elevation layers of CemaNeige: layer elevations (m), elevation the forcing represents (m)."""

    z_layers: tuple
    z_input: float
    grad_p: float = GRAD_P
    grad_t: float = GRAD_T
    z_threshold: float = Z_THRESHOLD


class LayerSimResult(NamedTuple):
    sim: SimResult  # basin-mean snowpack and melt in ``sim``
    precip: np.ndarray  # (L, n) layer precipitation, mm/d
    temp: np.ndarray  # (L, n) layer temperature, degC
    solid: np.ndarray  # (L, n) layer snowfall, mm/d
    melt: np.ndarray  # (L, n) layer melt, mm/d
    snowpack: np.ndarray  # (L, n) layer end-of-day snow water equivalent, mm


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
    """Snowpack and melt for ``k`` (CTG, Kf) pairs, outputs ``(k, n)``.

    ``solid`` and ``temp`` are either shared ``(n,)`` series or per-column ``(n, k)`` arrays (column
    ``j`` is run with ``ctg[j]``, ``kf[j]``): the multi-layer model tiles the parameters over the layers
    and runs all ``L * k`` columns in one python loop. Both paths give identical numbers per column.
    """
    n, k = solid.shape[0], ctg.size
    melt = np.zeros((n, k))
    pack = np.zeros((n, k))
    g = np.zeros(k)
    etg = np.zeros(k)
    one_m_ctg = 1.0 - ctg
    if solid.ndim == 2 or temp.ndim == 2:
        solid = np.broadcast_to(solid if solid.ndim == 2 else solid[:, None], (n, k))
        temp = np.broadcast_to(temp if temp.ndim == 2 else temp[:, None], (n, k))
        for i, (si, ti) in enumerate(zip(solid, temp)):
            g = g + si
            etg = np.minimum(ctg * etg + one_m_ctg * ti, 0.0)
            pot = np.minimum(kf * (ti - MELT_T), g)
            m = (0.9 * np.minimum(g / g_threshold, 1.0) + MIN_MELT_FRAC) * pot
            m = np.where((ti > MELT_T) & (etg == 0.0), m, 0.0)
            melt[i] = m
            g = g - m
            pack[i] = g
        return melt.T, pack.T
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


# --- elevation layers ------------------------------------------------------


def layer_elevations(hypso, n_layers: int) -> np.ndarray:
    """Elevations (m) of ``n_layers`` equal-area layers from a 101-value hypsometric curve.

    airGR rule (``CreateInputsModel``): see the module docstring. ``n_layers`` in 1..100.
    """
    h = np.asarray(hypso, dtype=float)
    if h.shape != (HYPSO_POINTS,):
        raise ValueError(f"the hypsometric curve needs {HYPSO_POINTS} values, got shape {h.shape}")
    if not 1 <= n_layers <= HYPSO_POINTS - 1:
        raise ValueError("n_layers must be between 1 and 100")
    nmoy, nreste = (HYPSO_POINTS - 1) // n_layers, (HYPSO_POINTS - 1) % n_layers
    out, ncont = [], 0
    for _ in range(n_layers):
        if nreste > 0:
            nn = nmoy + 1
            nreste -= 1
        else:
            nn = nmoy
        if nn == 1:
            z = h[ncont]
        elif nn == 2:
            z = 0.5 * (h[ncont] + h[ncont + 1])
        else:
            z = h[int(ncont + nn / 2)]
        out.append(z)
        ncont += nn
    return np.array(out, dtype=float)


def extrapolate_layers(
    precip,
    temp,
    z_layers,
    z_input: float,
    grad_p: float = GRAD_P,
    grad_t: float = GRAD_T,
    z_threshold: float = Z_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray]:
    """Precipitation and temperature of each layer, ``(P_layers, T_layers)`` of shape ``(L, n)``.

    Precipitation: airGR ``DataAltiExtrapolation_Valery`` branches, then rescaled each day so that the
    layer mean equals the input (0/0 -> 0). Temperature: constant lapse rate ``grad_t`` (degC/m).
    A single layer is returned unchanged (no extrapolation: it sits at ``z_input``).
    """
    p = np.asarray(precip, dtype=float)
    t = np.asarray(temp, dtype=float)
    z = np.atleast_1d(np.asarray(z_layers, dtype=float))
    if z.size == 1:
        return p[None, :].copy(), t[None, :].copy()
    factor = np.empty(z.size)
    for i, zl in enumerate(z.tolist()):
        if zl <= z_threshold:
            expo = zl - z_input if z_input <= z_threshold else zl - z_threshold
        else:
            expo = z_threshold - z_input if z_input <= z_threshold else 0.0
        factor[i] = math.exp(grad_p * expo)
    p_l = p[None, :] * factor[:, None]
    mean = p_l.mean(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        p_l = np.where(mean > 0, p_l / mean * p, 0.0)
    t_l = t[None, :] + ((z_input - z) * grad_t)[:, None]
    return p_l, t_l


def _g_threshold_layers(solid_layers: np.ndarray) -> float:
    """Shared Gthreshold: 0.9 x mean annual solid precipitation, averaged over the layers."""
    return _g_threshold(solid_layers.mean(axis=0))


def _snow_layers_batch(solid_l, temp_l, ctg, kf, g_threshold):
    """CemaNeige on ``L`` layers for ``k`` parameter sets: ``melt``, ``pack`` of shape ``(L, k, n)``."""
    n_layers, n = solid_l.shape
    k = ctg.size
    cols_s = np.repeat(solid_l.T, k, axis=1)  # (n, L*k): column l*k + j = layer l, set j
    cols_t = np.repeat(temp_l.T, k, axis=1)
    melt, pack = _snow_batch(
        cols_s, cols_t, np.tile(ctg, n_layers), np.tile(kf, n_layers), g_threshold
    )
    return melt.reshape(n_layers, k, n), pack.reshape(n_layers, k, n)


def _layers_inputs(layers: LayerSpec, precip, temp):
    return extrapolate_layers(
        precip, temp, layers.z_layers, layers.z_input, layers.grad_p, layers.grad_t,
        layers.z_threshold,
    )  # fmt: skip


def cemaneige_layers(precip_l, temp_l, ctg: float, kf: float, g_threshold: float | None = None):
    """CemaNeige on every layer (``(L, n)`` inputs). Returns ``(liquid, solid, melt, snowpack)``.

    ``liquid`` is the basin mean (n,) of rain + melt; the others are per layer ``(L, n)``.
    """
    p = np.asarray(precip_l, dtype=float)
    t = np.asarray(temp_l, dtype=float)
    solid = p * _solid_fraction(t)
    gt = _g_threshold_layers(solid) if g_threshold is None else max(g_threshold, 1e-6)
    melt, pack = _snow_layers_batch(solid, t, np.array([ctg], float), np.array([kf], float), gt)
    liquid = (p - solid + melt[:, 0]).mean(axis=0)
    return liquid, solid, melt[:, 0], pack[:, 0]


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


def _simulate_batch(
    params, precip, temp, pet, s0, r0, layers: LayerSpec | None = None
) -> SimResult:
    """``params`` is (k, 6) in ``Params`` order; every output is (k, n).

    With ``layers`` CemaNeige runs per elevation layer; ``snowpack`` and ``melt`` are basin means.
    """
    x1, x2, x3, x4, ctg, kf = (params[:, i] for i in range(6))
    if layers is None:
        solid = precip * _solid_fraction(temp)
        melt, pack = _snow_batch(solid, temp, ctg, kf, _g_threshold(solid))
        liquid = (precip - solid)[None, :] + melt
    else:
        res = _simulate_layers_batch(params, precip, temp, pet, s0, r0, layers)
        return res[0]
    g = _gr4j_batch(liquid, pet, x1, x2, x3, x4, s0, r0)
    return SimResult(*g, snowpack=pack, melt=melt)


def _simulate_layers_batch(params, precip, temp, pet, s0, r0, layers: LayerSpec):
    """Returns ``(SimResult, p_l, t_l, solid_l, melt_l (L,k,n), pack_l (L,k,n))``."""
    x1, x2, x3, x4, ctg, kf = (params[:, i] for i in range(6))
    p_l, t_l = _layers_inputs(layers, precip, temp)
    solid_l = p_l * _solid_fraction(t_l)
    melt_l, pack_l = _snow_layers_batch(solid_l, t_l, ctg, kf, _g_threshold_layers(solid_l))
    liquid = ((p_l - solid_l)[:, None, :] + melt_l).mean(axis=0)
    g = _gr4j_batch(liquid, pet, x1, x2, x3, x4, s0, r0)
    sim = SimResult(*g, snowpack=pack_l.mean(axis=0), melt=melt_l.mean(axis=0))
    return sim, p_l, t_l, solid_l, melt_l, pack_l


def simulate(
    params: Params, precip, temp, pet, s0: float = 0.3, r0: float = 0.5,
    layers: LayerSpec | None = None,
) -> SimResult:  # fmt: skip
    """CemaNeige -> GR4J. Returns flow (mm/d) and the internal fluxes and stores.

    ``layers=None`` is the single-layer model; with a ``LayerSpec`` CemaNeige runs per elevation layer
    (``snowpack`` and ``melt`` are then basin means; see ``simulate_layers`` for the per-layer series).
    """
    x = np.array([tuple(Params(*params))], dtype=float)
    res = _simulate_batch(
        x,
        np.asarray(precip, dtype=float),
        np.asarray(temp, dtype=float),
        np.asarray(pet, dtype=float),
        s0,
        r0,
        layers,
    )
    return SimResult(*(a[0] for a in res))


def simulate_layers(
    params: Params, precip, temp, pet, layers: LayerSpec, s0: float = 0.3, r0: float = 0.5
) -> LayerSimResult:
    """Like ``simulate`` with layers, also returning the per-layer series ``(L, n)``."""
    x = np.array([tuple(Params(*params))], dtype=float)
    sim, p_l, t_l, solid_l, melt_l, pack_l = _simulate_layers_batch(
        x,
        np.asarray(precip, float),
        np.asarray(temp, float),
        np.asarray(pet, float),
        s0,
        r0,
        layers,
    )
    return LayerSimResult(
        SimResult(*(a[0] for a in sim)), p_l, t_l, solid_l, melt_l[:, 0], pack_l[:, 0]
    )


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
    layers: LayerSpec | None = None,
) -> Calibration:
    """Calibrate ``Params`` by maximising KGE with differential evolution (fixed ``seed``).

    Only days at or after ``warmup`` with a valid ``qobs`` are scored. Default bounds: x1 [1, 3000] mm,
    x2 [-10, 10] mm/d, x3 [1, 1000] mm, x4 [0.5, 10] d, CTG [0, 1], Kf [0, 20] mm/degC/d. The population
    is evaluated in one vectorised pass per generation. No local polish (it costs as much again as the
    whole search). Caveat: GR4J has a local optimum with a small x1 and a strongly negative x2; DE can
    land there for some seeds (KGE ~0.98 instead of ~1.0 on noise-free synthetic data). The result is
    deterministic for a given ``seed``; for important runs compare a few seeds and keep the best.
    ``layers`` runs CemaNeige on elevation layers (all layers share CTG and Kf); the population is
    still one vectorised pass (parameters are tiled over the layers).
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
        q = _simulate_batch(x.T, precip, temp, pet, 0.3, 0.5, layers).q[:, scored]
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

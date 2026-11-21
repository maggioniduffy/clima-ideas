"""SCS-CN peak discharge for small catchments (F4.2, plan/04-debris-flows.md).

Pure functions, SI units (mm, m, km2, h, m3/s).

- Runoff depth (NRCS NEH-4 ch.10 / TR-55 ch.2): ``Q = (P - Ia)^2 / (P - Ia + S)`` with ``S = 25400/CN - 254`` mm
  and ``Ia = 0.2 S``. The 0.2 ratio is the standard default, not calibrated for Neuquén (sin verificar locally).
- Time of concentration: SCS lag method (NEH-4 ch.15, also TR-55; equation number sin verificar):
  ``Tl = L^0.8 (S' + 1)^0.7 / (1900 Y^0.5)`` with L in ft, ``S' = 1000/CN - 10`` in, Y mean slope in %,
  and ``Tc = Tl / 0.6``. Chosen over Kirpich because it uses the same CN as the runoff step and keeps the whole
  chain on one manual; Kirpich was calibrated on small agricultural basins in Tennessee and Pennsylvania.
  Neither formula is validated for Patagonian badlands (sin verificar).
- Peak: SCS dimensionless triangular unit hydrograph, ``qp = 0.208 A Q / Tp`` (A km2, Q mm, Tp h, qp m3/s),
  with ``Tp = D/2 + Tl`` (D = rainfall duration). The rain is treated as one uniform pulse of duration D
  (simplification: no storm hyetograph, no routing, no channel losses).

The CN itself is an input: no CN map for Neuquén is bundled here. Where it comes from (soil/land cover, F0.8)
must be stated next to every result that uses it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

IA_RATIO = 0.2
PEAK_RATE_CONSTANT = 0.208  # SI: A km2, Q mm, Tp h -> m3/s
LAG_TO_TC = 0.6  # Tl = 0.6 Tc
M_TO_FT = 3.280839895
SOURCE = "SCS-CN (NRCS NEH-4 ch.10 and 15; TR-55) sobre lluvias de diseño IDF solo con IMERG (F3.3)"


def retention_mm(cn: float) -> float:
    """Potential maximum retention S (mm) = 25400/CN - 254."""
    if not 0 < cn <= 100:
        raise ValueError(f"CN must be in (0, 100], got {cn}")
    return 25400.0 / cn - 254.0


def runoff_depth_mm(p_mm: float, cn: float, ia_ratio: float = IA_RATIO) -> float:
    """Direct runoff depth Q (mm) for rainfall depth `p_mm`; 0 when P <= Ia."""
    s = retention_mm(cn)
    ia = ia_ratio * s
    if p_mm <= ia:
        return 0.0
    return (p_mm - ia) ** 2 / (p_mm - ia + s)


def scs_lag_h(length_m: float, cn: float, slope_pct: float) -> float:
    """SCS lag time Tl (h) from longest flow path (m), CN and mean catchment slope (%)."""
    if length_m <= 0 or slope_pct <= 0:
        raise ValueError("length_m and slope_pct must be positive")
    l_ft = length_m * M_TO_FT
    s_in = 1000.0 / cn - 10.0
    return l_ft**0.8 * (s_in + 1.0) ** 0.7 / (1900.0 * slope_pct**0.5)


def time_of_concentration_h(length_m: float, cn: float, slope_pct: float) -> float:
    """Tc = Tl / 0.6 (h)."""
    return scs_lag_h(length_m, cn, slope_pct) / LAG_TO_TC


def peak_discharge_m3s(
    area_km2: float, cn: float, p_mm: float, duration_h: float, lag_h: float
) -> float:
    """Peak discharge (m3/s) for one rainfall depth `p_mm` of duration `duration_h`."""
    q = runoff_depth_mm(p_mm, cn)
    if q == 0.0:
        return 0.0
    tp = duration_h / 2.0 + lag_h
    return PEAK_RATE_CONSTANT * area_km2 * q / tp


@dataclass(frozen=True)
class DesignPeak:
    return_period: float
    critical_duration_h: float
    depth_mm: float
    runoff_mm: float
    peak_m3s: float


def design_peaks(
    area_km2: float,
    cn: float,
    length_m: float,
    slope_pct: float,
    rains: Mapping[tuple[float, float], float],
) -> list[DesignPeak]:
    """Peak per return period; `rains[(return_period, duration_h)] = depth_mm`.

    For each return period the duration giving the largest peak is reported (critical duration).
    """
    lag = scs_lag_h(length_m, cn, slope_pct)
    best: dict[float, DesignPeak] = {}
    for (rp, dur), depth in sorted(rains.items()):
        peak = peak_discharge_m3s(area_km2, cn, depth, dur, lag)
        cand = DesignPeak(rp, dur, depth, runoff_depth_mm(depth, cn), peak)
        if rp not in best or cand.peak_m3s > best[rp].peak_m3s:
            best[rp] = cand
    return [best[k] for k in sorted(best)]

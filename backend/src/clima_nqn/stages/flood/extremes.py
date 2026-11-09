"""Annual flow maxima and GEV return levels (plan/02, F2.2).

Conventions:
- Annual maxima are block maxima of the daily mean flow per hydrological year (labelled by its start
  year, April start for the Neuquén stations). Years with fewer than ``MIN_VALID_DAYS`` valid days are
  excluded and listed separately (assumption S5, not from SNIH).
- The GEV is fitted by maximum likelihood with ``pyextremes`` (``MLE`` model, scipy ``genextreme``).
  One block per year, so the return period T of a level is the inverse of its yearly exceedance
  probability: ``p = 1 / T``.
- Shape sign convention: scipy ``genextreme`` uses ``c = -xi``. We report both. ``xi > 0`` (``c < 0``)
  is the heavy (Frechet) tail, ``xi < 0`` (``c > 0``) is bounded above (Weibull), ``xi = 0`` Gumbel.
- Confidence intervals are the pyextremes bootstrap (resampling the annual maxima with replacement, refit,
  percentiles of the resampled return levels) (``alpha = 0.95``, the interval width in pyextremes) with
  ``N_SAMPLES`` resamples and a fixed seed. pyextremes draws from numpy's global generator, so the
  seed is set right before the bootstrap (the split of resamples across CPU cores can still shift the CI
  by a little between machines).
- Empirical return period uses the Weibull plotting position ``T = (n + 1) / rank`` (rank 1 = largest).
- Goodness of fit: one-sample Kolmogorov-Smirnov test against the fitted GEV. The parameters come
  from the same data, so the p-value is optimistic; read it as a coarse check, not a proof.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from pyextremes.models import get_model
from scipy.stats import genextreme, kstest

from clima_nqn.io import flow
from clima_nqn.stages.ar.extremes import _clean

RETURN_PERIODS = (2, 5, 10, 25, 50, 100)
N_SAMPLES = 1000
SEED = 20260509
CI_WIDTH = 0.95  # pyextremes' ``alpha`` is the width of the interval, not the tail probability
# Natural stations upstream of the dams. 11803 Paso Flores is regulated (record starts 2006, after
# Alicurá; its position vs. the dam is sin verificar) and stays out of the GEV.
DEFAULT_STATIONS = (12004, 12010, 12012)
EXCLUDED_NOTE = (
    "11803 Paso Flores excluido: regulado (registro desde 2006, posterior a Alicurá); "
    "su posición respecto de la presa es sin verificar."
)
GEV_DIR = flow.OUT_DIR / "gev"
REPORT_PATH = Path(__file__).resolve().parents[5] / "reports" / "02" / "F2.2.md"


# --- annual maxima -------------------------------------------------------------------------


def annual_maxima(
    df: pd.DataFrame, start_month: int = 4, min_valid: int = flow.MIN_VALID_DAYS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Max daily flow per complete hydrological year and the excluded (incomplete) years.

    Returns ``(maxima, excluded)``: ``maxima`` has ``hydro_year``, ``date``, ``q_m3s``, ``valid_days``;
    ``excluded`` has ``hydro_year``, ``valid_days``.
    """
    comp = flow.hydro_year_completeness(df, start_month, min_valid)
    valid = df.dropna(subset=["q_m3s"])
    year = np.where(
        valid["date"].dt.month >= start_month, valid["date"].dt.year, valid["date"].dt.year - 1
    )
    idx = valid["q_m3s"].groupby(year).idxmax()
    peaks = valid.loc[idx.to_numpy(), ["date", "q_m3s"]].copy()
    peaks.insert(0, "hydro_year", idx.index.astype(int))
    peaks = peaks.merge(comp[["hydro_year", "valid_days", "complete"]], on="hydro_year")
    done = peaks["complete"]
    maxima = peaks.loc[done, ["hydro_year", "date", "q_m3s", "valid_days"]].reset_index(drop=True)
    excluded = comp.loc[~comp["complete"], ["hydro_year", "valid_days"]].reset_index(drop=True)
    return maxima, excluded


def empirical_return_period(values: np.ndarray) -> np.ndarray:
    """Weibull plotting position ``T = (n + 1) / rank`` (rank 1 = largest), in input order."""
    values = np.asarray(values, dtype=float)
    rank = (-values).argsort(kind="stable").argsort(kind="stable") + 1
    return (len(values) + 1) / rank


# --- GEV -----------------------------------------------------------------------------------

MAX_XI = (
    1.0  # fits with xi >= 1 are rejected: the likelihood is unbounded there (degenerate spikes)
)
IRREGULAR_XI = 0.5  # the MLE is regular only for xi < 0.5; above it the CI is unreliable
_START_SHAPES = (-0.2, 0.0, 0.2)  # scipy c = -xi: heavy, Gumbel, bounded


class _MultiStartGEV(type(genextreme)):  # public base: scipy's private module path may move
    """``genextreme`` whose MLE tries several shape starting values and keeps the best likelihood.

    scipy's default start can stall far from the optimum: on 2000 synthetic points with c = 0.2 it
    returns loc = 193, scale = 3. Each start here also seeds loc and scale from the Gumbel moments.
    Candidates with xi >= ``MAX_XI`` are discarded; if none remains, the shape is pinned at
    xi = ``MAX_XI`` - 0.01 and only loc and scale are fitted (it shows as xi = 0.99 in the output).
    """

    def _try_fit(self, data, c0, **kwargs):
        data = np.asarray(data, dtype=float)
        scale0 = max(float(np.std(data)) * math.sqrt(6) / math.pi, 1e-9)  # Gumbel moments
        loc0 = float(np.mean(data)) - 0.5772 * scale0
        try:
            return super().fit(data, c0, **{"loc": loc0, "scale": scale0, **kwargs})
        except (RuntimeError, ValueError, FloatingPointError):  # a start that does not converge
            return None

    def fit(self, data, *args, **kwargs):
        if args:  # explicit starting values: defer to scipy
            return super().fit(data, *args, **kwargs)
        best, best_ll = None, -math.inf
        for c0 in _START_SHAPES:
            params = self._try_fit(data, c0, **kwargs)
            if params is None or params[0] <= -MAX_XI:  # xi >= 1: unbounded likelihood, not a fit
                continue
            ll = float(np.sum(self.logpdf(data, *params)))
            if np.isfinite(ll) and ll > best_ll:
                best, best_ll = params, ll
        if best is None:
            # no regular optimum: fit loc and scale with the shape pinned just inside the bound
            c_fixed = -(MAX_XI - 0.01)
            if "f0" in kwargs:
                raise RuntimeError("GEV maximum-likelihood fit did not converge from any start")
            return super().fit(data, f0=c_fixed, **kwargs)
        return best


GEV = _MultiStartGEV(name="genextreme")


def fit_gev(
    maxima: pd.Series,
    return_periods: Sequence[int] = RETURN_PERIODS,
    n_samples: int = N_SAMPLES,
    seed: int = SEED,
    ci_width: float = CI_WIDTH,
) -> dict:
    """MLE GEV fit (pyextremes) of a series of annual maxima, with bootstrap CI of the return levels.

    Shape is reported as ``shape_xi`` (xi > 0 heavy tail) and ``shape_c_scipy`` (= -xi).
    """
    series = pd.Series(np.asarray(maxima, dtype=float), index=pd.DatetimeIndex(maxima.index))
    model = get_model("MLE", extremes=series.sort_index(), distribution=GEV)
    params = model.fit_parameters
    c, loc, scale = float(params["c"]), float(params["loc"]), float(params["scale"])
    np.random.seed(seed)  # pyextremes bootstraps with numpy's global generator
    periods = np.asarray(return_periods, dtype=float)
    value, low, high = model.get_return_value(1.0 / periods, alpha=ci_width, n_samples=n_samples)
    ks = kstest(series.to_numpy(), genextreme(c, loc=loc, scale=scale).cdf)
    return {
        "loc": loc,
        "scale": scale,
        "shape_xi": -c,
        "shape_c_scipy": c,
        "n": len(series),
        "n_samples": n_samples,
        "seed": seed,
        "ci_level": ci_width,
        "ks_statistic": float(ks.statistic),
        "ks_pvalue": float(ks.pvalue),
        "return_levels": [
            {
                "return_period": int(t),
                "value": float(v),
                "ci95_low": float(lo),
                "ci95_high": float(hi),
            }
            for t, v, lo, hi in zip(return_periods, value, low, high, strict=True)
        ],
    }


def gev_return_period(value: float, fit: dict) -> float:
    """Return period (years) of ``value`` under the fitted GEV."""
    sf = genextreme(fit["shape_c_scipy"], loc=fit["loc"], scale=fit["scale"]).sf(value)
    return math.inf if sf <= 0 else float(1.0 / sf)


# --- station -------------------------------------------------------------------------------


def station_result(df: pd.DataFrame, meta: dict, n_samples: int = N_SAMPLES, top: int = 5) -> dict:
    """Annual maxima + GEV of one station; the dict that is written to JSON."""
    maxima, excluded = annual_maxima(df, meta.get("hydro_year_start_month", 4))
    if len(maxima) < 10:
        raise ValueError(
            f"station {meta['id']}: only {len(maxima)} complete years, too few for a GEV"
        )
    fit = fit_gev(pd.Series(maxima["q_m3s"].to_numpy(), index=maxima["date"]), n_samples=n_samples)
    emp = empirical_return_period(maxima["q_m3s"].to_numpy())
    rows = [
        {
            "hydro_year": int(y),
            "date": d.strftime("%Y-%m-%d"),
            "q_m3s": float(q),
            "valid_days": int(v),
            "empirical_T": float(t),
            "gev_T": gev_return_period(float(q), fit),
        }
        for y, d, q, v, t in zip(
            maxima["hydro_year"],
            maxima["date"],
            maxima["q_m3s"],
            maxima["valid_days"],
            emp,
            strict=True,
        )
    ]
    rows.sort(key=lambda r: -r["q_m3s"])
    valid = df.dropna(subset=["q_m3s"])
    return {
        "station_id": int(meta["id"]),
        "name": meta.get("name"),
        "river": meta.get("river"),
        "area_km2": meta.get("area_km2"),
        "hydro_year_start_month": meta.get("hydro_year_start_month", 4),
        "min_valid_days": flow.MIN_VALID_DAYS,
        "source": df.attrs.get("source", flow.SOURCE),
        "url": df.attrs.get("url", flow.SNIH_URL),
        "fetched": df.attrs.get("fetched"),
        "period": f"{valid['date'].min():%Y-%m-%d}/{valid['date'].max():%Y-%m-%d}",
        "n_years": len(maxima),
        "years_used": [int(y) for y in maxima["hydro_year"]],
        "excluded_years": [
            {"hydro_year": int(y), "valid_days": int(v)}
            for y, v in zip(excluded["hydro_year"], excluded["valid_days"], strict=True)
        ],
        "top": top,
        "gev": fit,
        "annual_maxima": rows,
    }


def _finite(obj):
    """Non-finite floats (e.g. gev_T = inf beyond the fitted support) -> None, for strict JSON."""
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_finite(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def write_station_json(result: dict, out_dir: Path | str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result['station_id']}.json"
    text = json.dumps(_finite(_clean(result)), indent=2, ensure_ascii=False, allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return path


# --- report --------------------------------------------------------------------------------


def _n(x: float, nd: int = 0) -> str:
    return (
        "n/d"
        if x is None or (isinstance(x, float) and math.isnan(x))
        else f"{x:,.{nd}f}".replace(",", " ")
    )


def _t(x: float | None) -> str:
    return "> 10 000" if x is None or x > 10_000 else _n(x, 1)


def build_report(results: list[dict]) -> str:
    lines = [
        "# F2.2 — Máximos anuales y GEV con intervalo de confianza",
        "",
        (
            "Retrospectivo: niveles de retorno de la distribución ajustada a los máximos anuales; no es un pronóstico ni "
            "un sistema de alerta."
        ),
        "",
        "## Fuente y método",
        "",
        f"- Fuente: {flow.SOURCE} ({flow.SNIH_URL}); caudal medio diario (m³/s). Citar al SIPH/SNIH.",
        (
            "- Máximo anual: caudal medio diario máximo por año hidrológico (inicio en abril, etiquetado por el año de "
            f"inicio). Año completo = al menos {flow.MIN_VALID_DAYS} días válidos (supuesto, no del SNIH); los demás "
            "se excluyen y se listan abajo."
        ),
        (
            "- Ajuste: GEV por máxima verosimilitud (`pyextremes`, modelo `MLE` sobre `scipy.stats.genextreme`), un bloque "
            "por año, T = 1/p."
        ),
        f"- IC 95 %: bootstrap no paramétrico de `pyextremes` (remuestreo con reemplazo de los máximos, reajuste, percentiles 2,5 y 97,5) con {N_SAMPLES} remuestreos y semilla fija ({SEED}); el reparto entre núcleos de CPU puede cambiar los extremos del IC en la última cifra.",
        (
            "- Convención de la forma: scipy usa c = −ξ. ξ > 0 (c < 0) es cola pesada; ξ < 0 (c > 0) está acotada "
            "por arriba; ξ = 0 es Gumbel. Se informa ξ."
        ),
        "- Período empírico: posición de Weibull T = (n + 1) / rango (rango 1 = el mayor).",
        (
            "- Bondad de ajuste: test de Kolmogorov-Smirnov contra la GEV ajustada; como los parámetros salen de los "
            "mismos datos, el valor p es optimista (control grueso)."
        ),
        "",
        "## Supuestos y salvedades",
        "",
        "- Estacionariedad: no se modela tendencia ni covariable. El efecto de ENSO queda para F2.7.",
        (
            "- Los niveles de retorno de períodos largos (50, 100 años) extrapolan más allá del registro; el IC lo refleja "
            "solo en parte (remuestrea los mismos años y supone que la GEV es el modelo correcto)."
        ),
        f"- {EXCLUDED_NOTE}",
        "- 12013 Chos Malal y 11804 Paso Limay no devolvieron datos en el SNIH (F2.1).",
        "- El calificador `D` en 12010 (336 filas) tiene significado sin verificar.",
        "",
    ]
    for r in results:
        g = r["gev"]
        lines += [
            f"## {r['station_id']} {r['name']} ({r['river']})",
            "",
            f"- Período con datos: {r['period']}; última consulta: {r['fetched']}.",
            f"- Años completos usados: {r['n_years']}; excluidos por incompletos: {len(r['excluded_years'])}"
            + (
                " ("
                + ", ".join(f"{e['hydro_year']}: {e['valid_days']} d" for e in r["excluded_years"])
                + ")"
                if r["excluded_years"]
                else ""
            )
            + ".",
            (
                f"- Parámetros GEV: ubicación {_n(g['loc'], 1)} m³/s, escala {_n(g['scale'], 1)} m³/s, "
                f"forma ξ = {g['shape_xi']:.3f} (c scipy = {g['shape_c_scipy']:.3f})."
            ),
            *(
                [
                    (
                        "- Aviso: ξ ≥ 0,5; el estimador de máxima verosimilitud no es regular en ese rango y el IC "
                        "es poco fiable."
                    )
                ]
                if g["shape_xi"] >= IRREGULAR_XI
                else []
            ),
            f"- Kolmogorov-Smirnov: D = {g['ks_statistic']:.3f}, p = {g['ks_pvalue']:.2f} (optimista).",
            "",
            "| T (años) | Nivel de retorno (m³/s) | IC 95 % (m³/s) |",
            "|---|---|---|",
            *[
                f"| {x['return_period']} | {_n(x['value'])} | {_n(x['ci95_low'])} – {_n(x['ci95_high'])} |"
                for x in g["return_levels"]
            ],
            "",
            f"Cinco mayores máximos anuales (n = {r['n_years']}):",
            "",
            "| Año hidrológico | Fecha | Caudal (m³/s) | T empírico (años) | T según GEV (años) |",
            "|---|---|---|---|---|",
            *[
                f"| {m['hydro_year']} | {m['date']} | {_n(m['q_m3s'])} | {_n(m['empirical_T'], 1)} | "
                f"{_t(m['gev_T'])} |"
                for m in r["annual_maxima"][: r["top"]]
            ],
            "",
        ]
    return "\n".join(lines)


def write_report(text: str, path: Path | str = REPORT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- entry point ---------------------------------------------------------------------------


def run(
    flow_dir: Path | str = flow.OUT_DIR,
    out_dir: Path | str = GEV_DIR,
    report: Path | str = REPORT_PATH,
    stations: Sequence[int] | None = None,
    n_samples: int = N_SAMPLES,
) -> list[dict]:
    """GEV of each station (default: the natural ones) -> ``<out>/<id>.json`` and the report."""
    flow_dir = Path(flow_dir)
    meta_all = {
        s["id"]: s for s in json.loads((flow_dir / "stations.json").read_text())["stations"]
    }
    results = []
    for sid in stations or DEFAULT_STATIONS:
        df = flow.read_flow(flow_dir / f"{sid}.parquet")
        res = station_result(df, meta_all[sid], n_samples=n_samples)
        write_station_json(res, out_dir)
        results.append(res)
    write_report(build_report(results), report)
    return results

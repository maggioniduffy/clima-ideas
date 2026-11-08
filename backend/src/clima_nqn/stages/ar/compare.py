"""Agreement between AR detectors over the Neuquén cordillera polygon (plan/01, F1.7).

Three methods are compared at the 6-hourly ERA5 steps they share:

- BARD (TECA, the reference detector of this project): AR step when any polygon cell has
  ``ar_probability >= threshold`` (same rule as the catalog: :func:`catalog.ar_steps`).
- ClimateNet (pretrained CGNet, ML): AR step when any polygon cell of its own grid is in the AR class.
- IVT baseline: AR step when any polygon cell has IVT >= 250 kg m-1 s-1 (the simple baseline next to the ML model).

Pairs are (candidate, reference). BARD is a reference for convenience, not ground truth: no method is. Metrics on
the step flags: contingency table, hit rate (hits / reference AR steps), false alarm ratio (candidate AR steps the
reference does not flag / candidate AR steps), Cohen's kappa and the Jaccard index of the AR step sets. Cell level:
IoU of the polygon cells flagged, on steps where either method flags (ClimateNet and IVT cells are mapped to the
BARD grid by nearest neighbour), pooled over steps and as the mean of per-step IoU. Season by month of the step
(southern hemisphere: DJF verano, MAM otoño, JJA invierno, SON primavera).

Run: ``python -m clima_nqn.stages.ar.compare --bard-dir D --climatenet-dir D --ivt-dir D --out-dir D``
(directories are searched recursively, so unpacked artifact folders work).
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.stages.ar import catalog

METHODS = {
    "bard": "BARD",
    "climatenet": "ClimateNet",
    "ivt": "IVT ≥ 250",
}
FILE_PREFIX = {
    "bard": "bard_neuquen",
    "climatenet": "climatenet_neuquen",
    "ivt": "ivt_threshold_neuquen",
}
# (candidate, reference)
PAIRS = (("climatenet", "bard"), ("ivt", "bard"), ("climatenet", "ivt"))
SEASONS = {
    "DJF": "verano (DJF)",
    "MAM": "otoño (MAM)",
    "JJA": "invierno (JJA)",
    "SON": "primavera (SON)",
}
_SEASON_OF_MONTH = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM"}
_SEASON_OF_MONTH.update({6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"})
IVT_THRESHOLD = 250.0
CAVEATS = [
    (
        "ClimateNet se entrenó, según la descripción del proyecto, con salida del modelo climático CAM5 y etiquetas de expertos (artículo GMD 14, 107, 2021 que "
        "enlaza el README; no se leyó acá, sin verificar); aplicarlo a ERA5 es un cambio de dominio: no se evaluó acá cuánto "
        "degrada la detección."
    ),
    (
        "ClimateNet corre en otra grilla (interpolada bilineal desde 0,25° a la grilla del modelo) que BARD e IVT; los "
        "pasos se comparan con 'alguna celda del polígono' y las celdas con vecino más cercano sobre la grilla de BARD."
    ),
    "Ningún método es la verdad: el acuerdo mide qué tan parecidas son las definiciones, no cuál acierta.",
    (
        "El polígono de cordillera es una aproximación sin verificar; el umbral 0,67 de BARD y los 250 kg m-1 s-1 de "
        "IVT son convenciones, y otros valores cambian los números."
    ),
    "Es un análisis retrospectivo de acuerdo entre detectores, no un sistema de alerta.",
]


# --- agreement metrics ---------------------------------------------------------------------


def contingency(a: np.ndarray, b: np.ndarray) -> dict[str, int]:
    """2x2 counts of boolean step flags: ``n11`` both, ``n10`` only a, ``n01`` only b, ``n00`` neither."""
    a, b = np.asarray(a, dtype=bool), np.asarray(b, dtype=bool)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch {a.shape} vs {b.shape}")
    return {
        "n11": int((a & b).sum()),
        "n10": int((a & ~b).sum()),
        "n01": int((~a & b).sum()),
        "n00": int((~a & ~b).sum()),
    }


def _ratio(num: float, den: float) -> float:
    return num / den if den else math.nan


def kappa_from(c: dict[str, int]) -> float:
    """Cohen's kappa of a contingency table; NaN when chance agreement is 1 (a constant flag on both sides)."""
    n = c["n11"] + c["n10"] + c["n01"] + c["n00"]
    if n == 0:
        return math.nan
    po = (c["n11"] + c["n00"]) / n
    pa1, pb1 = (c["n11"] + c["n10"]) / n, (c["n11"] + c["n01"]) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return (po - pe) / (1 - pe) if pe < 1 else math.nan


def cell_iou(cells_a: np.ndarray, cells_b: np.ndarray) -> dict:
    """IoU of flagged cells (steps x cells, boolean) on steps where either flags any cell.

    ``iou_pooled``: sum of intersections / sum of unions over those steps; ``iou_mean``: mean of per-step IoU;
    ``n_steps``: number of such steps. NaN when no step has a flagged cell.
    """
    a, b = np.asarray(cells_a, dtype=bool), np.asarray(cells_b, dtype=bool)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch {a.shape} vs {b.shape}")
    inter = (a & b).sum(axis=1)
    union = (a | b).sum(axis=1)
    keep = union > 0
    if not keep.any():
        return {"iou_pooled": math.nan, "iou_mean": math.nan, "n_steps": 0}
    return {
        "iou_pooled": float(inter[keep].sum() / union[keep].sum()),
        "iou_mean": float((inter[keep] / union[keep]).mean()),
        "n_steps": int(keep.sum()),
    }


def agreement(
    a: np.ndarray, b: np.ndarray, cells_a: np.ndarray | None = None, cells_b=None
) -> dict:
    """All metrics of candidate ``a`` vs reference ``b`` (step flags, optional cell masks)."""
    c = contingency(a, b)
    out = {
        **c,
        "n": sum(c.values()),
        "hit_rate": _ratio(c["n11"], c["n11"] + c["n01"]),
        "false_alarm_ratio": _ratio(c["n10"], c["n11"] + c["n10"]),
        "kappa": kappa_from(c),
        "jaccard": _ratio(c["n11"], c["n11"] + c["n10"] + c["n01"]),
    }
    if cells_a is not None and cells_b is not None:
        out.update(cell_iou(cells_a, cells_b))
    return out


def season_of(times: pd.DatetimeIndex) -> np.ndarray:
    return np.array([_SEASON_OF_MONTH[m] for m in pd.DatetimeIndex(times).month])


def compare_series(
    flags: dict[str, np.ndarray],
    cells: dict[str, np.ndarray],
    times: pd.DatetimeIndex,
    pairs: Sequence[tuple[str, str]] = PAIRS,
) -> dict:
    """Per-method AR step counts and per-pair agreement, overall and by season, on aligned steps."""
    seasons = season_of(times)
    groups = {"all": np.ones(len(times), dtype=bool), **{s: seasons == s for s in SEASONS}}
    methods = {}
    for name, f in flags.items():
        methods[name] = {
            g: {
                "n_steps": int(sel.sum()),
                "n_ar_steps": int(f[sel].sum()),
                "ar_step_rate": _ratio(f[sel].sum(), sel.sum()),
            }
            for g, sel in groups.items()
        }
    out_pairs = {}
    for cand, ref in pairs:
        out_pairs[f"{cand}_vs_{ref}"] = {
            "candidate": cand,
            "reference": ref,
            **{
                g: agreement(flags[cand][sel], flags[ref][sel], cells[cand][sel], cells[ref][sel])
                for g, sel in groups.items()
            },
        }
    return {"methods": methods, "pairs": out_pairs}


# --- loading -------------------------------------------------------------------------------


def find_year_files(directory: Path | str, prefix: str) -> dict[int, Path]:
    """``<prefix>_<year>.nc`` files below ``directory`` (recursive), keyed by year."""
    found = {}
    for path in sorted(Path(directory).rglob(f"{prefix}_*.nc")):
        m = re.fullmatch(rf"{re.escape(prefix)}_(\d{{4}})\.nc", path.name)
        if m:
            found[int(m.group(1))] = path
    return found


def _bard_year(path: Path, mask_fn, threshold: float):
    with xr.open_dataset(path) as ds:
        ds = ds[["ar_probability"]].load()
    mask = mask_fn(ds["lat"].values, ds["lon"].values)
    steps = catalog.ar_steps(ds, mask, threshold)  # same rule as the catalog
    inside = mask.transpose("lat", "lon").values
    prob = ds["ar_probability"].transpose("time", "lat", "lon").values[:, inside]
    return (
        steps.set_index("time")["is_ar"],
        prob >= threshold,
        ds["lat"].values,
        ds["lon"].values,
        inside,
    )


def _mask_year(path: Path, mask_fn, ref_lat, ref_lon, ref_inside):
    """Flags on the file's own grid and cells mapped to the BARD grid (nearest neighbour)."""
    with xr.open_dataset(path) as ds:
        da = ds["ar_mask"].transpose("time", "lat", "lon").load()
    own = mask_fn(da["lat"].values, da["lon"].values).transpose("lat", "lon").values
    flag = da.values.astype(bool)[:, own].any(axis=1)
    on_ref = da.sel(lat=ref_lat, lon=ref_lon, method="nearest").values.astype(bool)[:, ref_inside]
    return pd.Series(flag, index=pd.DatetimeIndex(da["time"].values)), on_ref


def read_provenance(path: Path) -> dict:
    """Global attributes of a ClimateNet output file that describe the model."""
    keys = (
        "title",
        "method",
        "model_repo",
        "model_commit",
        "weights_url",
        "weights_sha256",
        "model_grid",
        "source",
    )
    with xr.open_dataset(path) as ds:
        return {k: str(ds.attrs[k]) for k in keys if k in ds.attrs}


def compare_dirs(
    bard_dir,
    climatenet_dir,
    ivt_dir,
    threshold: float = catalog.DEFAULT_THRESHOLD,
    polygon: Sequence[tuple[float, float]] = catalog.CORDILLERA_POLYGON,
) -> tuple[dict, dict]:
    """Compare the years present in all three directories. Returns (results, meta)."""
    files = {
        "bard": find_year_files(bard_dir, FILE_PREFIX["bard"]),
        "climatenet": find_year_files(climatenet_dir, FILE_PREFIX["climatenet"]),
        "ivt": find_year_files(ivt_dir, FILE_PREFIX["ivt"]),
    }
    years = sorted(set.intersection(*(set(f) for f in files.values())))
    if not years:
        raise ValueError(
            "no year is present in all three directories: "
            + json.dumps({k: sorted(v) for k, v in files.items()})
        )

    def mask_fn(lat, lon):
        return catalog.polygon_mask(lat, lon, polygon)

    parts = {k: [] for k in METHODS}
    cell_parts = {k: [] for k in METHODS}
    ref = None
    for year in years:
        bard_flag, bard_cells, lat, lon, inside = _bard_year(
            files["bard"][year], mask_fn, threshold
        )
        ref = ref or (lat, lon, inside)
        if not (np.array_equal(ref[0], lat) and np.array_equal(ref[1], lon)):
            raise ValueError(f"BARD grid of {year} differs from {years[0]}")
        cn_flag, cn_cells = _mask_year(files["climatenet"][year], mask_fn, *ref)
        ivt_flag, ivt_cells = _mask_year(files["ivt"][year], mask_fn, *ref)
        series = {"bard": bard_flag, "climatenet": cn_flag, "ivt": ivt_flag}
        cells = {"bard": pd.DataFrame(bard_cells, index=bard_flag.index)}
        cells["climatenet"] = pd.DataFrame(cn_cells, index=cn_flag.index)
        cells["ivt"] = pd.DataFrame(ivt_cells, index=ivt_flag.index)
        common = bard_flag.index.intersection(cn_flag.index).intersection(ivt_flag.index)
        for k in METHODS:
            parts[k].append(series[k].loc[common])
            cell_parts[k].append(cells[k].loc[common])
    flags = {k: pd.concat(v) for k, v in parts.items()}
    times = flags["bard"].index
    cells = {k: pd.concat(v).values for k, v in cell_parts.items()}
    results = compare_series({k: v.values.astype(bool) for k, v in flags.items()}, cells, times)
    n_cells = int(ref[2].sum())
    meta = {
        "source": "ERA5 via ARCO-ERA5 (CC-BY 4.0); TECA BARD 6.0.0; ClimateNet CGNet (MIT, repo andregraubner/ClimateNet)",
        "period": f"{times.min():%Y-%m-%d}/{times.max():%Y-%m-%d}",
        "years_used": years,
        "years_found": {k: sorted(v) for k, v in files.items()},
        "n_steps": len(times),
        "bard_threshold": threshold,
        "ivt_threshold": IVT_THRESHOLD,
        "polygon": [list(v) for v in polygon],
        "polygon_cells_bard_grid": n_cells,
        "model": read_provenance(files["climatenet"][years[0]]),
        "caveats": CAVEATS,
    }
    return results, meta


# --- report --------------------------------------------------------------------------------


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def _f(x, nd: int = 2) -> str:
    return (
        "n/d"
        if x is None or (isinstance(x, float) and math.isnan(x))
        else f"{x:.{nd}f}".replace(".", ",")
    )


def _pair_title(p: dict) -> str:
    return f"{METHODS[p['candidate']]} (candidato) vs. {METHODS[p['reference']]} (referencia)"


def _pair_row(label: str, m: dict) -> str:
    return (
        f"| {label} | {m['n11']} | {m['n10']} | {m['n01']} | {m['n00']} | {_f(m['hit_rate'])} | "
        f"{_f(m['false_alarm_ratio'])} | {_f(m['kappa'])} | {_f(m['jaccard'])} | "
        f"{_f(m['iou_pooled'])} / {_f(m['iou_mean'])} ({m['n_steps']}) |"
    )


def write_report(results: dict, meta: dict, out_dir: Path | str) -> Path:
    """Write ``F1.7.md`` (Spanish) and ``F1.7.json`` into ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = meta.get("model", {})
    ms = results["methods"]
    lines = [
        "# F1.7 — Detector ML preentrenado (ClimateNet) vs. BARD",
        "",
        (
            "Pregunta: ¿cuánto coincide un detector de ríos atmosféricos (RA) preentrenado con BARD sobre la cordillera "
            "neuquina, y mejora algo a un umbral simple de IVT?"
        ),
        "",
        "## Fuente y alcance",
        "",
        f"- Fuente: {meta['source']}.",
        (
            f"- Período: {meta['period']}; años usados: {', '.join(str(y) for y in meta['years_used'])}; "
            f"{meta['n_steps']} pasos de 6 h compartidos."
        ),
        (
            f"- Polígono (lon, lat): {json.dumps(meta['polygon'])} — aproximación, sin verificar; "
            f"{meta['polygon_cells_bard_grid']} celdas en la grilla de BARD."
        ),
        f"- BARD: paso con RA si alguna celda del polígono tiene `ar_probability` ≥ {_f(meta['bard_threshold'])}.",
        "- ClimateNet: paso con RA si alguna celda del polígono (en su grilla) es de clase RA.",
        f"- Baseline: paso con RA si alguna celda del polígono tiene IVT ≥ {meta['ivt_threshold']:g} kg m-1 s-1.",
        "",
        "## Modelo",
        "",
        f"- Repositorio: {model.get('model_repo', 'sin verificar')}, commit `{model.get('model_commit', 'sin verificar')}`.",
        f"- Pesos: {model.get('weights_url', 'sin verificar')} (sha256 `{model.get('weights_sha256', 'sin verificar')}`).",
        f"- Grilla del modelo: {model.get('model_grid', 'sin verificar')}.",
        f"- Método: {model.get('method', 'sin verificar')}.",
        "",
        "## Pasos con RA en el polígono",
        "",
        "| Método | Pasos | Pasos con RA | Tasa |",
        "|---|---|---|---|",
        *[
            f"| {METHODS[k]} | {v['all']['n_steps']} | {v['all']['n_ar_steps']} | {_f(v['all']['ar_step_rate'], 3)} |"
            for k, v in ms.items()
        ],
        "",
        "## Acuerdo entre métodos (todos los pasos)",
        "",
        (
            "n11 = ambos con RA, n10 = solo el candidato, n01 = solo la referencia, n00 = ninguno. Tasa de aciertos = "
            "n11/(n11+n01); razón de falsas alarmas = n10/(n11+n10); Jaccard = n11/(n11+n10+n01). IoU de celdas: "
            "agregado / media por paso (pasos donde alguno marca)."
        ),
        "",
        "| Par | n11 | n10 | n01 | n00 | Tasa aciertos | Razón falsas alarmas | Kappa | Jaccard | IoU celdas |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *[_pair_row(_pair_title(p), p["all"]) for p in results["pairs"].values()],
        "",
        "## Por estación",
        "",
    ]
    for p in results["pairs"].values():
        lines += [
            f"### {_pair_title(p)}",
            "",
            "| Estación | n11 | n10 | n01 | n00 | Tasa aciertos | Razón falsas alarmas | Kappa | Jaccard | IoU celdas |",
            "|---|---|---|---|---|---|---|---|---|---|",
            *[_pair_row(label, p[s]) for s, label in SEASONS.items()],
            "",
        ]
    lines += ["## Salvedades", "", *[f"- {c}" for c in meta["caveats"]], ""]
    path = out_dir / "F1.7.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "F1.7.json").write_text(
        json.dumps(_clean({"meta": meta, "results": results}), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def run(
    bard_dir, climatenet_dir, ivt_dir, out_dir, threshold: float = catalog.DEFAULT_THRESHOLD
) -> dict:
    results, meta = compare_dirs(bard_dir, climatenet_dir, ivt_dir, threshold)
    write_report(results, meta, out_dir)
    return results


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bard-dir", type=Path, required=True)
    p.add_argument("--climatenet-dir", type=Path, required=True)
    p.add_argument("--ivt-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument(
        "--threshold",
        type=float,
        default=catalog.DEFAULT_THRESHOLD,
        help="BARD ar_probability threshold",
    )
    args = p.parse_args(argv)
    run(args.bard_dir, args.climatenet_dir, args.ivt_dir, args.out_dir, args.threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

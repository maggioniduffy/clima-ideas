"""Verification of the F5.1 hindcast forecasts against ERA5 (F5.2). Pure numpy/pandas/xarray."""

from __future__ import annotations

import warnings
from collections.abc import Callable

import numpy as np
import pandas as pd
import xarray as xr

KINDS = ("event", "control", "all")
COLUMNS = ["model", "lead", "kind", "threshold", "metric", "value", "lo", "hi", "n"]
CI_CONTINUOUS = ("bias", "mae", "crpss")
CI_BINARY = ("ets", "bss", "auc")


# --- scores -----------------------------------------------------------------------------------


def box_mean(da: xr.DataArray) -> xr.DataArray:
    """cos(lat)-weighted NaN-aware mean over lat and lon (all-NaN -> NaN)."""
    w = np.cos(np.deg2rad(da["lat"]))
    num = (da.fillna(0.0) * w).sum(("lat", "lon"))
    den = (da.notnull() * w).sum(("lat", "lon"))
    return (num / den.where(den > 0)).astype("float64")


def fair_crps(members: np.ndarray, obs: np.ndarray) -> np.ndarray:
    """Per-row fair ensemble CRPS; NaN members dropped per row, NaN for rows without members."""
    x = np.asarray(members, dtype="float64")
    y = np.asarray(obs, dtype="float64")
    ok = ~np.isnan(x)
    m = ok.sum(axis=1)
    term1 = np.where(ok, np.abs(x - y[:, None]), 0.0).sum(axis=1) / np.where(m > 0, m, 1)
    d = np.abs(x[:, :, None] - x[:, None, :])
    d = np.where(ok[:, :, None] & ok[:, None, :], d, 0.0).sum(axis=(1, 2))
    denom = 2.0 * m * (m - 1)
    term2 = np.where(m > 1, d / np.where(m > 1, denom, 1), 0.0)
    out = term1 - term2
    return np.where((m > 0) & ~np.isnan(y), out, np.nan)


def crps_vs_empirical(obs: np.ndarray) -> np.ndarray:
    """Leave-one-out climatological CRPS: case k is scored against the other cases' observations."""
    o = np.asarray(obs, dtype="float64")
    n = len(o)
    if n < 2:
        return np.full(n, np.nan)
    d = np.abs(o[:, None] - o[None, :])
    s = d.sum(axis=1)
    m = n - 1
    pair = d.sum() - 2.0 * s
    term2 = pair / (2.0 * m * (m - 1)) if m > 1 else 0.0
    return s / m - term2


def contingency(fcst: np.ndarray, obs: np.ndarray, thr: float) -> dict:
    f, o = np.asarray(fcst) >= thr, np.asarray(obs) >= thr
    h = int((f & o).sum())
    miss = int((~f & o).sum())
    fa = int((f & ~o).sum())
    cn = int((~f & ~o).sum())
    n = h + miss + fa + cn

    def ratio(a: float, b: float) -> float:
        return a / b if b > 0 else float("nan")

    hits_random = (h + miss) * (h + fa) / n if n else 0.0
    return {
        "hits": h,
        "misses": miss,
        "false_alarms": fa,
        "correct_neg": cn,
        "pod": ratio(h, h + miss),
        "far": ratio(fa, h + fa),
        "freq_bias": ratio(h + fa, h + miss),
        "ets": ratio(h - hits_random, h + miss + fa - hits_random),
    }


def brier(prob: np.ndarray, obs_bin: np.ndarray) -> float:
    p, o = np.asarray(prob, dtype="float64"), np.asarray(obs_bin, dtype="float64")
    return float(np.mean((p - o) ** 2)) if len(p) else float("nan")


def _loo_brier_ref(obs_bin: np.ndarray) -> np.ndarray:
    """Per-case squared error of the leave-one-out sample base rate."""
    o = np.asarray(obs_bin, dtype="float64")
    n = len(o)
    if n < 2:
        return np.full(n, np.nan)
    return ((o.sum() - o) / (n - 1) - o) ** 2


def bss(prob: np.ndarray, obs_bin: np.ndarray) -> float:
    """Brier skill score against the (leave-one-out) sample base rate."""
    ref = _loo_brier_ref(obs_bin)
    if len(ref) == 0 or not np.nanmean(ref) > 0:
        return float("nan")
    return 1.0 - brier(prob, obs_bin) / float(np.nanmean(ref))


def roc_auc(score: np.ndarray, obs_bin: np.ndarray) -> float:
    """Mann-Whitney AUC, ties count 0.5; NaN when a class is empty."""
    o = np.asarray(obs_bin).astype(bool)
    npos, nneg = int(o.sum()), int((~o).sum())
    if npos == 0 or nneg == 0:
        return float("nan")
    ranks = pd.Series(np.asarray(score, dtype="float64")).rank(method="average").to_numpy()
    return float((ranks[o].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def episodes(dates, gap_days: int = 3) -> np.ndarray:
    """Episode id per date (input order): a new episode starts when the gap to the previous
    sorted date exceeds ``gap_days``."""
    d = pd.to_datetime(pd.Series(np.asarray(dates)))
    order = np.argsort(d.to_numpy(), kind="stable")
    gaps = d.iloc[order].diff().dt.days.fillna(0).to_numpy()
    ids_sorted = np.cumsum(gaps > gap_days)
    out = np.empty(len(d), dtype="int64")
    out[order] = ids_sorted
    return out


def bootstrap_ci(
    fn: Callable[[np.ndarray], float],
    episode_ids: np.ndarray,
    n: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile CI of ``fn(index array)`` resampling whole episodes with replacement."""
    ids = np.asarray(episode_ids)
    uniq = np.unique(ids)
    groups = [np.flatnonzero(ids == u) for u in uniq]
    rng = np.random.default_rng(seed)
    vals = np.empty(n)
    for b in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[i] for i in pick])
        vals[b] = fn(idx)
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return float("nan"), float("nan")
    lo, hi = np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


# --- per model --------------------------------------------------------------------------------


def str_values(da: xr.DataArray) -> np.ndarray:
    """Plain ``<U`` array of a string coordinate (zarr v3 reads them as numpy ``StringDType``)."""
    return np.array([str(x) for x in da.values.tolist()])


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return float("nan")
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def _safe_mean(x: np.ndarray) -> float:
    return float(np.mean(x)) if len(x) else float("nan")


def verify_model(
    fc_ds: xr.Dataset,
    obs_box: pd.Series,
    thresholds: tuple[float, ...] = (5.0, 1.0, 10.0),
    main: float = 5.0,
    n_boot: int = 1000,
    seed: int = 0,
    model: str | None = None,
    obs_cells: xr.DataArray | None = None,
) -> pd.DataFrame:
    """Long table of scores for one F5.1 ``<model>.zarr`` dataset (see module docs).

    ``obs_cells`` (date, lat, lon) enables the cell-level sensitivity (``cell_mae``, ``cell_bias``).
    """
    model = model or str(fc_ds.attrs.get("model", "?"))
    prec = fc_ds["precip_mm"].where(fc_ds["status"] == 0)
    members = box_mean(prec).transpose("case", "lead", "member").values  # (case, lead, member)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ens_mean = np.nanmean(members, axis=2)
    leads = [int(x) for x in fc_ds["lead"].values]
    vdates = pd.to_datetime(fc_ds["valid_date"].values)
    case_kind = str_values(fc_ds["kind"])
    obs_all = obs_box.reindex(vdates).to_numpy(dtype="float64")
    cell_mean = cell_obs = None
    if obs_cells is not None:
        cell_obs = obs_cells.reindex(date=vdates).values  # (case, lat, lon)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            cell_mean = np.nanmean(prec.values, axis=2)  # (case, lead, lat, lon)
    rows: list[dict] = []

    def add(lead, kind, thr, metric, value, n, ci=(np.nan, np.nan)):
        rows.append(
            {
                "model": model,
                "lead": lead,
                "kind": kind,
                "threshold": thr,
                "metric": metric,
                "value": float(value),
                "lo": ci[0],
                "hi": ci[1],
                "n": int(n),
            }
        )

    for li, lead in enumerate(leads):
        for kind in KINDS:
            sel = (case_kind == kind) if kind != "all" else np.ones(len(case_kind), bool)
            sel = sel & ~np.isnan(ens_mean[:, li]) & ~np.isnan(obs_all)
            idx = np.flatnonzero(sel)
            n = len(idx)
            if n == 0:
                continue
            fm, ob, mem = ens_mean[idx, li], obs_all[idx], members[idx, li]
            ep = episodes(vdates[idx])
            kw = {"n": n_boot, "seed": seed}
            add(lead, kind, np.nan, "n", n, n)
            add(lead, kind, np.nan, "n_episodes", len(np.unique(ep)), n)
            add(lead, kind, np.nan, "obs_mean", ob.mean(), n)
            add(lead, kind, np.nan, "fc_mean", fm.mean(), n)
            err = fm - ob
            ae = np.abs(err)
            add(
                lead,
                kind,
                np.nan,
                "bias",
                err.mean(),
                n,
                bootstrap_ci(lambda i, e=err: e[i].mean(), ep, **kw),
            )
            add(
                lead,
                kind,
                np.nan,
                "mae",
                ae.mean(),
                n,
                bootstrap_ci(lambda i, e=ae: e[i].mean(), ep, **kw),
            )
            add(lead, kind, np.nan, "ratio", fm.mean() / ob.mean() if ob.mean() > 0 else np.nan, n)
            add(lead, kind, np.nan, "spearman", _spearman(fm, ob), n)
            crps = fair_crps(mem, ob)
            ref = crps_vs_empirical(ob)
            skill = 1.0 - crps.mean() / ref.mean() if ref.mean() > 0 else np.nan

            def crpss_fn(i, crps=crps, ref=ref):
                r = ref[i].mean()
                return 1.0 - crps[i].mean() / r if r > 0 else np.nan

            add(lead, kind, np.nan, "crps", crps.mean(), n)
            add(lead, kind, np.nan, "crps_ref", ref.mean(), n)
            add(lead, kind, np.nan, "crpss", skill, n, bootstrap_ci(crpss_fn, ep, **kw))
            if cell_mean is not None and kind != "control":
                cerr = cell_mean[idx, li] - cell_obs[idx]
                with np.errstate(all="ignore"):
                    add(
                        lead,
                        kind,
                        np.nan,
                        "cell_mae",
                        np.nanmean(np.nanmean(np.abs(cerr), axis=0)),
                        n,
                    )
                    add(lead, kind, np.nan, "cell_bias", np.nanmean(np.nanmean(cerr, axis=0)), n)
            if kind != "all":
                continue
            with np.errstate(all="ignore"):
                n_valid = (~np.isnan(mem)).sum(axis=1)
                for thr in thresholds:
                    ob_bin = ob >= thr
                    prob = np.where(
                        n_valid > 0, np.nansum(mem >= thr, axis=1) / np.maximum(n_valid, 1), np.nan
                    )
                    ct = contingency(fm, ob, thr)
                    for k in ("hits", "misses", "false_alarms", "correct_neg"):
                        add(lead, kind, thr, k, ct[k], n)
                    bs_ref = _loo_brier_ref(ob_bin)
                    bs_case = (prob - ob_bin.astype(float)) ** 2

                    def ets_fn(i, fm=fm, ob=ob, thr=thr):
                        return contingency(fm[i], ob[i], thr)["ets"]

                    def bss_fn(i, bs_case=bs_case, bs_ref=bs_ref):
                        r = bs_ref[i].mean()
                        return 1.0 - bs_case[i].mean() / r if r > 0 else np.nan

                    def auc_fn(i, fm=fm, ob_bin=ob_bin):
                        return roc_auc(fm[i], ob_bin[i])

                    for k in ("pod", "far", "freq_bias"):
                        add(lead, kind, thr, k, ct[k], n)
                    add(lead, kind, thr, "ets", ct["ets"], n, bootstrap_ci(ets_fn, ep, **kw))
                    add(lead, kind, thr, "brier", brier(prob, ob_bin), n)
                    add(
                        lead, kind, thr, "bss", bss(prob, ob_bin), n, bootstrap_ci(bss_fn, ep, **kw)
                    )
                    add(
                        lead,
                        kind,
                        thr,
                        "auc",
                        roc_auc(fm, ob_bin),
                        n,
                        bootstrap_ci(auc_fn, ep, **kw),
                    )
    return pd.DataFrame(rows, columns=COLUMNS)


def _chain(lows: dict[int, float], floor: float) -> int:
    """Largest L such that lows[1..L] are all > floor (NaN or missing breaks the chain)."""
    best = 0
    for lead in range(1, max(lows, default=0) + 1):
        v = lows.get(lead, np.nan)
        if np.isnan(v) or not v > floor:
            break
        best = lead
    return best


def useful_horizon(df: pd.DataFrame, threshold: float) -> dict[str, dict[str, int]]:
    """Per model: largest lead with ETS lo > 0 (``ets``), AUC lo > 0.5 (``auc``) and both (``both``),
    each requiring every shorter lead to pass too (0 = none)."""
    out: dict[str, dict[str, int]] = {}
    sub = df[(df["kind"] == "all") & np.isclose(df["threshold"].astype(float), threshold)]
    for model, g in sub.groupby("model", sort=False):
        lows = {
            m: g[g["metric"] == m].set_index("lead")["lo"].astype(float).to_dict()
            for m in ("ets", "auc")
        }
        h_ets, h_auc = _chain(lows["ets"], 0.0), _chain(lows["auc"], 0.5)
        out[str(model)] = {"ets": h_ets, "auc": h_auc, "both": min(h_ets, h_auc)}
    return out


# --- report -----------------------------------------------------------------------------------


def _f(x, d: int = 2) -> str:
    if x is None or (isinstance(x, float | np.floating) and np.isnan(x)):
        return "—"
    return f"{x:.{d}f}".replace(".", ",")


def _ci(v, lo, hi, d: int = 2) -> str:
    if np.isnan(v):
        return "—"
    if np.isnan(lo) or np.isnan(hi):
        return _f(v, d)
    return f"{_f(v, d)} [{_f(lo, d)}; {_f(hi, d)}]"


def _get(df: pd.DataFrame, model: str, lead: int, kind: str, metric: str, thr=np.nan):
    s = df[(df["model"] == model) & (df["lead"] == lead) & (df["kind"] == kind)]
    s = s[s["metric"] == metric]
    if np.isnan(thr):
        s = s[s["threshold"].isna()]
    else:
        s = s[np.isclose(s["threshold"].astype(float), thr)]
    if s.empty:
        return float("nan"), float("nan"), float("nan"), 0
    r = s.iloc[0]
    return float(r["value"]), float(r["lo"]), float(r["hi"]), int(r["n"])


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out + [""]


RULE_LINES = [
    (
        "- Observado: ERA5 `tp`, suma de las horas D 01:00 … D+1 00:00 UTC (misma ventana que la anticipación L: "
        "horas (24(L−1), 24L] de la corrida 00 UTC), recorte a la caja −41…−36 / −71,5…−68, ×1000 → mm."
    ),
    (
        "- Variable verificada: media de la caja ponderada por cos(lat), por caso, anticipación y miembro "
        "(pronóstico) y por caso (observado). Sensibilidad: celda a celda."
    ),
    (
        "- Continuas: sesgo y MAE de la media del ensamble, razón de medias, Spearman; CRPS (ensamble «fair»; "
        "con un solo miembro = error absoluto) y CRPSS contra climatología muestral (distribución empírica de lo "
        "observado en los otros casos del mismo modelo, dejando uno afuera)."
    ),
    (
        "- Binarias sobre la media de caja: umbral principal {main} mm/día, sensibilidades {sens}. POD, FAR, sesgo de "
        "frecuencia, ETS (media del ensamble ≥ umbral); Brier y BSS contra la tasa base muestral (fracción de miembros ≥ "
        "umbral); AUC ROC con la media del ensamble."
    ),
    "- IC 95 % por bootstrap de episodios (casos a ±3 días agrupados, {n_boot} remuestreos, semilla {seed}).",
    (
        "- Horizonte útil: mayor anticipación L tal que, para todas las anticipaciones 1…L, el IC inferior de ETS > 0 y "
        "el de AUC > 0,5; se informa también cada criterio por separado."
    ),
]


def render_md(df: pd.DataFrame, horizons: dict, meta: dict) -> str:
    """Spanish report. ``horizons`` = ``{threshold: useful_horizon(df, threshold)}``."""
    main = float(meta.get("main", 5.0))
    thresholds = [float(t) for t in meta.get("thresholds", (5.0, 1.0, 10.0))]
    sens = [t for t in thresholds if t != main]
    models = list(dict.fromkeys(df["model"]))
    leads = sorted(int(x) for x in df["lead"].unique())
    hz = {float(k): v for k, v in horizons.items()}
    L = ["# F5.2 — Acierto por anticipación de los ríos atmosféricos contra ERA5 (mitad AR)", ""]
    L += ["## Veredicto", "", "<!-- veredicto: lo escribe Opus -->", ""]
    for thr in [main, *sens]:
        for model in models:
            h = hz.get(thr, {}).get(model)
            if h is None:
                continue
            word = "ningún día" if h["both"] == 0 else f"{h['both']} día(s)"
            L.append(
                f"- {model}, umbral {_f(thr, 0)} mm: horizonte útil {word} "
                f"(solo ETS: {h['ets']}; solo AUC: {h['auc']})."
            )
    L += ["", "## Fuente y alcance", ""]
    L.append(f"- Observado: {meta.get('obs_source', 'ERA5')}; {meta.get('obs_window', '')}")
    if meta.get("obs_note"):
        L.append(f"- {meta['obs_note']}")
    for model in models:
        info = meta.get("models", {}).get(model, {})
        L.append(
            f"- {model}: {info.get('source', '')}; {info.get('period', '')}; "
            f"{info.get('n_event', '?')} casos de evento y {info.get('n_control', '?')} de control."
        )
    L += ["", "## Regla fijada antes de correr", ""]
    for line in RULE_LINES:
        L.append(
            line.replace("{main}", _f(main, 0))
            .replace("{sens}", ", ".join(f"{_f(t, 0)} mm" for t in sens))
            .replace("{n_boot}", str(meta.get("n_boot", 1000)))
            .replace("{seed}", str(meta.get("seed", 0)))
        )
    L.append("")
    for model in models:
        L += [f"## {model}", ""]
        for kind, label in (("event", "Casos de evento"), ("control", "Casos de control")):
            L += [f"### {label}: error en mm/día (caja media)", ""]
            rows = []
            for lead in leads:
                g = lambda m, kind=kind, lead=lead, model=model: _get(df, model, lead, kind, m)
                n = g("n")[0]
                if np.isnan(n):
                    continue
                cs = g("crpss")
                rows.append(
                    [
                        str(lead),
                        str(int(n)),
                        _f(g("obs_mean")[0]),
                        _f(g("fc_mean")[0]),
                        _ci(*g("bias")[:3]),
                        _ci(*g("mae")[:3]),
                        _ci(cs[0], cs[1], cs[2]),
                    ]
                )
            L += _table(
                [
                    "Anticipación (días)",
                    "n",
                    "Obs. medio",
                    "Pronóstico medio",
                    "Sesgo [IC]",
                    "MAE [IC]",
                    "CRPSS [IC]",
                ],
                rows,
            )
        L += [f"### Umbral {_f(main, 0)} mm/día (todos los casos)", ""]
        rows = []
        for lead in leads:
            g = lambda m, lead=lead, model=model: _get(df, model, lead, "all", m, main)
            n = g("ets")[3]
            if not n:
                continue
            rows.append(
                [
                    str(lead),
                    str(n),
                    _f(g("pod")[0]),
                    _f(g("far")[0]),
                    _f(g("freq_bias")[0]),
                    _ci(*g("ets")[:3]),
                    _ci(*g("bss")[:3]),
                    _ci(*g("auc")[:3]),
                ]
            )
        L += _table(
            [
                "Anticipación (días)",
                "n",
                "POD",
                "FAR",
                "Sesgo frec.",
                "ETS [IC]",
                "BSS [IC]",
                "AUC [IC]",
            ],
            rows,
        )
        if sens:
            L += ["### Sensibilidad a otros umbrales (todos los casos)", ""]
            header = ["Anticipación (días)"]
            for t in sens:
                header += [f"ETS {_f(t, 0)} mm [IC]", f"AUC {_f(t, 0)} mm [IC]"]
            rows = []
            for lead in leads:
                row = [str(lead)]
                for t in sens:
                    row += [
                        _ci(*_get(df, model, lead, "all", "ets", t)[:3]),
                        _ci(*_get(df, model, lead, "all", "auc", t)[:3]),
                    ]
                rows.append(row)
            L += _table(header, rows)
        if (df[(df["model"] == model) & (df["metric"] == "cell_mae")]).shape[0]:
            L += ["### Sensibilidad celda a celda (media de la caja vs. media sobre celdas)", ""]
            rows = []
            for lead in leads:
                row = [str(lead)]
                for kind in ("event", "all"):
                    for m in ("mae", "cell_mae", "bias", "cell_bias"):
                        row.append(_f(_get(df, model, lead, kind, m)[0]))
                rows.append(row)
            header = ["Anticipación (días)"] + [
                f"{m} {k}"
                for k in ("evento", "todos")
                for m in ("MAE caja", "MAE celda", "sesgo caja", "sesgo celda")
            ]
            L += _table(header, rows)
    L += [
        "## Advertencias",
        "",
        (
            "- La muestra es 50/50 evento/control por construcción: no es la tasa base climatológica, así que ETS, "
            "Brier y BSS no son valores operativos; sirven para comparar anticipaciones y modelos entre sí."
        ),
        (
            "- IFS y AIFS tienen pocos casos (n chico, ICs anchos); IFS está a 0,4° hasta 2024-02-28 y se interpola "
            "bilinealmente a 0,25°."
        ),
        (
            "- ERA5 es un reanálisis, no lluvia medida: subestima o desplaza la lluvia intensa y orográfica; "
            "los errores incluyen el error de la referencia."
        ),
        "- Mitad convección pendiente: F5.1 no tiene casos convectivos, así que no se verifica convección aquí.",
        "- Esto es retrospectivo, no un sistema de alerta; los avisos oficiales son del SMN, la AIC y Defensa Civil.",
        "",
    ]
    return "\n".join(L)

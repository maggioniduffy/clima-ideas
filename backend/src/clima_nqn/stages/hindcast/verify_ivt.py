"""F5.10: forecast IVT vs. forecast precipitation, same cases, same metrics, per lead.

Inputs are the F5.10 IVT store (``gefs-reforecast-ivt.zarr``, member c00), the F5.1 precipitation
store (member c00 only) and an ERA5 obs zarr with ``ivt`` and ``precip_mm``. Three verified
quantities per case and lead: ``ivt_max`` (spatial maximum of the daily IVT over the box, main),
``ivt_mean`` (box mean, sensitivity) and ``precip`` (box mean, as in F5.2). Metrics per lead and
quantity: AUC event vs. control, Spearman (events, all), rank-CRPSS against leave-one-out
climatology, episode-bootstrap CIs; and paired IVT - precip differences of AUC and Spearman whose CI
comes from the same bootstrap resamples (the same seed and episode ids give the same index draws).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from clima_nqn.stages.hindcast import verify as vf

QUANTITIES = ("ivt_max", "ivt_mean", "precip")
PAIRS = (("ivt_max", "precip"), ("ivt_mean", "precip"))  # main, sensitivity
COLUMNS = ["variable", "lead", "kind", "metric", "value", "lo", "hi", "n"]
MIN_CASES = 6


def _member_pos(ds: xr.Dataset, member: str) -> int:
    members = list(vf.str_values(ds["member"]))
    if member not in members:
        raise ValueError(f"member {member!r} not in the store ({members})")
    return members.index(member)


def _rank01(x: np.ndarray) -> np.ndarray:
    """Percentile rank within the sample, scaled to [0, 1] (ties average)."""
    n = len(x)
    if n < 2:
        return np.zeros(n)
    return (pd.Series(x).rank(method="average").to_numpy() - 1.0) / (n - 1.0)


def _cell_max(da: xr.DataArray) -> xr.DataArray:
    return da.max(("lat", "lon"), skipna=True).astype("float64")


def prepare(
    ivt_ds: xr.Dataset, precip_ds: xr.Dataset, obs_ds: xr.Dataset, member: str = "c00"
) -> dict:
    """Aligned arrays: ``fc[q]`` (case, lead), ``obs[q]`` (case), kinds, valid dates, leads."""
    if "ivt" not in ivt_ds:
        raise ValueError("the IVT store lacks ivt")
    if "ivt" not in obs_ds or "precip_mm" not in obs_ds:
        raise ValueError("obs needs ivt and precip_mm (`hindcast observe --variables tp,ivt`)")
    if "precip_mm" not in precip_ds:
        raise ValueError("the precipitation store lacks precip_mm")
    ids_i, ids_p = vf.str_values(ivt_ds["case"]), vf.str_values(precip_ds["case"])
    pos_p = {c: k for k, c in enumerate(ids_p)}
    ii = [k for k, c in enumerate(ids_i) if c in pos_p]
    ip = [pos_p[ids_i[k]] for k in ii]
    if not ii:
        raise ValueError("no common cases between the IVT and precipitation stores")
    leads = sorted(
        {int(x) for x in ivt_ds["lead"].values} & {int(x) for x in precip_ds["lead"].values}
    )
    if not leads:
        raise ValueError("no common leads")
    for a, b in ((ivt_ds, precip_ds), (ivt_ds, obs_ds)):
        if not (
            np.array_equal(np.round(a["lat"].values, 4), np.round(b["lat"].values, 4))
            and np.array_equal(np.round(a["lon"].values, 4), np.round(b["lon"].values, 4))
        ):
            raise ValueError("the stores do not share one lat/lon grid")
    ivt = (
        ivt_ds["ivt"]
        .where(ivt_ds["status"] == 0)
        .isel(case=ii, member=_member_pos(ivt_ds, member))
        .sel(lead=leads)
        .transpose("case", "lead", "lat", "lon")
    )
    pre = (
        precip_ds["precip_mm"]
        .where(precip_ds["status"] == 0)
        .isel(case=ip, member=_member_pos(precip_ds, member))
        .sel(lead=leads)
        .transpose("case", "lead", "lat", "lon")
    )
    vdates = pd.to_datetime(ivt_ds["valid_date"].values[ii])
    if not (pd.to_datetime(precip_ds["valid_date"].values[ip]) == vdates).all():
        raise ValueError("valid dates differ between the IVT and precipitation stores")
    fc = {
        "ivt_max": _cell_max(ivt).values,
        "ivt_mean": vf.box_mean(ivt).values,
        "precip": vf.box_mean(pre).values,
    }
    obs_ivt = obs_ds["ivt"].reindex(date=vdates)
    obs_pre = obs_ds["precip_mm"].reindex(date=vdates)
    obs = {
        "ivt_max": _cell_max(obs_ivt).values,
        "ivt_mean": vf.box_mean(obs_ivt).values,
        "precip": vf.box_mean(obs_pre).values,
    }
    return {
        "fc": fc,
        "obs": obs,
        "kind": vf.str_values(ivt_ds["kind"])[ii],
        "vdates": vdates,
        "leads": leads,
    }


def verify_ivt(
    ivt_ds: xr.Dataset,
    precip_ds: xr.Dataset,
    obs_ds: xr.Dataset,
    n_boot: int = 1000,
    seed: int = 0,
    member: str = "c00",
) -> tuple[pd.DataFrame, dict]:
    """Long table (``COLUMNS``) and meta of the F5.10 comparison."""
    d = prepare(ivt_ds, precip_ds, obs_ds, member)
    kind, vdates = d["kind"], d["vdates"]
    rows: list[dict] = []

    def add(variable, lead, kd, metric, value, n, ci=(np.nan, np.nan)):
        rows.append(
            {
                "variable": variable,
                "lead": lead,
                "kind": kd,
                "metric": metric,
                "value": float(value),
                "lo": ci[0],
                "hi": ci[1],
                "n": int(n),
            }
        )

    kw = {"n": n_boot, "seed": seed}
    for li, lead in enumerate(d["leads"]):
        ok = np.ones(len(kind), bool)
        for q in QUANTITIES:
            ok &= np.isfinite(d["fc"][q][:, li]) & np.isfinite(d["obs"][q])
        idx = np.flatnonzero(ok)  # one common sample for every quantity and pair
        is_ev = kind[idx] == "event"
        n = len(idx)
        if n < MIN_CASES or is_ev.sum() == 0 or (~is_ev).sum() == 0:
            continue
        ep = vf.episodes(vdates[idx])
        ev = np.flatnonzero(is_ev)
        ep_ev = vf.episodes(vdates[idx][ev])
        add("all", lead, "all", "n", n, n)
        add("all", lead, "event", "n", len(ev), n)
        add("all", lead, "all", "n_episodes", len(np.unique(ep)), n)
        f = {q: d["fc"][q][idx, li] for q in QUANTITIES}
        o = {q: d["obs"][q][idx] for q in QUANTITIES}

        def auc_fn(i, a, b=None, is_ev=is_ev):
            if b is None:
                return vf.roc_auc(a[i], is_ev[i])
            return vf.roc_auc(a[i], is_ev[i]) - vf.roc_auc(b[i], is_ev[i])

        for q in QUANTITIES:
            fq, oq = f[q], o[q]
            add(q, lead, "all", "auc", vf.roc_auc(fq, is_ev), n,
                vf.bootstrap_ci(lambda i, a=fq: auc_fn(i, a), ep, **kw))  # fmt: skip
            add(q, lead, "all", "spearman", vf._spearman(fq, oq), n,
                vf.bootstrap_ci(lambda i, a=fq, b=oq: vf._spearman(a[i], b[i]), ep, **kw))  # fmt: skip
            add(q, lead, "event", "spearman", vf._spearman(fq[ev], oq[ev]), len(ev),
                vf.bootstrap_ci(lambda i, a=fq[ev], b=oq[ev]: vf._spearman(a[i], b[i]), ep_ev, **kw))  # fmt: skip
            fr, orr = _rank01(fq), _rank01(oq)
            crps, ref = np.abs(fr - orr), vf.crps_vs_empirical(orr)
            skill = 1.0 - crps.mean() / ref.mean() if ref.mean() > 0 else np.nan

            def crpss_fn(i, crps=crps, ref=ref):
                r = ref[i].mean()
                return 1.0 - crps[i].mean() / r if r > 0 else np.nan

            add(q, lead, "all", "crpss_rank", skill, n, vf.bootstrap_ci(crpss_fn, ep, **kw))
        for a, b in PAIRS:
            name = f"{a}-{b}"
            add(name, lead, "all", "d_auc", vf.roc_auc(f[a], is_ev) - vf.roc_auc(f[b], is_ev), n,
                vf.bootstrap_ci(lambda i, a=f[a], b=f[b]: auc_fn(i, a, b), ep, **kw))  # fmt: skip
            add(name, lead, "all", "d_spearman",
                vf._spearman(f[a], o[a]) - vf._spearman(f[b], o[b]), n,
                vf.bootstrap_ci(
                    lambda i, fa=f[a], oa=o[a], fb=f[b], ob=o[b]: (
                        vf._spearman(fa[i], oa[i]) - vf._spearman(fb[i], ob[i])
                    ), ep, **kw))  # fmt: skip
            add(name, lead, "event", "d_spearman",
                vf._spearman(f[a][ev], o[a][ev]) - vf._spearman(f[b][ev], o[b][ev]), len(ev),
                vf.bootstrap_ci(
                    lambda i, fa=f[a][ev], oa=o[a][ev], fb=f[b][ev], ob=o[b][ev]: (
                        vf._spearman(fa[i], oa[i]) - vf._spearman(fb[i], ob[i])
                    ), ep_ev, **kw))  # fmt: skip
    df = pd.DataFrame(rows, columns=COLUMNS)
    kinds = vf.str_values(ivt_ds["kind"])
    meta = {
        "member": member,
        "n_boot": n_boot,
        "seed": seed,
        "leads": d["leads"],
        "n_event": int((kinds == "event").sum()),
        "n_control": int((kinds == "control").sum()),
        "ivt_source": ivt_ds.attrs.get("source", ""),
        "ivt_period": ivt_ds.attrs.get("period", ""),
        "ivt_levels_hpa": list(ivt_ds.attrs.get("levels_hpa", [])),
        "ivt_steps": ivt_ds.attrs.get("steps", ""),
        "precip_source": precip_ds.attrs.get("source", ""),
        "obs_source": obs_ds.attrs.get("source", ""),
        "obs_window": obs_ds.attrs.get("window", ""),
        "obs_ivt_window": obs_ds.attrs.get("ivt_window", ""),
        "obs_note": f"{obs_ds.sizes['date']} fechas; ERA5T: {obs_ds.attrs.get('era5t')}",
    }
    return df, meta


def horizons(df: pd.DataFrame) -> dict[str, dict[str, int]]:
    """Per quantity: longest L with AUC lo > 0.5 (``auc``), Spearman(all) lo > 0 (``spearman``) and
    both (``both``) for every lead 1..L."""
    out: dict[str, dict[str, int]] = {}
    for q in QUANTITIES:
        g = df[(df["variable"] == q) & (df["kind"] == "all")]
        lows = {
            m: g[g["metric"] == m].set_index("lead")["lo"].astype(float).to_dict()
            for m in ("auc", "spearman")
        }
        h_auc, h_sp = vf._chain(lows["auc"], 0.5), vf._chain(lows["spearman"], 0.0)
        out[q] = {"auc": h_auc, "spearman": h_sp, "both": min(h_auc, h_sp)}
    return out


# --- report -----------------------------------------------------------------------------------

RULE_LINES = [
    (
        "- IVT pronosticado: |Q| con Q = (1/g) ∫ q·(u, v) dp, por trapecio sobre 1000, 925, 850, 700, 600, 500, 400 "
        "y 300 hPa (g = 9,80665; presión en Pa), en las horas 24(L−1)+6, +12, +18 y 24L de la corrida 00 UTC; el IVT "
        "diario es la media de los cuatro |Q| (media de módulos)."
    ),
    (
        "- IVT observado: ERA5 `viwve`/`viwvn` (columna completa), |Q| en las mismas cuatro horas, promediado igual."
    ),
    (
        "- Agregado espacial: máximo sobre la caja del IVT medio diario (principal; coherente con el `ivt_max` del "
        "catálogo); sensibilidad: media de la caja ponderada por cos(lat). La lluvia usa la media de la caja, como en F5.2."
    ),
    (
        "- Mismas métricas para IVT y lluvia, por anticipación y sobre la misma muestra de casos (solo casos con las "
        "seis series finitas): AUC evento contra control con el valor pronosticado como puntaje; Spearman entre "
        "pronóstico y ERA5 (todos los casos y solo eventos); CRPSS-rango contra la climatología muestral dejando uno "
        "afuera, sobre percentiles de rango [0, 1] de pronóstico y observado dentro de su propia muestra de esa "
        "anticipación (un solo miembro: CRPS = |x − y|), que no depende del sesgo de nivel."
    ),
    (
        "- IC 95 % por bootstrap de episodios (casos a ±3 días agrupados, {n_boot} remuestreos, semilla {seed}). Las "
        "diferencias pareadas IVT − lluvia usan los mismos remuestreos para las dos variables."
    ),
    (
        "- Horizonte por variable: mayor anticipación L tal que, para todas las anticipaciones 1…L, el IC inferior del "
        "AUC > 0,5 y el del Spearman (todos los casos) > 0."
    ),
]


def _get(df: pd.DataFrame, variable: str, lead: int, kind: str, metric: str):
    s = df[
        (df["variable"] == variable)
        & (df["lead"] == lead)
        & (df["kind"] == kind)
        & (df["metric"] == metric)
    ]
    if s.empty:
        return float("nan"), float("nan"), float("nan"), 0
    r = s.iloc[0]
    return float(r["value"]), float(r["lo"]), float(r["hi"]), int(r["n"])


def _c(df, variable, lead, kind, metric) -> str:
    return vf._ci(*_get(df, variable, lead, kind, metric)[:3])


def render_md(df: pd.DataFrame, hz: dict, meta: dict) -> str:
    """Spanish report of the F5.10 comparison (verdict left as a placeholder)."""
    leads = sorted(int(x) for x in df["lead"].unique())
    pair = "ivt_max-precip"
    L = ["# F5.10 — Acierto del IVT pronosticado frente a la lluvia pronosticada", ""]
    L += ["## Veredicto", "", "<!-- veredicto: lo escribe Opus -->", ""]
    names = {"ivt_max": "IVT (máximo de la caja)", "ivt_mean": "IVT (media de la caja)"}
    for q in QUANTITIES:
        h = hz.get(q)
        if h is None:
            continue
        word = "ningún día" if h["both"] == 0 else f"{h['both']} día(s)"
        L.append(
            f"- {names.get(q, 'Lluvia (media de la caja)')}: horizonte {word} "
            f"(solo AUC: {h['auc']}; solo Spearman: {h['spearman']})."
        )
    L += ["", "## Fuente y alcance", ""]
    L.append(f"- IVT pronosticado: {meta.get('ivt_source', '')}; {meta.get('ivt_period', '')}.")
    if meta.get("ivt_steps"):
        L.append(f"- Convención: {meta['ivt_steps']}.")
    L.append(
        f"- Lluvia pronosticada: {meta.get('precip_source', '')} (F5.1, miembro {meta['member']})."
    )
    L.append(f"- Observado: {meta.get('obs_source', 'ERA5')}; {meta.get('obs_window', '')}")
    if meta.get("obs_ivt_window"):
        L.append(f"- {meta['obs_ivt_window']}")
    if meta.get("obs_note"):
        L.append(f"- {meta['obs_note']}")
    L.append(
        f"- Casos: {meta.get('n_event', '?')} de evento y {meta.get('n_control', '?')} de control (F1.3, F5.1); "
        f"solo el miembro {meta['member']}."
    )
    L += ["", "## Regla fijada antes de correr", ""]
    for line in RULE_LINES:
        L.append(
            line.replace("{n_boot}", str(meta.get("n_boot", 1000))).replace(
                "{seed}", str(meta.get("seed", 0))
            )
        )
    L.append("")
    L += ["## IVT (máximo de la caja) frente a lluvia, por anticipación", ""]
    rows = []
    for lead in leads:
        n = _get(df, "all", lead, "all", "n")[0]
        if np.isnan(n):
            continue
        rows.append(
            [
                str(lead),
                str(int(n)),
                _c(df, "ivt_max", lead, "all", "auc"),
                _c(df, "precip", lead, "all", "auc"),
                _c(df, pair, lead, "all", "d_auc"),
                _c(df, "ivt_max", lead, "all", "spearman"),
                _c(df, "precip", lead, "all", "spearman"),
                _c(df, pair, lead, "all", "d_spearman"),
                _c(df, "ivt_max", lead, "all", "crpss_rank"),
                _c(df, "precip", lead, "all", "crpss_rank"),
            ]
        )
    L += vf._table(
        [
            "Anticipación (días)",
            "n",
            "AUC IVT [IC]",
            "AUC lluvia [IC]",
            "Dif. AUC IVT − lluvia [IC]",
            "Spearman IVT (todos) [IC]",
            "Spearman lluvia (todos) [IC]",
            "Dif. Spearman [IC]",
            "CRPSS-rango IVT [IC]",
            "CRPSS-rango lluvia [IC]",
        ],
        rows,
    )
    L += ["### Spearman solo en eventos", ""]
    rows = [
        [
            str(lead),
            _c(df, "ivt_max", lead, "event", "spearman"),
            _c(df, "precip", lead, "event", "spearman"),
            _c(df, pair, lead, "event", "d_spearman"),
        ]
        for lead in leads
    ]
    L += vf._table(
        [
            "Anticipación (días)",
            "Spearman IVT (eventos) [IC]",
            "Spearman lluvia (eventos) [IC]",
            "Dif. [IC]",
        ],
        rows,
    )
    L += ["## Sensibilidad: IVT medio de la caja", ""]
    spair = "ivt_mean-precip"
    rows = [
        [
            str(lead),
            _c(df, "ivt_mean", lead, "all", "auc"),
            _c(df, spair, lead, "all", "d_auc"),
            _c(df, "ivt_mean", lead, "all", "spearman"),
            _c(df, spair, lead, "all", "d_spearman"),
            _c(df, "ivt_mean", lead, "all", "crpss_rank"),
        ]
        for lead in leads
    ]
    L += vf._table(
        [
            "Anticipación (días)",
            "AUC IVT medio [IC]",
            "Dif. AUC vs. lluvia [IC]",
            "Spearman IVT medio [IC]",
            "Dif. Spearman vs. lluvia [IC]",
            "CRPSS-rango IVT medio [IC]",
        ],
        rows,
    )
    L += [
        "## Advertencias",
        "",
        (
            f"- Solo el miembro {meta['member']} (control) de GEFS, tanto para el IVT como para la lluvia: no es el "
            "ensamble de F5.2 (5 miembros), así que la curva de lluvia no es idéntica a la de F5.2."
        ),
        (
            "- El IVT pronosticado integra 8 niveles entre 1000 y 300 hPa; ERA5 `viwve`/`viwvn` integra la columna "
            "completa. Hay un sesgo de nivel entre los dos. Las métricas principales (AUC, Spearman, CRPSS sobre "
            "rangos) no dependen de la escala, pero los valores absolutos del IVT pronosticado y del observado no son "
            "comparables kg a kg."
        ),
        (
            "- El IVT observado y los eventos del catálogo F1.3 salen del mismo IVT de ERA5, y los controles se "
            "eligieron sin río atmosférico a ±3 días. Por eso el AUC del IVT mide en parte la coincidencia con la "
            "definición del catálogo, no solo la habilidad física; la lluvia no tiene esa ventaja, y la comparación "
            "favorece al IVT por construcción."
        ),
        (
            "- La muestra es 50/50 evento/control por construcción: no es la tasa base climatológica; las cifras sirven "
            "para comparar variables y anticipaciones entre sí."
        ),
        "- Esto es retrospectivo, no un sistema de alerta; los avisos oficiales son del SMN, la AIC y Defensa Civil.",
        "",
    ]
    return "\n".join(L)

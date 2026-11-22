"""AIFS vs. IFS on the common F5.1 cases (F5.4): paired absolute errors against ERA5."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import xarray as xr
from scipy.stats import binomtest

from clima_nqn.stages.hindcast import verify as v

TIE_MM = 0.05
GROUPS = {"1–3": (1, 3), "4–7": (4, 7), "8–10": (8, 10)}
KINDS = ("event", "control", "all")
NATIVE_025_FROM = pd.Timestamp("2024-02-29")
PLACEHOLDER = "<!-- veredicto: lo escribe Opus -->"
SUMMARY_COLUMNS = [
    "lead", "kind", "n", "mae_ifs", "mae_aifs", "diff", "lo", "hi", "bias_ifs", "bias_aifs",
    "wins_aifs", "wins_ifs", "ties", "p_sign", "verdict",
]  # fmt: skip


# --- paired table -----------------------------------------------------------------------------


def _box(ds: xr.Dataset) -> np.ndarray:
    """(case, lead) box mean of the valid entries (NaN where the entry is not status 0)."""
    prec = ds["precip_mm"].where(ds["status"] == 0)
    bm = v.box_mean(prec).transpose("case", "lead", "member").values
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(bm, axis=2)


def paired_table(ifs: xr.Dataset, aifs: xr.Dataset, obs_box: pd.Series) -> pd.DataFrame:
    """Long table of paired forecasts: one row per common case and lead with both entries valid
    and the observation available."""
    ids_i = v.str_values(ifs["case"])
    ids_a = v.str_values(aifs["case"])
    common = [c for c in ids_i if c in set(ids_a)]
    cols = [
        "case", "kind", "event_id", "valid_date", "lead", "obs", "ifs", "aifs",
        "ae_ifs", "ae_aifs", "winner",
    ]  # fmt: skip
    if not common:
        return pd.DataFrame(columns=cols)
    ifs_c = ifs.isel(case=[int(np.flatnonzero(ids_i == c)[0]) for c in common])
    aifs_c = aifs.isel(case=[int(np.flatnonzero(ids_a == c)[0]) for c in common])
    leads = [int(x) for x in ifs_c["lead"].values if int(x) in set(aifs_c["lead"].values.tolist())]
    fi = _box(ifs_c.sel(lead=leads))
    fa = _box(aifs_c.sel(lead=leads))
    vd = pd.to_datetime(ifs_c["valid_date"].values)
    kind = v.str_values(ifs_c["kind"])
    event_id = v.str_values(ifs_c["event_id"])
    ob = obs_box.reindex(vd).to_numpy(dtype="float64")
    rows = []
    for li, lead in enumerate(leads):
        for ci, case in enumerate(common):
            o, i, a = ob[ci], fi[ci, li], fa[ci, li]
            if np.isnan(o) or np.isnan(i) or np.isnan(a):
                continue
            aei, aea = abs(i - o), abs(a - o)
            if abs(aei - aea) < TIE_MM:
                w = "empate"
            else:
                w = "aifs" if aea < aei else "ifs"
            rows.append(
                {
                    "case": case,
                    "kind": kind[ci],
                    "event_id": event_id[ci],
                    "valid_date": vd[ci],
                    "lead": lead,
                    "obs": float(o),
                    "ifs": float(i),
                    "aifs": float(a),
                    "ae_ifs": float(aei),
                    "ae_aifs": float(aea),
                    "winner": w,
                }
            )
    return pd.DataFrame(rows, columns=cols)


# --- summary ----------------------------------------------------------------------------------


def sign_test_p(wins_aifs: int, wins_ifs: int) -> float:
    """Two-sided exact sign test on the non-tied pairs (NaN without pairs)."""
    n = int(wins_aifs) + int(wins_ifs)
    if n == 0:
        return float("nan")
    return float(binomtest(int(wins_aifs), n, 0.5).pvalue)


def verdict(diff_lo: float, diff_hi: float, p_sign: float, diff: float) -> str:
    """Fixed rule: the CI of the mean diff (AIFS-IFS) must exclude 0 AND sign test p < 0.05."""
    if np.isnan(diff_lo) or np.isnan(diff_hi) or np.isnan(p_sign):
        return "sin diferencia detectable"
    excludes = diff_lo > 0 or diff_hi < 0
    if excludes and p_sign < 0.05:
        return "AIFS mejor" if diff < 0 else "AIFS peor"
    return "sin diferencia detectable"


def _row(sub: pd.DataFrame, label: str, kind: str, n_boot: int, seed: int) -> dict:
    ae_i, ae_a = sub["ae_ifs"].to_numpy(), sub["ae_aifs"].to_numpy()
    d = ae_a - ae_i
    ep = v.episodes(sub["valid_date"].to_numpy())
    lo, hi = v.bootstrap_ci(lambda i: d[i].mean(), ep, n=n_boot, seed=seed)
    w = sub["winner"]
    wa, wi, ties = int((w == "aifs").sum()), int((w == "ifs").sum()), int((w == "empate").sum())
    p = sign_test_p(wa, wi)
    diff = float(d.mean())
    return {
        "lead": label,
        "kind": kind,
        "n": len(sub),
        "mae_ifs": float(ae_i.mean()),
        "mae_aifs": float(ae_a.mean()),
        "diff": diff,
        "lo": lo,
        "hi": hi,
        "bias_ifs": float((sub["ifs"] - sub["obs"]).mean()),
        "bias_aifs": float((sub["aifs"] - sub["obs"]).mean()),
        "wins_aifs": wa,
        "wins_ifs": wi,
        "ties": ties,
        "p_sign": p,
        "verdict": verdict(lo, hi, p, diff),
    }


def paired_summary(table: pd.DataFrame, n_boot: int = 1000, seed: int = 0) -> pd.DataFrame:
    """Per lead (``"1"``..) and lead group (``"1–3"``..) x kind (event, control, all)."""
    rows = []
    leads = sorted(int(x) for x in table["lead"].unique())
    scopes = [(str(L), [L]) for L in leads]
    scopes += [(g, [L for L in leads if lo <= L <= hi]) for g, (lo, hi) in GROUPS.items()]
    for kind in KINDS:
        base = table if kind == "all" else table[table["kind"] == kind]
        for label, ls in scopes:
            sub = base[base["lead"].isin(ls)]
            if len(sub):
                rows.append(_row(sub, label, kind, n_boot, seed))
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


# --- report -----------------------------------------------------------------------------------


def common_period(table: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    d = pd.to_datetime(table["valid_date"])
    return d.min(), d.max()


def native_025(table: pd.DataFrame) -> bool:
    """All common valid dates on or after 2024-02-29 (IFS open data at 0.25 deg native)."""
    return bool(len(table)) and bool((pd.to_datetime(table["valid_date"]) >= NATIVE_025_FROM).all())


RULE_LINES = [
    (
        "- Casos comunes: ids presentes en las dos tiendas, con la entrada válida (estado 0) en ambos modelos y "
        "ERA5 disponible, por anticipación. Variable: media de la caja ponderada por cos(lat), pronóstico "
        "determinista de cada modelo y ERA5 como referencia."
    ),
    (
        "- Error absoluto por caso y anticipación; diferencia = error AIFS − error IFS (negativa: AIFS mejor). "
        "Gana el menor error; empate si la diferencia de errores es < 0,05 mm."
    ),
    (
        "- IC 95 % de la diferencia media por bootstrap de episodios (fechas a ±3 días agrupadas, {n_boot} "
        "remuestreos, semilla {seed}). Prueba de signos bilateral exacta sobre los pares sin empate."
    ),
    (
        "- Veredicto: «AIFS mejor/peor» solo si, en esa anticipación y para los casos de evento, el IC de la "
        "diferencia media excluye 0 Y p de signos < 0,05; si no, «sin diferencia detectable». Los grupos "
        "1–3, 4–7 y 8–10 días promedian los pares de sus anticipaciones."
    ),
]


def _fmt(x, d: int = 2) -> str:
    return v._f(x, d)


def _ci(row) -> str:
    return v._ci(row["diff"], row["lo"], row["hi"])


def _pfmt(p: float) -> str:
    if np.isnan(p):
        return "—"
    return "<0,001" if p < 0.001 else _fmt(p, 3)


def _lead_order(label: str) -> tuple[int, int]:
    return (1, 0) if not label.isdigit() else (0, int(label))


def render_md(table: pd.DataFrame, summary: pd.DataFrame, meta: dict) -> str:
    """Spanish report: verdict, source, rule, summary per kind, table per event case, warnings."""
    L = ["# F5.4 — AIFS contra IFS en los eventos de Neuquén", ""]
    L += ["## Veredicto", "", PLACEHOLDER, ""]
    ev = summary[summary["kind"] == "event"]
    n_ev = int(meta.get("n_event", table[table["kind"] == "event"]["case"].nunique()))
    ev_leads = ev[ev["lead"].str.isdigit()]
    for g in GROUPS:
        r = ev[ev["lead"] == g]
        if r.empty:
            continue
        r = r.iloc[0]
        L.append(
            f"- Eventos, {g} días (n = {r['n']} pares): MAE IFS {_fmt(r['mae_ifs'])} mm, "
            f"MAE AIFS {_fmt(r['mae_aifs'])} mm, dif. AIFS−IFS {_ci(r)} mm; "
            f"victorias A/I/E {r['wins_aifs']}/{r['wins_ifs']}/{r['ties']}, "
            f"p signos {_pfmt(r['p_sign'])}: {r['verdict']}."
        )
    for word in ("AIFS mejor", "AIFS peor", "sin diferencia detectable"):
        ls = [r["lead"] for _, r in ev_leads.iterrows() if r["verdict"] == word]
        L.append(f"- Anticipaciones (eventos) con «{word}»: {', '.join(ls) if ls else 'ninguna'}.")
    L.append(
        f"- Potencia baja: {n_ev} casos de evento (n chico); un «sin diferencia detectable» no "
        "prueba que los modelos sean equivalentes."
    )
    L += ["", "## Fuente y alcance", ""]
    L.append(
        "- IFS y AIFS: ECMWF open data (espejo AWS ecmwf-forecasts), CC-BY-4.0; corrida 00 UTC, "
        "un solo pronóstico determinista por modelo."
    )
    L.append(
        f"- Casos comunes: {meta.get('n_event', '?')} de evento y {meta.get('n_control', '?')} de "
        f"control; fechas válidas {meta.get('first', '?')} a {meta.get('last', '?')}."
    )
    if meta.get("native_025"):
        L.append(
            "- Todas las fechas comunes son ≥ 2024-02-29: en este período IFS y AIFS están ambos a "
            "0,25° nativos, sin interpolación."
        )
    else:
        L.append(
            "- ATENCIÓN: hay fechas comunes anteriores a 2024-02-29, cuando IFS estaba a 0,4° "
            "(interpolado a 0,25°)."
        )
    L.append(f"- Referencia: {meta.get('obs_source', 'ERA5')}.")
    L += ["", "## Regla fijada antes de correr", ""]
    for line in RULE_LINES:
        L.append(
            line.replace("{n_boot}", str(meta.get("n_boot", 1000))).replace(
                "{seed}", str(meta.get("seed", 0))
            )
        )
    L.append("")
    for kind, label in (
        ("event", "Casos de evento"),
        ("control", "Casos de control"),
        ("all", "Todos los casos"),
    ):
        sub = summary[summary["kind"] == kind]
        if sub.empty:
            continue
        L += [f"## Resumen: {label}", ""]
        header = [
            "Anticipación (días)", "n", "MAE IFS", "MAE AIFS", "Dif. AIFS−IFS [IC]",
            "Sesgo IFS", "Sesgo AIFS", "Victorias A/I/E", "p signos",
        ]  # fmt: skip
        if kind == "event":
            header.append("Veredicto")
        rows = []
        for _, r in sub.sort_values("lead", key=lambda s: s.map(_lead_order)).iterrows():
            row = [
                r["lead"],
                str(r["n"]),
                _fmt(r["mae_ifs"]),
                _fmt(r["mae_aifs"]),
                _ci(r),
                _fmt(r["bias_ifs"]),
                _fmt(r["bias_aifs"]),
                f"{r['wins_aifs']}/{r['wins_ifs']}/{r['ties']}",
                _pfmt(r["p_sign"]),
            ]
            if kind == "event":
                row.append(r["verdict"])
            rows.append(row)
        L += v._table(header, rows)
    L += ["## Tabla por evento", ""]
    ev_t = table[table["kind"] == "event"]
    for case, g in ev_t.groupby("case", sort=False):
        first = g.iloc[0]
        eid = first["event_id"] or str(case)
        L += [f"### {eid} — {pd.Timestamp(first['valid_date']).date()} (caso {case})", ""]
        rows = [
            [
                str(int(r["lead"])),
                _fmt(r["obs"]),
                _fmt(r["ifs"]),
                _fmt(r["aifs"]),
                _fmt(r["ifs"] - r["obs"]),
                _fmt(r["aifs"] - r["obs"]),
            ]
            for _, r in g.sort_values("lead").iterrows()
        ]
        L += v._table(
            [
                "Anticipación (días)",
                "Obs. (mm)",
                "IFS (mm)",
                "AIFS (mm)",
                "Error IFS (mm)",
                "Error AIFS (mm)",
            ],
            rows,
        )
    L += [
        "## Advertencias",
        "",
        (
            f"- n chico: {n_ev} eventos (y pocos episodios independientes); los IC son anchos y la "
            "potencia para detectar diferencias es baja."
        ),
        "- Un solo pronóstico determinista por modelo y caso: no se evalúa el ensamble ni la probabilidad.",
        (
            "- ERA5 es un reanálisis, no lluvia medida, y comparte linaje con IFS (modelo y asimilación): "
            "puede favorecer a IFS en anticipaciones cortas."
        ),
        "- Esto es retrospectivo, no un sistema de alerta; los avisos oficiales son del SMN, la AIC y Defensa Civil.",
        "",
    ]
    return "\n".join(L)

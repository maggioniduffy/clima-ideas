"""Spanish report ``reports/06/F6.2.md`` generated from ``F6.2.json``."""

from __future__ import annotations

import math
from pathlib import Path

from clima_nqn.stages.seasonal import data

REPORT_MD = Path("../reports/06/F6.2.md")
TARGET_LABEL = {
    "rain": "lluvia en la cordillera (caja 12004)",
    "ar": "cantidad de ríos atmosféricos por mes",
    "flow12004": "caudal medio mensual, estación 12004",
    "flow12010": "caudal medio mensual, estación 12010",
    "rain12010": "lluvia en la cordillera (caja 12010, sensibilidad)",
}
MODEL_LABEL = {
    "logit": "logística (agrupada en anticipaciones)",
    "lgbm": "LightGBM (agrupado en anticipaciones)",
    "logit_lead": "logística por anticipación (sensibilidad)",
    "logit_flow": "logística con caudal reciente (sensibilidad; no disponible en la emisión)",
}
REF_LABEL = {
    "clim": "climatología 1/3",
    "clim_emp": "climatología empírica",
    "persist": "persistencia",
    "persist_cond": "persistencia condicional",
    "enso": "análogos ENSO",
}
PHASE_LABEL = {"nino": "El Niño", "nina": "La Niña", "neutral": "neutro", "": "sin dato"}


def _f(x, nd=3) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def _sk(r: dict | None, key: str = "rps") -> str:
    if not r:
        return "—"
    return f"{_f(r[f'{key}_skill'], 3)} [{_f(r[f'{key}_lo'], 3)}; {_f(r[f'{key}_hi'], 3)}]"


def _idx(skill: list[dict]) -> dict:
    return {(r["model"], r["ref"], r["lead"]): r for r in skill}


def _table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _skill_table(res: dict, model: str, key: str = "rps", refs=tuple(REF_LABEL)) -> str:
    ix = _idx(res["skill"])
    rows = []
    for lead in [*data.LEADS, "all"]:
        rows.append(
            [
                ("todas" if lead == "all" else str(lead)),
                *[_sk(ix.get((model, r, lead)), key) for r in refs],
            ]
        )
    return _table(["Anticipación (meses)", *[REF_LABEL[r] for r in refs]], rows)


def build_markdown(js: dict, meta: dict) -> str:
    out: list[str] = []
    w = out.append
    res = js["results"]
    w("# F6.2 — Modelo estacional de terciles (Experimental)\n")
    w(
        "> **No es una alerta oficial.** Es una evaluación retrospectiva (hindcast) para usuarios técnicos; el modelo "
        "estacional es *Experimental* y nunca se promueve a «Perspectiva de riesgo». Avisos oficiales: SMN, AIC y "
        "Defensa Civil.\n"
    )
    w("## Resumen\n")
    verd = js["verdicts"]
    wins = [v for v in verd if v["beats_climatology"] and v["lead"] != "all"]
    w(
        f"- Pruebas por anticipación (4 variables × 6 anticipaciones × 2 modelos = {len([v for v in verd if v['lead'] != 'all' and v['target'] in data.MAIN_TARGETS])}); "
        f"con IC al 95 % se esperan ~5 % de falsos positivos por azar."
    )
    if wins:
        w(
            "- Superan a la climatología (RPSS > 0 con IC que excluye 0, esquema externo, contra 1/3 y contra la climatología empírica):"
        )
        for v in wins:
            w(
                f"  - {TARGET_LABEL[v['target']]}, anticipación {v['lead']}, {v['model']}: RPSS {_f(v['rpss_vs_clim'])} "
                f"[{_f(v['ci_vs_clim'][0])}; {_f(v['ci_vs_clim'][1])}]"
            )
        for t in sorted({v["target"] for v in wins}):
            ix = _idx(res["outer"][t]["skill"])
            w(
                f"- {TARGET_LABEL[t]}: RPSS de la logística contra la persistencia condicional (usa el caudal del mes anterior, que "
                "operativamente no está disponible en la emisión) en anticipaciones 1 / 2 / 3: "
                + " / ".join(_sk(ix.get(("logit", "persist_cond", k))) for k in (1, 2, 3))
                + "."
            )
    else:
        w(
            "- Ninguna variable ni anticipación supera a la climatología con IC al 95 % que excluya 0: "
            "solo se emitirán baselines (climatología, persistencia, análogos ENSO)."
        )
    w("")
    w("## Fuentes y período\n")
    w(
        _table(
            ["Dato", "Fuente", "Licencia", "Período"],
            [
                [
                    "Nieve (`sd`, equivalente en agua) y humedad de suelo (`swvl1–3`)",
                    "ERA5 0,25° (Copernicus C3S) vía ARCO-ERA5; **no es ERA5-Land** (sensibilidad con ERA5-Land pendiente)",
                    "CC-BY 4.0",
                    meta.get("state_period", "—"),
                ],
                [
                    "Lluvia diaria de la caja (F2.5 `forcing.parquet`)",
                    "ERA5 vía ARCO-ERA5, caja aproximada, sin verificar",
                    "CC-BY 4.0",
                    "1980–2025",
                ],
                [
                    "Ríos atmosféricos (F1.3 `events.parquet`)",
                    "TECA BARD 6.0.0 sobre ERA5; meses completos del catálogo",
                    "CC-BY 4.0",
                    "1980-01 a 2025-12",
                ],
                [
                    "Caudal medio mensual 12004 y 12010 (F2.5)",
                    "SNIH; mes válido con ≥ 25 días",
                    "uso público SNIH, sin verificar",
                    "1980–2026-03",
                ],
                [
                    "ONI (solo baseline ENSO y puntaje por fase)",
                    "NOAA CPC",
                    "dominio público",
                    "ONI revisado, no la versión publicada en su momento: sin verificar archivo histórico",
                ],
            ],
        )
    )
    w(
        "Cajas de la cuenca alta: rectángulos aproximados, sin verificar (`snow.UPSTREAM_BOXES`: 12004, 12010, 12012). "
        "«Lluvia en la cordillera» = lluvia de la caja de la cuenca alta del Neuquén (12004), no el polígono de la cordillera.\n"
    )
    if meta.get("input_hashes"):
        w(
            "Hash (SHA-256 abreviado) de las entradas: "
            + ", ".join(f"`{k}` {v}" for k, v in meta["input_hashes"].items())
            + "\n"
        )
    w("## Método\n")
    w(
        "- Emisión el día 1 de cada mes M, de 1980-05 a 2025-12 (el primer mes con ventana completa de 90 días). "
        "Anticipación k = 1..6 apunta al mes M+k−1 (la 1 es el mes que empieza en la emisión)."
    )
    w(
        "- Objetivo: tercil (bajo / medio / alto) del valor del mes objetivo. Bordes por mes calendario **solo con los años de "
        "entrenamiento** de cada partición. Empates (recuentos de ríos atmosféricos): regla de rango medio, "
        "p = (n_menores + 0,5·n_iguales)/n; bajo si p < 1/3, alto si p > 2/3. Fracción de etiquetas de test empatadas: "
        + ", ".join(
            f"{TARGET_LABEL[t]} {_f((res['outer'][t] or {}).get('tied_fraction'), 2)}"
            for t in js["targets"]
            if res["outer"].get(t)
        )
        + "."
    )
    w(
        "- Entradas disponibles en la emisión (cada una con `available_on` ≤ fecha de emisión; una aserción y un unit lo "
        "verifican): nieve y humedad de suelo de ERA5 a las 00 UTC de emisión − 5 días (latencia de ERA5T) en las 3 cajas; "
        "lluvia de la caja en los 30 y 90 días que terminan en el día emisión − 6 (el total diario de D termina a las 00 UTC "
        "de D+1); seno y coseno del mes objetivo; anticipación. Anomalías por mes de emisión, estandarizadas con "
        "estadísticos de entrenamiento. **Sin ENSO como entrada.**"
    )
    w(
        "- Caudal reciente (último mes con ≥ 25 días antes de la emisión) solo como sensibilidad. Operativamente SNIH tiene "
        "~236 días de retraso (F6.1): **no se puede usar en la emisión**."
    )
    w(
        "- Modelos: regresión logística multinomial (L2, C ∈ {0,01; 0,1; 1}, estandarizada) y LightGBM multiclase "
        "(num_leaves ∈ {4, 8}, n_estimators ∈ {50, 120}, learning_rate 0,05, min_child_samples 50), un modelo por variable "
        "**agrupado en las 6 anticipaciones con la anticipación como entrada**; logística por anticipación como sensibilidad."
    )
    w(
        "- Baselines: climatología 1/3; climatología empírica (frecuencias de entrenamiento por mes calendario, +1 de Laplace; "
        "importa con empates); persistencia (tercil del último mes completo disponible: M−2 para lluvia y ríos atmosféricos por la "
        "latencia de 5 días, M−1 para caudal, retrospectivo; probabilidad 1 en ese tercil); persistencia condicional "
        "(frecuencias de entrenamiento del tercil objetivo dado el tercil persistente y la anticipación; baseline extra más fuerte); "
        "análogos ENSO (frecuencias de entrenamiento del mismo mes de emisión, anticipación y fase del ONI en la emisión, +1 de Laplace; "
        "ONI de la temporada centrada 3 meses antes del mes de emisión)."
    )
    w("## Validación\n")
    w(
        "- **Externa:** cada año hidrológico (abril–marzo, 1981–2024) es una vez el test (muestras con emisión en ese año). "
        "Se sacan del entrenamiento todas las muestras cuya emisión o mes objetivo cae en [inicio − 6 meses, fin + 6 meses), "
        "incluidos los objetivos del test que pasan de marzo (hasta agosto)."
    )
    w(
        "- **Interna, anidada:** solo con los años del entrenamiento externo, origen móvil expansivo (≥ 15 años iniciales, "
        "bloques de 5 años; entrenamiento antes del bloque y con sus meses objetivo terminados); elige hiperparámetros y el conjunto "
        "de variables entre {estado, estado+lluvia, estado+lluvia+mes}. El año de test externo nunca interviene."
    )
    w(
        "- **Control:** origen móvil puro (entrenar con todo lo anterior al año t, predecir t, t = 1995–2024)."
    )
    w(
        f"- Puntajes: RPS (3 categorías ordenadas) y Brier del tercil superior e inferior. Skill = 1 − puntaje_modelo / puntaje_referencia, "
        f"sobre los promedios por año de test; IC 95 % por bootstrap de años ({meta.get('n_boot', 1000)} remuestreos, semilla {meta.get('seed')}). "
        "«Supera a la climatología» = RPSS > 0 con IC que excluye 0 en el esquema externo, contra 1/3 **y** contra la climatología empírica.\n"
    )

    for scheme, title in (
        ("outer", "Esquema externo (un año afuera con separación)"),
        ("control", "Control (origen móvil puro)"),
    ):
        w(f"## Resultados — {title}\n")
        w("RPSS del modelo contra cada baseline (IC 95 %). Positivo = mejor que la referencia.\n")
        for t in data.MAIN_TARGETS:
            r = res[scheme].get(t)
            if not r:
                continue
            w(f"### {TARGET_LABEL[t]}\n")
            w(
                f"Muestras de test {r['n_test_samples']}, años {r['years'][0]}–{r['years'][1]}; frecuencia de clases en test "
                f"(bajo/medio/alto) {', '.join(_f(x, 2) for x in r['class_freq_test'])}.\n"
            )
            for m in ("logit", "lgbm"):
                w(f"**{MODEL_LABEL[m]}**\n")
                w(_skill_table(r, m))
            ix = _idx(r["skill"])
            rows = []
            for m in ("logit", "lgbm"):
                rows.append(
                    [
                        MODEL_LABEL[m],
                        _sk(ix.get((m, "clim", "all")), "bs_upper"),
                        _sk(ix.get((m, "clim", "all")), "bs_lower"),
                    ]
                )
            w("Skill de Brier (BSS) contra climatología 1/3, todas las anticipaciones:\n")
            w(_table(["Modelo", "BSS tercil superior", "BSS tercil inferior"], rows))
            bl = _idx(r["baseline_vs_clim"])
            w(
                "Baselines contra la climatología 1/3 (RPSS, todas las anticipaciones): "
                + "; ".join(
                    f"{REF_LABEL[b]} {_sk(bl.get((b, 'clim', 'all')))}" for b in list(REF_LABEL)[1:]
                )
                + ".\n"
            )

    w("## RPS por año de test (esquema externo)\n")
    w(
        "RPS medio del año (todas las anticipaciones); menor es mejor. Fase = ONI DJF del año hidrológico (revisado).\n"
    )
    for t in data.MAIN_TARGETS:
        r = res["outer"].get(t)
        if not r:
            continue
        w(f"### {TARGET_LABEL[t]}\n")
        cols = ["logit", "lgbm", "clim", "clim_emp", "persist", "persist_cond", "enso"]
        rows = [
            [
                str(y["year"]),
                PHASE_LABEL.get(y["phase"], y["phase"]),
                *[_f(y.get(f"rps_{c}")) for c in cols],
            ]
            for y in r["by_year"]
        ]
        w(_table(["Año", "Fase", *cols], rows))
        rows = [
            [
                str(y["year"]),
                *[
                    _f(y.get(f"bs_upper_{c}")) + " / " + _f(y.get(f"bs_lower_{c}"))
                    for c in ("logit", "lgbm", "clim", "persist", "enso")
                ],
            ]
            for y in r["by_year"]
        ]
        w("Brier superior / inferior por año:\n")
        w(_table(["Año", "logit", "lgbm", "clim", "persist", "enso"], rows))

    w("## Skill por fase ENSO del año (esquema externo)\n")
    w(
        "RPSS de todas las anticipaciones por fase (ONI DJF del año hidrológico; la fase se usa solo para agrupar el puntaje).\n"
    )
    for t in data.MAIN_TARGETS:
        r = res["outer"].get(t)
        if not r:
            continue
        w(f"### {TARGET_LABEL[t]}\n")
        rows = []
        for ph in ("nino", "nina", "neutral"):
            for m in ("logit", "lgbm"):
                cells = []
                n_y = 0
                for ref in REF_LABEL:
                    hit = [
                        x
                        for x in r["by_phase"]
                        if x["phase"] == ph and x["model"] == m and x["ref"] == ref
                    ]
                    cells.append(_sk(hit[0]) if hit else "—")
                    n_y = hit[0]["n_years"] if hit else n_y
                rows.append([PHASE_LABEL[ph], str(n_y), m, *cells])
        w(_table(["Fase", "Años", "Modelo", *[REF_LABEL[x] for x in REF_LABEL]], rows))

    w("## Sensibilidades (esquema externo)\n")
    for t in data.SENSITIVITY_TARGETS:
        r = res["outer"].get(t)
        if r:
            w("### Caja 12010 para la lluvia\n")
            for m in ("logit", "lgbm"):
                w(f"**{MODEL_LABEL[m]}**\n")
                w(_skill_table(r, m, refs=("clim", "clim_emp", "persist_cond", "enso")))
    for m in ("logit_lead", "logit_flow"):
        w(f"### {MODEL_LABEL[m]}\n")
        for t in data.MAIN_TARGETS:
            r = res["outer"].get(t)
            if not r:
                continue
            w(f"{TARGET_LABEL[t]}:\n")
            w(_skill_table(r, m, refs=("clim", "clim_emp")))
    w(
        "ERA5-Land en lugar de ERA5 0,25° para nieve y humedad de suelo: **pendiente**, sin verificar.\n"
    )

    w("## Hiperparámetros elegidos\n")
    for t in data.MAIN_TARGETS:
        r = res["outer"].get(t)
        if not r or not r["configs"]:
            continue
        cf = [c for c in r["configs"] if c["model"] in ("logit", "lgbm")]
        w(
            f"- {TARGET_LABEL[t]}: "
            + "; ".join(
                f"{m}: "
                + ", ".join(
                    f"{k}×{n}" for k, n in sorted(_count(cf, m).items(), key=lambda x: -x[1])[:4]
                )
                for m in ("logit", "lgbm")
            )
        )
    w("")
    w("## Veredicto por variable y anticipación\n")
    w(
        "Esquema externo; «supera» exige RPSS > 0 con IC 95 % que excluye 0 contra 1/3 y contra la climatología empírica (`F6.2.json`: `verdicts[].beats_climatology`).\n"
    )
    rows = [
        [
            TARGET_LABEL[v["target"]],
            str(v["lead"]),
            v["model"],
            _f(v["rpss_vs_clim"]),
            f"[{_f(v['ci_vs_clim'][0])}; {_f(v['ci_vs_clim'][1])}]",
            _f(v["rpss_vs_clim_emp"]),
            f"[{_f(v['ci_vs_clim_emp'][0])}; {_f(v['ci_vs_clim_emp'][1])}]",
            "sí" if v["beats_climatology"] else "no",
        ]
        for v in verd
        if v["target"] in data.MAIN_TARGETS
    ]
    w(
        _table(
            ["Variable", "Ant.", "Modelo", "RPSS vs 1/3", "IC", "RPSS vs empírica", "IC", "Supera"],
            rows,
        )
    )
    w("## Modelo final\n")
    w(meta.get("final_note", "—") + "\n")
    w("## Advertencias\n")
    for line in (
        "No es una alerta oficial; consultar SMN, AIC y Defensa Civil.",
        "Experimental: el estacional nunca se promueve; el resto del proyecto es retrospectivo.",
        "ERA5 0,25°, no ERA5-Land; las cajas son rectángulos aproximados, sin verificar.",
        "ONI revisado, no la versión publicada en su momento: sin verificar archivo histórico.",
        "El caudal reciente no está disponible en la emisión (SNIH ~236 días de retraso, F6.1); su uso es solo sensibilidad.",
        "Con 44 años de test hay poca muestra efectiva por mes; los IC son anchos y muchas pruebas simultáneas dejan falsos positivos esperables.",
        "Posibles tendencias o regulación del caudal (represas) pueden inflar el skill sobre la climatología de terciles fijos: sin verificar.",
        "Entradas históricas son reanálisis, no pronósticos: el modelo no usa pronósticos GEFS ni ENSO pronosticado.",
    ):
        w(f"- {line}")
    w("\n## Lectura\n\n(pendiente de revisión)\n")
    return "\n".join(out)


def _count(cfgs: list[dict], model: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cfgs:
        if c["model"] != model:
            continue
        key = f"{c['fset']}/" + ",".join(
            f"{k}={c[k]}" for k in ("C", "num_leaves", "n_estimators") if k in c
        )
        out[key] = out.get(key, 0) + 1
    return out


def write_markdown(js: dict, meta: dict, path: Path = REPORT_MD) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown(js, meta))
    return path

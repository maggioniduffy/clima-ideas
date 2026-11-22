# Fase 5 — Predicción retrospectiva

Estado: hecha (todas las tareas; capas hindcast-verification y hindcast-analogs publicadas el 2026-11-22) · Depende de: 1 (mitad ríos atmosféricos), 3 (mitad convección) · Refs: `docs/architecture.md`

## Pregunta

¿Los pronósticos veían venir los eventos de las fases 1 y 3, y con cuántos días de anticipación?

## Datos

Reforecasts GEFS (AWS Open Data), ECMWF open data (IFS, AIFS) para eventos recientes, ERA5 (agua precipitable,
CAPE, convergencia).

## Tareas

Primero la mitad de ríos atmosféricos (solo necesita el catálogo F1.3); la de convección se suma al cerrar la fase 3.

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F5.1 ✅ | Ingesta de pronósticos para las fechas de eventos y días de control | Sonnet escribe, Haiku corre | Zarr por modelo y anticipación |
| F5.2 ✅ | Verificación por días de anticipación, separada en ríos atmosféricos y convección | Haiku analiza, Sonnet codifica métricas | Curvas de acierto + unit de métricas |
| F5.3 ✅ | Clasificador de "día de riesgo" (LightGBM) vs. climatología y regresión logística | Sonnet | Brier y PR-AUC en test temporal, no exactitud |
| F5.4 ✅ | AIFS vs. IFS en los eventos neuquinos | Haiku | Tabla por evento y anticipación |
| F5.5 ✅ | Análogos: días ERA5 más parecidos a cada evento y qué pasó | Sonnet | Unit de búsqueda; capa de análogos |
| F5.6 ✅ | Tablero de verificación en el visor | Sonnet | e2e: elegir modelo, evento y anticipación |
| F5.7 ✅ | Acierto por fase ENSO; fase y ONI como variables del clasificador F5.3 | Haiku analiza, Sonnet agrega variables | Curvas por fase + Brier con y sin ENSO |
| F5.8 ✅ | Tabla de la compuerta de evidencia (`plan/06-forecast.md`, criterios 1–3) para "día de riesgo": por región y anticipación, BSS vs. climatología y vs. regresión logística con IC bootstrap por evento, eventos independientes en test (agrupados también entre regiones), diagrama de confiabilidad, POD y FAR | Haiku corre, Sonnet codifica | Tabla con veredicto por región y anticipación + unit de agrupación de eventos y de anticipaciones contiguas |
| F5.9 ✅ | Propuesta (2026-11-13): comprobar si el IVT se puede calcular con los niveles de ECMWF open data y GEFS (variables, niveles, resolución, latencia) | Haiku | Anotado en `docs/research/data-access.md` con fuente; si no se puede, F5.10 y F6.9 no se hacen |
| F5.10 ✅ | Propuesta (2026-11-13), depende de F5.9: acierto por anticipación del IVT pronosticado frente a la lluvia pronosticada en los eventos del catálogo F1.3 | Haiku analiza, Sonnet codifica métricas | Curvas de IVT y de lluvia lado a lado, misma métrica y mismos eventos |

## Entregable

Acierto según anticipación por tipo de evento; hipótesis a medir: los ríos atmosféricos se ven días antes y la
convección casi no.

La fase 5 es la evidencia de la perspectiva de riesgo (`plan.md`, Rumbo 7): F5.8 dice qué anticipaciones pueden
pasar a la fase 6 como perspectiva y cuáles quedan "Experimental".

## Avance

- F5.1 (2026-11-22): `clima-nqn hindcast cases | fetch | combine` (`backend/src/clima_nqn/stages/hindcast/`),
  workflow `hindcast-forecasts.yml`, datos en la rama `data/f51-forecasts`. Casos: día UTC del IVT máximo de cada
  evento F1.3 y un día de control por evento, mismo mes, sin río atmosférico a ±3 días (semilla 20261122). Lluvia
  diaria por anticipación 1–10 (horas (24(L−1), 24L] de la corrida de 00 UTC), recortada a −41..−36 / −71,5..−68:
  - GEFSv12 reforecast, 5 miembros, 2000–2019 (no hay corridas de 2020): 202 eventos + 202 controles, 20 199 de
    20 200 entradas.
  - ECMWF IFS (espejo AWS desde 2023-01-28; 0,4° interpolado a 0,25° hasta 2024-02-28): 23 + 23 casos.
  - AIFS (desde 2024-02-29): 10 + 16 casos. `tp` en m o en kg m⁻² según el mensaje; las corridas de marzo de
    2024 vienen en grilla gaussiana reducida y se interpolan (sin comparar con otra fuente).
  Primera mirada (media de la caja, sin verificar contra lo observado, eso es F5.2): GEFS pronostica 7,8 mm en
  días de evento a 1 día y 3,5 mm a 10 días, contra ~1,7 mm en controles a todas las anticipaciones.

- F5.2, mitad ríos atmosféricos (2026-11-22): `clima-nqn hindcast observe | verify`
  (`stages/hindcast/observe.py`, `verify.py`), informe `reports/05/F5.2.md` + `.json`, ERA5 de caja por fecha en
  `reports/05/F5.2-obs.csv`. Referencia ERA5, horas D 01…D+1 00 UTC (misma ventana que la anticipación), media de la
  caja por cos(lat); IC por bootstrap de episodios. GEFS, eventos: CRPSS vs. climatología con IC > 0 de 1 a 7 días
  (0,80 → 0,25), cruza 0 de 8 a 10; subestima de forma creciente desde 6 días (−1,5 → −3,7 mm sobre 7,2). IFS: CRPSS
  de eventos > 0 hasta 5 días (n 23). AIFS (n 10): sin conclusión. ETS/AUC evento vs. control > 0 hasta 10 días en 1,
  5 y 10 mm: cota optimista por cómo se eligieron los controles.
- F5.4 (2026-11-22): `clima-nqn hindcast compare`, informe `reports/05/F5.4.md`. 10 eventos + 16 controles comunes
  (2024-03…2025-11, ambos a 0,25° nativo): sin diferencia detectable entre AIFS e IFS en ninguna anticipación (regla:
  IC excluye 0 y signos p < 0,05). A 7 días, indicio sin verificar de AIFS peor (IC [0,7; 6,8] mm, p 0,11).

- F5.10 (2026-11-22): `clima-nqn hindcast fetch --variable ivt` (GEFS c00, 8 niveles 1000–300 hPa, rama
  `data/f510-ivt`) y `hindcast verify-ivt`, informe `reports/05/F5.10.md`. Sobre todos los casos, el IVT pronosticado
  conserva acierto 1–2 días más que la lluvia (Spearman +0,06…+0,10 con IC > 0 a 6–8 días; CRPSS-rango > 0 hasta
  6–7 días contra 6). Dentro de los eventos, la lluvia ordena mejor la intensidad. El AUC evento contra control
  favorece al IVT por construcción y no se usa como evidencia.

- F5.3 (2026-11-22): `clima-nqn hindcast riskday`, informe `reports/05/F5.3.md`; pronósticos de todos los días en
  `data/f53-alldays` (364 790 de 364 800 entradas) y medias regionales de ERA5 en `reports/05/F5.3-obs.csv`. La
  logística le gana a la climatología con IC hasta 9 días (cordillera norte), 10 (sur) y 7 (Confluencia), y
  LightGBM no le gana a la logística. Río atmosférico: 27–38 % de los días ≥ p95 en la cordillera y 48–69 % con p99;
  en Confluencia domina la convección (48 %, 87 % en DJF). El contraste por mecanismo dentro de cada región queda
  sin verificar (< 20 eventos de río atmosférico en test). Cierra también la mitad de convección de F5.2.

- F5.7 (2026-11-22): `clima-nqn hindcast enso-skill`, informe `reports/05/F5.7.md`. Sin señal de ENSO en el acierto
  por fase (la diferencia Niño − Niña excluye 0 solo a 5 días; la regla pedía 3 contiguas). El ONI conocido a la
  fecha de la corrida no mejora el clasificador de F5.3 en ninguna de 30 combinaciones.

- F5.8 (2026-11-22): `clima-nqn hindcast gate`, informe `reports/05/F5.8.md`. Persistencia = Markov de entrenamiento
  (decisión del usuario). La logística pasa el hindcast (BSS > 0 con IC contra climatología y persistencia, 118
  eventos agrupados, anticipaciones contiguas) hasta 9 días en la cordillera norte, 10 en la sur y 7 en Confluencia;
  el resto queda "Experimental". Sensibilidad: p90 9/10/10, p98 7/7/5. LightGBM no supera a la logística (criterio
  3). ~14 eventos independientes por temporada mayo–septiembre. El tope por anticipación (bin con ≥ 20 días) no era
  monótono (1,0 a 1 día, 0,1–0,5 a 2); desde el 2026-11-22 (decisión del usuario) rige el tope con bins agrupando L−1, L
  y L+1, no creciente en L: 100 % hasta 3–4 días y 30–40 % a 10 (columna nueva de `reports/05/F5.8.md`; el resto del
  informe no cambió).
- F5.5 (2026-11-22): `clima-nqn hindcast analogs-library | analogs | analogs-layer`, workflow
  `hindcast-analogs.yml`, rama `data/f55-analogs`, informe `reports/05/F5.5.md`. IVT diario ERA5 1980–2025, 10
  análogos por evento F1.3: el 42 % de los días análogos fue río atmosférico contra 5 % del baseline al azar
  (diferencia 0,37 [0,34; 0,39]; k = 5 y 20 dan 0,41 y 0,32). Lluvia ERA5 de los análogos en la cordillera 3–4 veces
  la del baseline. IMERG no cubre la cordillera ("sin dato"); en Confluencia IMERG y ERA5 dan signos opuestos (sin
  verificar).
- F5.6 (2026-11-22): capa `hindcast-verification` (`clima-nqn hindcast verification-layer`) y panel
  `HindcastPanel`: modelo, evento y anticipación; pronóstico contra ERA5, curva de acierto, tabla de la compuerta y
  análogos. e2e `web/e2e/hindcast.spec.ts`. Capas en R2; el panel llega a la web en línea al desplegar desde `main`.

## Abierto

- F5.3, decisiones del usuario (2026-11-22), fijadas antes de correr:
  - Día de riesgo: lluvia diaria media de la región en ERA5 ≥ p95 de los días de entrenamiento (sensibilidad p90 y
    p98), en 3 regiones: cordillera norte y sur (polígono F1 cortado en −38,5) y Confluencia (caja de F3.6).
  - Ríos atmosféricos y convección no se separan: en cada región, cada día de riesgo se clasifica por mecanismo
    (río atmosférico F1.3 > convectivo, con cp/tp de ERA5 ≥ 0,5 > otro) y se compara su preponderancia y su acierto.
    Esto reemplaza la mitad de convección de F5.2.
  - Pronósticos de todos los días 2000–2019 (GEFSv12 reforecast, 5 miembros, grilla −41,25…−36 / −72…−67,5) en la
    rama `data/f53-alldays`. Test 2015–2019.
- F5.2, mitad convección: se resuelve en F5.3, por mecanismo y en todos los días (decisión del 2026-11-22).
  ERA5 sigue siendo una referencia débil para convección (F3.4); contrastar con IMERG queda como sensibilidad posible.

- Licencia de GEFS (2026-11-22, F6.1): NODD abierta con atribución; reforecast GEFSv12 2000–2020 con APCP e IVT calculable.
- F5.9 (2026-11-22): IVT calculable en GEFS (operativo y reforecast) e IFS/AIFS; detalle en `reports/06/F6.1-latency.md`.
- F5.7 es la comprobación ENSO de esta fase: una tabla, sin más peso (ver `plan.md`, Rumbo 1).
- Partición temporal estricta para evitar fuga entre entrenamiento y test.

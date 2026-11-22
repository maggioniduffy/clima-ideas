# Fase 5 — Predicción retrospectiva

Estado: en curso (F5.1 y F5.9 hechas) · Depende de: 1 (mitad ríos atmosféricos), 3 (mitad convección) · Refs: `docs/architecture.md`

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
| F5.2 | Verificación por días de anticipación, separada en ríos atmosféricos y convección | Haiku analiza, Sonnet codifica métricas | Curvas de acierto + unit de métricas |
| F5.3 | Clasificador de "día de riesgo" (LightGBM) vs. climatología y regresión logística | Sonnet | Brier y PR-AUC en test temporal, no exactitud |
| F5.4 | AIFS vs. IFS en los eventos neuquinos | Haiku | Tabla por evento y anticipación |
| F5.5 | Análogos: días ERA5 más parecidos a cada evento y qué pasó | Sonnet | Unit de búsqueda; capa de análogos |
| F5.6 | Tablero de verificación en el visor | Sonnet | e2e: elegir modelo, evento y anticipación |
| F5.7 | Acierto por fase ENSO; fase y ONI como variables del clasificador F5.3 | Haiku analiza, Sonnet agrega variables | Curvas por fase + Brier con y sin ENSO |
| F5.8 | Tabla de la compuerta de evidencia (`plan/06-forecast.md`, criterios 1–3) para "día de riesgo": por región y anticipación, BSS vs. climatología y vs. regresión logística con IC bootstrap por evento, eventos independientes en test (agrupados también entre regiones), diagrama de confiabilidad, POD y FAR | Haiku corre, Sonnet codifica | Tabla con veredicto por región y anticipación + unit de agrupación de eventos y de anticipaciones contiguas |
| F5.9 ✅ | Propuesta (2026-11-13): comprobar si el IVT se puede calcular con los niveles de ECMWF open data y GEFS (variables, niveles, resolución, latencia) | Haiku | Anotado en `docs/research/data-access.md` con fuente; si no se puede, F5.10 y F6.9 no se hacen |
| F5.10 | Propuesta (2026-11-13), depende de F5.9: acierto por anticipación del IVT pronosticado frente a la lluvia pronosticada en los eventos del catálogo F1.3 | Haiku analiza, Sonnet codifica métricas | Curvas de IVT y de lluvia lado a lado, misma métrica y mismos eventos |

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

## Abierto

- Licencia de GEFS (2026-11-22, F6.1): NODD abierta con atribución; reforecast GEFSv12 2000–2020 con APCP e IVT calculable.
- F5.9 (2026-11-22): IVT calculable en GEFS (operativo y reforecast) e IFS/AIFS; detalle en `reports/06/F6.1-latency.md`.
- F5.7 es la comprobación ENSO de esta fase: una tabla, sin más peso (ver `plan.md`, Rumbo 1).
- Partición temporal estricta para evitar fuga entre entrenamiento y test.

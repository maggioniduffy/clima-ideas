# Fase 5 — Predicción retrospectiva

Estado: pendiente · Depende de: 1 (mitad ríos atmosféricos), 3 (mitad convección) · Refs: `docs/architecture.md`

## Pregunta

¿Los pronósticos veían venir los eventos de las fases 1 y 3, y con cuántos días de anticipación?

## Datos

Reforecasts GEFS (AWS Open Data), ECMWF open data (IFS, AIFS) para eventos recientes, ERA5 (agua precipitable,
CAPE, convergencia).

## Tareas

Primero la mitad de ríos atmosféricos (solo necesita el catálogo F1.3); la de convección se suma al cerrar la fase 3.

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F5.1 | Ingesta de pronósticos para las fechas de eventos y días de control | Sonnet escribe, opencode corre | Zarr por modelo y anticipación |
| F5.2 | Verificación por días de anticipación, separada en ríos atmosféricos y convección | opencode analiza, Sonnet codifica métricas | Curvas de acierto + unit de métricas |
| F5.3 | Clasificador de "día de riesgo" (LightGBM) vs. climatología y regresión logística | Sonnet; advisor si hace falta (partición temporal) | Brier y PR-AUC en test temporal, no exactitud |
| F5.4 | AIFS vs. IFS en los eventos neuquinos | opencode | Tabla por evento y anticipación |
| F5.5 | Análogos: días ERA5 más parecidos a cada evento y qué pasó | Sonnet | Unit de búsqueda; capa de análogos |
| F5.6 | Tablero de verificación en el visor | Sonnet | e2e: elegir modelo, evento y anticipación |
| F5.7 | Acierto por fase ENSO; fase y ONI como variables del clasificador F5.3 | opencode analiza, Sonnet agrega variables | Curvas por fase + Brier con y sin ENSO |
| F5.8 | Tabla de la compuerta de evidencia (`plan/06-forecast.md`, criterios 1–3) para "día de riesgo": por región y anticipación, BSS vs. climatología y vs. regresión logística con IC bootstrap por evento, eventos independientes en test (agrupados también entre regiones), diagrama de confiabilidad, POD y FAR | opencode corre, Sonnet codifica | Tabla con veredicto por región y anticipación + unit de agrupación de eventos y de anticipaciones contiguas |

## Entregable

Acierto según anticipación por tipo de evento; hipótesis a medir: los ríos atmosféricos se ven días antes y la
convección casi no.

La fase 5 es la evidencia de la perspectiva de riesgo (`plan.md`, Rumbo 7): F5.8 dice qué anticipaciones pueden
pasar a la fase 6 como perspectiva y cuáles quedan "Experimental".

## Abierto

- Licencia de GEFS sin verificar: confirmarla antes de F5.1.
- F5.7 es la comprobación ENSO de esta fase: una tabla, sin más peso (ver `plan.md`, Rumbo 1).
- Partición temporal estricta para evitar fuga entre entrenamiento y test.

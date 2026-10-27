# Fase 5 — Predicción retrospectiva

Estado: pendiente · Depende de: 1, 3 · Refs: `docs/architecture.md`

## Pregunta

¿Los pronósticos veían venir los eventos de las fases 1 y 3, y con cuántos días de anticipación?

## Datos

Reforecasts GEFS (AWS Open Data), ECMWF open data (IFS, AIFS) para eventos recientes, ERA5 (agua precipitable,
CAPE, convergencia).

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F5.1 | Ingesta de pronósticos para las fechas de eventos y días de control | Sonnet escribe, opencode corre | Zarr por modelo y anticipación |
| F5.2 | Verificación por días de anticipación, separada en ríos atmosféricos y convección | opencode analiza, Sonnet codifica métricas | Curvas de acierto + unit de métricas |
| F5.3 | Clasificador de "día de riesgo" (LightGBM) vs. climatología y regresión logística | Sonnet | Brier y PR-AUC en test temporal, no exactitud |
| F5.4 | AIFS vs. IFS en los eventos neuquinos | opencode | Tabla por evento y anticipación |
| F5.5 | Análogos: días ERA5 más parecidos a cada evento y qué pasó | Sonnet | Unit de búsqueda; capa de análogos |
| F5.6 | Tablero de verificación en el visor | Sonnet | e2e: elegir modelo, evento y anticipación |

## Entregable

Acierto según anticipación por tipo de evento; hipótesis a medir: los ríos atmosféricos se ven días antes y la
convección casi no.

## Abierto

- Partición temporal estricta para evitar fuga entre entrenamiento y test.

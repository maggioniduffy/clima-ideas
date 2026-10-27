# Fase 3 — Convección en la meseta y la Confluencia

Estado: pendiente · Depende de: 0 · Refs: `docs/architecture.md`

## Pregunta

¿Cada cuánto se repite una lluvia como la de abril de 2014 y cuánto la subestiman los productos globales?

## Datos

IMERG 30 min (2000–hoy), SMN Neuquén Aero, estaciones AIC (Plottier). Acceso horario según F0.8.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F3.1 | Ingesta IMERG recortado a la Confluencia y meseta | Sonnet escribe, opencode corre | Zarr 2000–hoy |
| F3.2 | Ingesta de estaciones con control de calidad | Sonnet | Parquet + unit de QC |
| F3.3 | Curvas IDF (duraciones 30 min–24 h) estación vs. IMERG | Sonnet | Unit con serie sintética de cuantiles conocidos |
| F3.4 | Sesgo de IMERG en eventos conocidos; corrección por cuantiles | opencode analiza, Sonnet implementa | Informe de sesgo + función QM testeada |
| F3.5 | Capa: curva IDF lado a lado + replay del temporal de abril de 2014 | Sonnet | e2e: replay y comparación |
| F3.6 | Frecuencia de días convectivos extremos por fase ENSO (F0.10), primavera y verano | opencode analiza | Tabla con n de años, test de permutación y "sin verificar" donde no alcance |

## Entregable

Curva IDF de Neuquén capital, estación e IMERG lado a lado, con el sesgo medido.

## Abierto

- Sin lluvia horaria de estación, IDF solo con IMERG y marcada así.

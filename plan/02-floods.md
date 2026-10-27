# Fase 2 — Crecidas de ríos

Estado: pendiente · Depende de: 1, acceso a caudales (F0.8) · Refs: `docs/architecture.md`

## Pregunta

¿Qué tan raras fueron las crecidas grandes y qué parte explican los ríos atmosféricos o la lluvia sobre nieve?

## Datos

Caudales de los ríos Neuquén, Limay, Agrio y Curi Leuvú (BDHI, AIC). Estación aguas arriba de las presas.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F2.1 | Ingesta de caudales diarios con control de huecos | Sonnet escribe, opencode descarga | Parquet por estación + reporte de huecos |
| F2.2 | Máximos anuales y GEV con intervalo de confianza (`pyextremes`) | Sonnet | Unit: recupera parámetros de una GEV sintética |
| F2.3 | Etiquetar crecidas mayores con el catálogo F1.3 y lluvia sobre nieve | opencode | Tabla de crecidas con causa probable |
| F2.4 | Capa: estaciones + panel de período de retorno y serie | Sonnet | e2e: elegir estación, ver curva y crecidas |
| F2.5 | ML (alta): LSTM de caudal diario; preentreno en CAMELS-CL, ajuste en Neuquén; baselines GR4J y persistencia | Sonnet implementa, opencode entrena, Opus revisa métricas | NSE/KGE en test vs. baselines |
| F2.6 | Ficha de crecida: pronóstico LSTM de próximos días con incertidumbre vs. observado | Sonnet | e2e sobre un evento pasado |
| F2.7 | Máximos anuales y caudal estacional por fase ENSO; GEV con ONI como covariable vs. estacionaria | Sonnet | Comparación por verosimilitud + unit con GEV sintética dependiente de covariable |

## Entregable

Períodos de retorno con IC para una estación natural, crecidas etiquetadas por causa, LSTM comparado.

## Abierto

- Si no hay caudal accesible, la fase se reduce a ERA5-Land y se marca así. Decide el usuario.
- Efecto de presas: usar solo estaciones aguas arriba para la GEV.

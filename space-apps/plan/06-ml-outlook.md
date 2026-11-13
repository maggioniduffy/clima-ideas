# Fase 6 — Predicción experimental

Estado: pendiente · Depende de: 2, 5 · Refs: `../plan/06-forecast.md` (Validación F6.2, F6.4, F6.6)

Experimental: nadie la usa para decidir. Mide si un modelo predice la actividad de fuego mejor que la
climatología.

## Pregunta

¿Cuál es la probabilidad de que el próximo mes tenga más focos que la mediana del área (terciles)?

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| SA6.1 | Variables: ONI y su pronóstico, SPEI reciente, FWI, anomalía de focos del mes previo, mes del año; días con río atmosférico si existe 5b | Sonnet | Unit: ninguna variable con fecha de disponibilidad posterior a la de emisión |
| SA6.2 | Baselines: climatología, persistencia y análogos de años con la misma fase ENSO | Sonnet | Unit |
| SA6.3 | Regresión logística y LightGBM validados con el esquema F6.2 | Sonnet implementa, opencode entrena | RPS y Brier por año de test vs. cada baseline |
| SA6.4 | Registro congelado de predicciones, como clima-ideas F6.4 | Sonnet | Unit: no se edita ni se emite con fecha pasada |
| SA6.5 | Capa "Experimental" con probabilidad, incertidumbre, skill y aviso fijo "Experimental, no es una alerta" | Sonnet | e2e: ver predicción, skill y aviso |

## Reglas

Horizonte máximo: 6 meses. Nada de proyecciones de décadas; eso requiere escenarios climáticos y queda fuera
de alcance.

Si un modelo no supera a la climatología, se informa así y la capa lo muestra.

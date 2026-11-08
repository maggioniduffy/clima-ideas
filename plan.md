# Plan de desarrollo: Neuquén, lluvias extremas y aluviones

Índice de fases. Fuente de alcance: `NEUQUEN_PLAN.md` (el resto de las ideas del repo queda fuera), más ENSO como
eje de análisis en las fases 1, 2, 3 y 5 y la fase 6 de predicción experimental (pedido del usuario, 2026-10-27).
Producto: pipeline Python por etapa que publica capas en un visor web.

## Fases

| # | Fase | Archivo | Depende de | Estado |
|---|---|---|---|---|
| 0 | Bases: monorepo, visor, API, contrato de capas, acceso a datos | [plan/00-foundations.md](plan/00-foundations.md) | — | hecha |
| 1 | Ríos atmosféricos en la cordillera | [plan/01-atmospheric-rivers.md](plan/01-atmospheric-rivers.md) | 0 | casi hecha (F1.1–F1.4, F1.6–F1.8 hechas; F1.5 parcial: falta verificar fuentes) |
| 2 | Crecidas de ríos + LSTM de caudal | [plan/02-floods.md](plan/02-floods.md) | 1, datos de caudal | pendiente |
| 3 | Convección e IDF en la Confluencia | [plan/03-convection.md](plan/03-convection.md) | 0 | pendiente |
| 4 | Aluviones: cuencas chicas, HEC-RAS, emulador | [plan/04-debris-flows.md](plan/04-debris-flows.md) | 2, 3 | pendiente |
| 5 | Predicción retrospectiva | [plan/05-hindcast.md](plan/05-hindcast.md) | 1, 3 | pendiente |
| 6 | Predicción a futuro (experimental) | [plan/06-forecast.md](plan/06-forecast.md) | 0, 2, 5 | pendiente |

La fase 3 puede correr en paralelo a la 1–2. La investigación de acceso a datos (F0.8) arranca el día uno.

## Referencias

| Archivo | Cuándo leerlo |
|---|---|
| [docs/agents.md](docs/agents.md) | Al delegar: plantillas de prompt |
| [docs/architecture.md](docs/architecture.md) | Al tocar estructura, contrato de capas, API o tests |
| [docs/design.md](docs/design.md) | Al tocar UI: tokens, temas, reglas de interfaz |

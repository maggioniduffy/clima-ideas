# Plan: calendario de fuego armonizado MODIS + VIIRS

Desafío CONAE, NASA Space Apps Challenge 2026. Hackatón: 14–15/11/2026. Autor: Faustino Maggioni Duffy.
Producto: pipeline Python que arma una serie de focos de calor armonizada 2000–hoy en dos escalas (MODIS-equivalente y
VIIRS-equivalente, que sigue cuando MODIS se apague) y una app web con calendario
año×mes, anomalías, contexto ENSO y sequía, CSV descargable y una capa de predicción experimental.

Reusa de clima-ideas: [../docs/architecture.md](../docs/architecture.md),
[../docs/agents.md](../docs/agents.md), tareas de [../plan/00-foundations.md](../plan/00-foundations.md),
validación de [../plan/06-forecast.md](../plan/06-forecast.md). Diseño: [docs/design.md](docs/design.md).

## Fases

| # | Fase | Archivo | Depende de | Fechas | Estado |
|---|---|---|---|---|---|
| 0 | Bases, reglas del evento, acceso a datos | [plan/00-foundations.md](plan/00-foundations.md) | — | 29/10–1/11 | pendiente |
| 1 | Datos FIRMS: descarga, filtros, grilla | [plan/01-data.md](plan/01-data.md) | 0 | 30/10–3/11 | pendiente |
| 2 | Armonización MODIS–VIIRS + ML | [plan/02-harmonization.md](plan/02-harmonization.md) | 1 | 3/11–7/11 | pendiente |
| 3 | Calendario y análisis por área | [plan/03-calendar-analytics.md](plan/03-calendar-analytics.md) | 2 | 4/11–7/11 | pendiente |
| 4 | App web | [plan/04-web-app.md](plan/04-web-app.md) | 0, 3 | 4/11–10/11 | pendiente |
| 5 | ENSO, sequía y fuego | [plan/05-enso-drought.md](plan/05-enso-drought.md) | 3 | 7/11–11/11 | pendiente |
| 5b | Ríos atmosféricos y fuego (opcional) | [plan/05b-atmospheric-rivers.md](plan/05b-atmospheric-rivers.md) | 4 | 11/11–12/11 | pendiente |
| 6 | Predicción experimental | [plan/06-ml-outlook.md](plan/06-ml-outlook.md) | 2, 5 | 9/11–12/11 | pendiente |
| 7 | Entrega | [plan/07-submission.md](plan/07-submission.md) | 4 | 12/11–15/11 | pendiente |

**SA0.1 hecho ([docs/research/rules.md](docs/research/rules.md)): las reglas prohíben empezar a trabajar en el
desafío antes del 14/11.** Hasta entonces solo inscripción, sede, equipo y aprendizaje general; nada de código,
datos ni diseño del desafío. Las fases arrancan el 14/11, comprimidas a 48 h, y se revisan con las guías del
13/11. Inscripción: evento local virtual (alcanza 1 persona). Pendiente: consulta escrita al Local Lead sobre si se puede usar este plan y el material genérico de
clima-ideas.

## Mínimo para entregar

Fases 0–4 y 7: serie armonizada, calendario, anomalía y CSV. 5, 6 y 5b suman si llegan a tiempo, en ese orden.

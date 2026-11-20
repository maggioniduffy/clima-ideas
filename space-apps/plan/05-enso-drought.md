# Fase 5 — ENSO, sequía y fuego

Estado: pendiente · Depende de: 3, 0 (SA0.9) · Refs: `../plan/01-atmospheric-rivers.md` (eje ENSO)

## Pregunta

¿La fase ENSO, a través de la sequía, cambia cuánto se quema? Cadena: ENSO → anomalía de lluvia → sequía →
combustible seco → focos. Hipótesis a medir, no a afirmar: en el centro-norte de Argentina La Niña trae sequía
y más focos.

## Datos

ONI (SA0.9), SPI/SPEI a 3 y 6 meses (CHIRPS o ERA5, según SA0.8; sin verificar licencias), FWI de Copernicus
CEMS (sin verificar acceso).

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| SA5.1 | SPI/SPEI mensual por celda | Sonnet escribe, opencode corre | Unit contra valores de referencia publicados |
| SA5.2 | Calendario de focos partido por fase ENSO (mediana por mes en Niño, Niña, Neutro) | Sonnet | Unit sobre serie sintética |
| SA5.3 | Correlación con rezagos ONI → SPEI → focos por región, con IC bootstrap | opencode analiza, Sonnet codifica | `reports/05/SA5.3.md` + unit de rezagos |
| SA5.4 | UI: fila de fase ENSO bajo el calendario y sequía del área en el inspector, con fuente y período | Sonnet | e2e |

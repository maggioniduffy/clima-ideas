# Fase 1 — Ríos atmosféricos en la cordillera

Estado: pendiente · Depende de: 0 · Refs: `docs/architecture.md` (contrato de capas)

## Pregunta

¿Cuántos ríos atmosféricos llegan a la cordillera neuquina por año y cuánta lluvia extrema explican?

## Datos

ERA5 1980–hoy: componentes de IVT, precipitación, isoterma de 0 °C. Licencia según F0.8.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F1.1 | Script de descarga ERA5 (cdsapi) por recorte y variables, idempotente | Sonnet escribe, opencode corre | Zarr completo en `data/raw/era5/` |
| F1.2 | Detección con TECA BARD (o detector por umbral de IVT si F0.9 falló) | opencode corre, Opus valida | Máscara diaria de ríos atmosféricos |
| F1.3 | Catálogo: eventos que tocan el polígono de cordillera (fecha, duración, IVT máx., isoterma 0 °C) | Sonnet | Parquet + unit tests con máscara sintética |
| F1.4 | Fracción de días de lluvia extrema (p99) que coinciden con un evento | opencode | Informe con cifras, fuente y período |
| F1.5 | Contraste con literatura de ríos atmosféricos en los Andes | opencode | Tabla: nuestro conteo vs. publicado |
| F1.6 | Capa del visor: eventos en la línea de tiempo + replay de IVT por hora | Sonnet | e2e: elegir evento, reproducir, inspeccionar |
| F1.7 | ML (media): detector preentrenado tipo ClimateNet vs. BARD | opencode corre, Sonnet integra | Acuerdo entre métodos medido; opcional |

## Entregable

Catálogo de ríos atmosféricos + fracción de lluvia extrema explicada, visible como capa con replay.

## Abierto

- Umbral de "lluvia extrema" (p99 diario propuesto). Opus confirma tras F1.4.

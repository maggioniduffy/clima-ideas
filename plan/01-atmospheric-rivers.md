# Fase 1 — Ríos atmosféricos en la cordillera

Estado: en curso · Depende de: 0 · Refs: `docs/architecture.md` (contrato de capas)

## Pregunta

¿Cuántos ríos atmosféricos llegan a la cordillera neuquina por año y cuánta lluvia extrema explican?

## Datos

ERA5 1980–hoy: componentes de IVT, precipitación, isoterma de 0 °C. Licencia según F0.8.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F1.1 | Script de descarga ERA5 desde ARCO-ERA5 (Zarr público en Google Cloud, sin cola ni clave; `tools/teca/fetch_era5_ivt.py --source arco`) por recorte y variables, idempotente | Sonnet escribe, opencode corre | Zarr completo en `data/raw/era5/` |
| F1.2 | Detección con TECA BARD en jobs paralelos (matriz de GitHub Actions por año o por mes; BARD tarda ~2,5 h por año en el hemisferio sur) | opencode corre, Opus valida | Máscara diaria de ríos atmosféricos |
| F1.3 | Catálogo: eventos que tocan el polígono de cordillera (fecha, duración, IVT máx., isoterma 0 °C) | Sonnet | Parquet + unit tests con máscara sintética |
| F1.4 | Fracción de días de lluvia extrema (p99) que coinciden con un evento | opencode | Informe con cifras, fuente y período |
| F1.5 | Contraste con literatura de ríos atmosféricos en los Andes | opencode | Tabla: nuestro conteo vs. publicado |
| F1.6 | Capa del visor: eventos en la línea de tiempo + replay de IVT por hora | Sonnet | e2e: elegir evento, reproducir, inspeccionar |
| F1.7 | ML (media): detector preentrenado tipo ClimateNet vs. BARD | opencode corre, Sonnet integra | Acuerdo entre métodos medido; opcional |
| F1.8 | Ríos atmosféricos por fase ENSO (F0.10): conteo, IVT y lluvia por estación del año; test de permutación | opencode analiza, Sonnet codifica el test | Tabla Niño/Neutro/Niña con p-valor y n de años + unit del test |

## Entregable

Catálogo de ríos atmosféricos + fracción de lluvia extrema explicada, visible como capa con replay.

## Avance

- F1.1 código listo (2026-11-08): `clima-nqn era5 fetch` + workflow `era5.yml` (un job por año, hasta 20 en paralelo,
  64 lecturas concurrentes). Caja `NEUQUEN_BOX` -34,-74,-43,-66; horario; `viwve`, `viwvn`, `tp`, `deg0l`. Prueba
  real: enero 2023 a 2 horas/día, 62 pasos, ~80 MB/s en red. Año completo estimado ~15 min (sin verificar en Actions).
  Falta: `gh workflow run era5.yml -f years=1980-2025`, bajar artefactos y `clima-nqn era5 combine`.
- F1.2 código listo (2026-11-08): `teca.yml` con input `years` (matriz por año) y recorte a Neuquén con
  `tools/teca/crop_bard.py` (artefacto `bard-neuquen-<año>`). Falta: corrida 1980–2025 y validar el recorte con salida
  real de BARD.

## Abierto

- Pocos años por fase ENSO: informar n y no afirmar diferencias que el test no sostiene.

- Umbral de "lluvia extrema" (p99 diario propuesto). Opus confirma tras F1.4.

# Fase 1 — Ríos atmosféricos en la cordillera

Estado: en curso · Depende de: 0 · Refs: `docs/architecture.md` (contrato de capas)

## Pregunta

¿Cuántos ríos atmosféricos llegan a la cordillera neuquina por año y cuánta lluvia extrema explican?

## Datos

ERA5 1980–hoy: componentes de IVT, precipitación, isoterma de 0 °C. Licencia según F0.8.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F1.1 ✅ | Script de descarga ERA5 desde ARCO-ERA5 (Zarr público en Google Cloud, sin cola ni clave; `tools/teca/fetch_era5_ivt.py --source arco`) por recorte y variables, idempotente | Sonnet escribe, opencode corre | Zarr completo en `data/raw/era5/` |
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

- F1.1 hecha (2026-11-08): run 42437929137 de `era5.yml`, 1980–2025, 46 jobs verdes en 17 min. Artefactos
  `era5-neuquen-<año>` (~100 MB c/u, ~4,6 GB total, vencen 2027-02-06): Zarr horario de `viwve`, `viwvn`, `tp`,
  `deg0l` sobre `NEUQUEN_BOX` -34,-74,-43,-66, fuente ARCO-ERA5 (CC-BY 4.0). Cada job pasa el chequeo de completitud
  (eje de tiempo y variables). No se revisó el contenido fuera de Actions (esta sesión no llega al almacenamiento de
  artefactos): F1.3/F1.4 deben bajarlos dentro de Actions (`actions/download-artifact` con `run-id`).
- F1.2 código listo (2026-11-08): `teca.yml` con input `years` (matriz por año) y recorte a Neuquén con
  `tools/teca/crop_bard.py` (artefacto `bard-neuquen-<año>`). Falta: corrida 1980–2025 y validar el recorte con salida
  real de BARD.

## Abierto

- Pocos años por fase ENSO: informar n y no afirmar diferencias que el test no sostiene.

- Umbral de "lluvia extrema" (p99 diario propuesto). Opus confirma tras F1.4.

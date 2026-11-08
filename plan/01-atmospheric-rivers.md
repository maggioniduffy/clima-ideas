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
- F1.3 código listo (2026-11-08): `clima-nqn ar catalog` (`stages/ar/catalog.py`) + workflow `ar-catalog.yml`, que
  baja los artefactos de BARD y ERA5 por run id. Evento: pasos BARD de 6 h consecutivos con `ar_probability` ≥ 0,67 en
  alguna celda del polígono de cordillera (rectángulo 71,95–70 O, 36–41,1 S, aproximación sin verificar). Por evento:
  inicio, fin, duración, prob. máx., fracción de área, IVT máx. (valor, hora, celda), isoterma 0 °C máx. y media, lluvia
  media acumulada (mm) y fase ENSO del mes de inicio. 22 unit tests con datos sintéticos. Falta: correr sobre el run
  de BARD 1980–2025.
- F1.4 código listo (2026-11-08): `clima-nqn ar extremes` (`stages/ar/extremes.py`), corre en `ar-catalog.yml` después
  del catálogo y sube `F1.4.md` + `F1.4.json`. Día UTC (D 01:00 a D+1 00:00), lluvia media en el polígono. Principal:
  días ≥ p99 de todos los días; sensibilidad: p95, p99 por celda sobre días húmedos (≥ 1 mm), ventana ±1 día. Baseline:
  tasa base de días con río atmosférico (cociente frac/tasa base), IC de Wilson 95 %, por estación. 17 unit tests
  sintéticos. Falta: correr y pasar el informe a `reports/01/F1.4.md`.
- F1.5 parcial (2026-11-08): `reports/01/F1.5.md`, 9 estudios en tabla, **ninguno verificado en fuente primaria**
  (la red de la sesión no llega a doi.org ni a las revistas; cifras de resúmenes del buscador, marcadas así). Sin
  estudios con cifras para Neuquén/Comahue. Más comparables: ~50 % de lluvia diaria extrema con RA en Chile
  centro-sur (Valenzuela y Garreaud 2019) y 40–55 % de la lluvia anual por RA en la costa 37–47 S (Viale et al.
  2018). Falta: verificar en fuente primaria y completar la columna "nuestro valor" tras F1.3/F1.4.
- F1.6 código listo (2026-11-08): `clima-nqn ar layer` publica `data/processed/ar-events/` (manifiesto, eventos en
  JSON/Parquet, frames horarios de |IVT| en Float32 por evento) y la ruta `GET /layers/{id}/frames/{t}`. Visor: eventos
  en la línea de tiempo coloreados por IVT máx., lista en el panel, replay horario (play/pausa, paso, deslizador),
  inspector con campos del evento, fuente, período y valor de IVT por celda. e2e con capa falsa: 4/4. Corre en
  `ar-catalog.yml` (artefacto `ar-events-layer`). Falta: correr con datos reales y revisar escala (satura en
  800 kg m-1 s-1) y contraste del raster.
- F1.8 código listo (2026-11-08): `clima-nqn ar enso` (`stages/ar/enso.py`), corre en `ar-catalog.yml` y sube
  `F1.8.md` + `F1.8.json`. Por estación-año (DJF con diciembre del año anterior): n eventos, días con RA, IVT, fracción
  de lluvia por RA; fase ENSO por ONI medio de la estación (umbrales de `io/enso.py`). Test de permutación Niño−Niña
  (bilateral, p = (k+1)/(n+1)) y de 3 grupos (F de ANOVA), p ajustado por Benjamini-Hochberg; "diferencia sostenida"
  solo con p < 0,05. 12 unit tests sintéticos. Falta: correr con datos reales.
- F1.2 código listo (2026-11-08): `teca.yml` con input `years` (matriz por año) y recorte a Neuquén con
  `tools/teca/crop_bard.py` (artefacto `bard-neuquen-<año>`). Falta: corrida 1980–2025 y validar el recorte con salida
  real de BARD.

## Abierto

- Pocos años por fase ENSO: informar n y no afirmar diferencias que el test no sostiene.

- Umbral de "lluvia extrema" (p99 diario propuesto). Opus confirma tras F1.4.

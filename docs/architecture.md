# Arquitectura

## Estructura

```
backend/            uv, Python 3.12
  src/clima_nqn/
    stages/         ar/, floods/, convection/, debris/, hindcast/  (una carpeta por fase)
    io/             descargas e ingesta (ERA5, IMERG, caudales, GLO-30)
    layers/         escritura de capas + manifiesto
    api/            FastAPI, solo lectura de data/processed
  tests/            unit (rápidos) y slow (marcados)
web/                pnpm, Vite, React, TypeScript, deck.gl
  src/i18n/es.ts    todos los textos de UI
  src/theme/        tokens (ver docs/design.md)
  e2e/              Playwright
data/               raw/ interim/ processed/  (fuera de git)
reports/            informes de opencode por fase
```

## Flujo

`io` descarga → `stages/*` calcula → `layers` publica en `data/processed/<layer_id>/` → API sirve → visor dibuja.
Cada paso es un comando CLI idempotente (`clima-nqn <stage> <step>`).

## Contrato de capas

`data/processed/<layer_id>/manifest.json`:

```json
{
  "id": "ar-events",
  "title": "Ríos atmosféricos",
  "kind": "events | points | raster-frames | series | polygons",
  "source": "ERA5 (Copernicus)",
  "period": "1980-01-01/2025-12-31",
  "license": "CC BY 4.0",
  "updated_at": "ISO-8601",
  "files": ["events.parquet"]
}
```

Formatos: tablas en Parquet/GeoParquet; grillas en Zarr; frames para el visor en PNG o binario Float32.
La UI toma fuente y período del manifiesto.

`data/` no está en git. Las capas pesadas se construyen en Actions y se bajan a mano; sin ellas, el visor local
queda vacío o, con `CLIMA_NQN_DATA=e2e/fixtures/processed`, muestra solo los 2 eventos sintéticos de los fixtures.
Capa `ar-events` completa (433 eventos, ~37 MB), desde la corrida de `ar-catalog.yml`:

```
gh run download <run-id> -n ar-events-layer -D data/processed/ar-events
```

### Área del visor

El visor muestra todo el recorte ERA5 (`era5.NEUQUEN_BOX`: 34–43 °S, 74–66 °O), no solo la provincia: el raster de IVT
dibuja todas las celdas de la grilla de frames (37×33) y el relieve cubre el mismo rectángulo. El contorno provincial y
el marcador de Neuquén van encima como referencia. No hay franja ni recorte a la provincia (se quitó en noviembre de
2026); el catálogo de ríos atmosféricos sigue usando su polígono de cordillera, que es otra cosa.

Capa `relief` (Copernicus GLO-30), construida en local desde la raíz del repo:

```
cd backend && uv run clima-nqn dem fetch && uv run clima-nqn dem build
```

- `dem fetch` baja las 72 teselas de 1° del rectángulo a `data/raw/glo30` (~2,6 GB, bucket público de Copernicus).
  Las teselas sin DEM (océano: S35 W074 y S36 W074) devuelven 404 y quedan marcadas con un archivo `<tesela>.404`.
- `dem build` decima a paso 1/66° (66 muestras por tesela, ~1,7 km) y escribe `data/processed/relief/`
  (~305 000 puntos, ~3,7 MB). El paso es 1/66 y no 0,015 para que cada tesela tenga un número entero de muestras y la
  grilla coincida con el `step` que lee el visor.
- Desde un worktree, `data/` se resuelve dentro del worktree: pasar `--dest`/`--raw`/`--out` con la ruta del `data/`
  del checkout principal para reusar las teselas.
- Tras regenerar la capa, recargar el visor sin caché: el navegador puede seguir mostrando el `relief.bin` anterior.

### Caudales (SNIH)

Caudal medio diario de seis estaciones de la Red Hidrológica Nacional (Neuquén, Agrio, Curí Leuvú y Limay), del SNIH/SIPH
(Subsecretaría de Recursos Hídricos). Desde la raíz del repo:

```
cd backend && uv run clima-nqn flow fetch && uv run clima-nqn flow ingest
```

- `flow fetch` baja los datos a `data/raw/flow/` (`<id>.json` por estación y `stations.json` con la metadata y la fecha de
  consulta), en ventanas de 10 años y con ~1 s entre pedidos. `--station` (repetible) limita las estaciones.
- `flow ingest` no usa red: escribe `data/flow/<id>.parquet` (`date`, `q_m3s`, `qualifier`, `validated`; los huecos son
  filas NaN), `data/flow/stations.json` y el informe `reports/02/F2.1.md`.
- `flow gev` ajusta una GEV (`pyextremes`, MLE, IC 95 % por bootstrap) a los máximos anuales de las estaciones naturales
  (12004, 12010, 12012; 11803 queda fuera por regulada) y escribe `data/flow/gev/<id>.json` y `reports/02/F2.2.md`.
- `flow enso` (`--flow-dir`, `--enso`, `--out`, `--report`, `--station`, `--analysis-station`, `--n-perm`, `--addendum/--no-addendum`, `--addendum-n-perm`) compara máximos anuales y caudal
  abr–sep por fase de ENSO (permutación) y una GEV con ONI como covariable de la ubicación contra la estacionaria (LRT y AIC), con
  valores p ajustados por BH; escribe `data/flow/enso.json` y `reports/02/F2.7.md` con el veredicto para F6.2 y una adenda de robustez posterior al resultado
  (p de permutación, ONI rezagado JFM (un único valor trimestral, fechado en febrero), control de tendencia y 1953–2009; solo 12004 y 12010) que no cambia el veredicto. Necesita `enso fetch`.
- `flow snow-fetch` (`--flow-dir`, `--catalog`, `--out`, `--station`, `--workers`, `--retries`, `--retry-wait`) baja de ARCO-ERA5 (anónimo)
  el agua equivalente de nieve de ERA5 (`snow_depth`, 0,25°; no es ERA5-Land) a las 00 UTC de `[pico − 8, pico + 1]` de cada crecida
  dentro del período del catálogo, recortada a un rectángulo aproximado aguas arriba (sin verificar); escribe un Parquet
  (`data/raw/era5/snow-floods/snow-floods.parquet`), omite las ventanas ya guardadas y reintenta lecturas fallidas.
- `flow causes` (`--flow-dir`, `--gev-dir`, `--catalog`, `--snow`, `--out`, `--report`, `--station`, `--n-perm`) etiqueta los máximos anuales por
  causa probable (río atmosférico del catálogo F1.3 en `[pico − 3, pico]` y lluvia sobre nieve), con la sensibilidad a la ventana
  `w = 0..7` frente a la línea base por azar (permutación); escribe `data/flow/causes.json` y `reports/02/F2.3.md`. Sin archivo de nieve
  etiqueta solo por río atmosférico. Necesita el catálogo (`ar catalog`).
- Términos del SNIH (§7): citar al SIPH/SNIH como fuente, declarar la fecha de última actualización y no alterar el
  sentido original de los datos. El Parquet guarda fuente, URL y fecha de consulta en sus metadatos.

Capa `flood-stations` (F2.4), desde los Parquet de F2.1 y los JSON de F2.2:

```
cd backend && uv run clima-nqn flow layer
```

- `flow layer` (`--flow-dir`, `--gev-dir`, `--out`; por defecto `data/processed/flood-stations`) escribe `manifest.json` (kind `points`,
  fuente SNIH/SIPH, período = primera..última fecha entre estaciones, fecha de actualización en la licencia),
  `stations.json` y `stations/<id>.json`; todos figuran en `files` (la API solo sirve archivos del manifiesto).
- `stations.json`: `id` (texto), `lon`, `lat`, `value`, `name`, `river`, `area_km2`, `has_gev`, `regulated`. `value` es el caudal de
  período de retorno 100 años (m³/s) si la estación tiene GEV y el máximo diario observado si no; el mapa dimensiona el punto con él
  (radio 6–18 px, proporcional a √valor). Las reguladas (11803) se dibujan huecas y no tienen `gev`, `return_levels` ni `curve`.
- `stations/<id>.json`: `daily` (`start` y un valor por día con 1 decimal, `null` en huecos), `annual_maxima` y `top_floods` (5 mayores),
  y con GEV: `gev` (`irregular` si ξ ≥ 0,5), `return_levels` y `curve` (T de 1,1 a 200; el IC 95 % solo dentro del rango guardado, 2–100).
  Sin GEV, los períodos de retorno son empíricos (Weibull).
- El inspector abre el panel de la estación (curva T–caudal con banda IC, serie diaria con máximos anuales, mayores crecidas).

## API

`GET /health` · `GET /layers` · `GET /layers/{id}` · `GET /layers/{id}/data` · `GET /layers/{id}/frames/{t}` (binario Float32 del conjunto de frames `t`; en `ar-events`, `t` es el id del evento y el índice está en `frames/index.json`)

## Tests

- Unit con datos sintéticos de resultado conocido (pytest, vitest).
- e2e con capas falsas en `web/e2e/fixtures/` (Playwright), sin depender de datos reales.
- `@pytest.mark.slow`: datos reales o corridas largas; fuera de CI.

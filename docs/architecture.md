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
- Términos del SNIH (§7): citar al SIPH/SNIH como fuente, declarar la fecha de última actualización y no alterar el
  sentido original de los datos. El Parquet guarda fuente, URL y fecha de consulta en sus metadatos.

## API

`GET /health` · `GET /layers` · `GET /layers/{id}` · `GET /layers/{id}/data` · `GET /layers/{id}/frames/{t}` (binario Float32 del conjunto de frames `t`; en `ar-events`, `t` es el id del evento y el índice está en `frames/index.json`)

## Tests

- Unit con datos sintéticos de resultado conocido (pytest, vitest).
- e2e con capas falsas en `web/e2e/fixtures/` (Playwright), sin depender de datos reales.
- `@pytest.mark.slow`: datos reales o corridas largas; fuera de CI.

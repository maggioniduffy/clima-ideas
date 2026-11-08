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

## API

`GET /health` · `GET /layers` · `GET /layers/{id}` · `GET /layers/{id}/data` · `GET /layers/{id}/frames/{t}` (binario Float32 del conjunto de frames `t`; en `ar-events`, `t` es el id del evento y el índice está en `frames/index.json`)

## Tests

- Unit con datos sintéticos de resultado conocido (pytest, vitest).
- e2e con capas falsas en `web/e2e/fixtures/` (Playwright), sin depender de datos reales.
- `@pytest.mark.slow`: datos reales o corridas largas; fuera de CI.

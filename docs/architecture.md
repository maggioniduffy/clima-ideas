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

ERA5 regional (`clima-nqn era5 fetch`): `--variables` elige variables por nombre ERA5 o corto (`2m_temperature`/`t2m`, además de las cuatro por defecto de la fase 1: `viwve`, `viwvn`, `tp`, `deg0l`); sin la opción baja solo las cuatro. El workflow `era5.yml` expone `variables` y `name` (directorio y artefacto `era5-<name>-<año>`).

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
- `flow forcing` (`--era5-dir`, `--t2m-dir`, `--t2m-run-id`, `--dem-dir`, `--out`, `--station`) calcula, desde los Zarr locales de ERA5, el forzante
  diario (UTC) por cuenca para GR4J y el LSTM (F2.5): precipitación (`tp`, suma de D 01:00 a D+1 00:00), nivel de 0 °C, temperatura media,
  mínima y máxima (`t2m`) y PET de Oudin et al. (2005); promedio del rectángulo aproximado aguas arriba (sin verificar) ponderado por cos(lat) sobre las
  celdas con centro adentro. Escribe un Parquet largo (`data/flow/forcing.parquet`) con fuente, licencia, unidades y período en los metadatos, y
  `forcing.static.json` con área, elevación (GLO-30) y fracción sobre 2000 m. Los días son UTC y los de caudal locales (UTC−3), sin corregir. Omite
  los años ya guardados; sin `t2m` deja la temperatura y la PET en NaN, lista los años faltantes y un nuevo corrido con `--t2m-dir` los completa.
- `flow lstm-train` (`--mode sim|forecast`, `--split default|alt`, `--pretrain/--no-pretrain`, `--seeds`, `--epochs`, `--pretrain-epochs`, `--samples-per-epoch`, `--hidden`, `--seq-len`, `--station`, `--forcing`, `--flow-dir`, `--camels-dir`, `--camels-cache`, `--out-dir`, `--run-name`) entrena el LSTM de caudal diario (F2.5; PyTorch CPU,
  grupo opcional `ml`: `uv sync --group ml`; CI y API no lo instalan, y sin torch el comando lo avisa). Preentrena con CAMELS-CL (PANGAEA, DOI 10.1594/PANGAEA.894885, CC-BY-4.0; zips en `data/raw/camels-cl/zip`,
  forzante CR2MET con PET de Hargreaves, distinto del ERA5 de Neuquén; cuencas con ≥ 10 años de caudal válido) y ajusta en Neuquén con menor tasa de aprendizaje. Entradas: P, Tmedia, Tmin, Tmax, PET + log(área), elevación media y latitud;
  objetivo en mm/d normalizado con las filas de entrenamiento; pérdida NSE* por cuenca (Kratzert et al. 2019). `sim` usa solo forzante (ventana de 365 días); `forecast` suma el caudal observado hasta el día de emisión
  (más un canal de máscara) y lee los horizontes 1–7 con meteorología observada (ERA5), no un pronóstico operativo. Años hidrológicos (abril–marzo): `default` entrena 1980–2006, valida 2007–2013 y prueba 2014–2025; `alt` prueba 1980–1991,
  valida 1992–1998 y entrena 1999–2025; las ventanas de entrenamiento y validación nunca incluyen días de prueba. Conjunto de semillas (mediana) y banda del 90 % desde los cuantiles 5/95 % del log((obs+ε)/(pred+ε)) de validación (ε = 0,01 mm/d).
  Escribe `data/flow/lstm/<run-name>/` (pesos por semilla, `norm.json`, `quantiles.json`, `config.json`, `history.json`; archivos chicos).
- `flow streamflow-eval` (`--run-name`, `--forcing`, `--flow-dir`, `--out-dir`, `--station`) compara en los años de prueba el LSTM con GR4J+CemaNeige (calibrado en los años de entrenamiento, 3 semillas, la mejor KGE) y, en `forecast`,
  con persistencia: NSE/KGE por estación (y por horizonte 1–7), cobertura de la banda del 90 %, sensibilidad sin el año hidrológico 2023 y NSE del log(q + 0,01 × caudal medio de entrenamiento). Escribe `metrics.json` y `metrics.md` en la carpeta del run.
  Los días de caudal son locales y los del forzante UTC, sin corregir; se excluyen los primeros 365 días de cada serie.
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
- Ficha de crecida (F2.6, opcional): `cd backend && uv run --group ml clima-nqn flow lstm-hindcast --run-name fc-default` escribe
  `events/<id>.json` (JSON estricto, `null` en huecos) con las crecidas máximas anuales de los años de prueba del run (3 mayores por
  estación, más 2023-06-26 en 12004): `meta` (run, modo, semillas, años de prueba, forzante "ERA5 observada, no pronóstico", `caveat`
  "Pronóstico retrospectivo con meteorología observada (ERA5), no pronóstico operativo. Experimental, no es una alerta.", preentreno,
  `area_km2` y `area_note`, fuente y período) y `events[]`: `peak_date`, `peak_q`, `obs` (`start` y 22 valores, pico−14..pico+7, m³/s) e
  `issues[]` (8 días de emisión pico−7..pico: `days_before_peak`, `persistence`, `median`, `lo`, `hi` para plazos 1–7, m³/s; banda 90 %
  con los cuantiles de validación). Los archivos se agregan a `files` del manifiesto y el detalle de la estación lleva `has_events: true`;
  sin ellos la capa es válida y el panel no muestra la ficha. `flow layer` conserva los `events/` existentes.

## API

`GET /health` · `GET /layers` · `GET /layers/{id}` · `GET /layers/{id}/data` · `GET /layers/{id}/frames/{t}` (binario Float32 del conjunto de frames `t`; en `ar-events`, `t` es el id del evento y el índice está en `frames/index.json`)

## Publicación estática (F0.11)

En línea no hay API: `clima-nqn publish` sube `data/processed/` a Cloudflare R2 con objetos que imitan las rutas,
y la web estática los lee cuando el build tiene `VITE_DATA_URL` (sin esa variable usa `/api`, como en local).

| Ruta de la API | Objeto en R2 |
|---|---|
| `GET /layers` | `layers.json` (mismo JSON) |
| `GET /layers/{id}` | `{id}/manifest.json` |
| `GET /layers/{id}/data?file=f` | `{id}/{f}` (sin `file`: `files[0]`) |
| `GET /layers/{id}/frames/{t}` | `{id}/frames/{t}.bin` |

Se suben solo los manifiestos válidos, los archivos de `files` y los frames de capas que listan `frames/index.json`
(la misma regla que la API). Pasos del usuario, una vez:

1. Crear el bucket en R2 y darle acceso público (subdominio `r2.dev` o dominio propio).
2. CORS del bucket: `GET` y `HEAD` desde el dominio de Vercel (y `http://localhost:5173` para probar).
3. Crear un token de API de R2 con permiso de escritura solo en ese bucket.
4. Exportar `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` y `R2_BUCKET` (o ponerlas en `.env` en la
   raíz; `make` lo lee si existe), y correr `make publish`
   (`make publish-dry` lista lo que sube sin red).
5. En Vercel, `VITE_DATA_URL` = URL pública del bucket, y volver a desplegar.

## Tests

- Unit con datos sintéticos de resultado conocido (pytest, vitest).
- e2e con capas falsas en `web/e2e/fixtures/` (Playwright), sin depender de datos reales.
- `@pytest.mark.slow`: datos reales o corridas largas; fuera de CI.

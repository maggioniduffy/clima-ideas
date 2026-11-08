# TECA / BARD en GitHub Actions

Workflow manual `.github/workflows/teca.yml` (F0.9). Compila TECA 6.0.0 (solo apps C++, sin MPI ni bindings Python)
con conda-forge, verifica `teca_bayesian_ar_detect --help` y, opcionalmente, corre BARD (detector bayesiano de
ríos atmosféricos) sobre uno o varios años de ERA5. No corre en push ni PR.

## Lanzar

```sh
gh workflow run teca.yml -f years=2023 -f run_bard=true               # un año
gh workflow run teca.yml -f years=1980-2025 -f run_bard=true          # varios años en paralelo
gh workflow run teca.yml -f years=1980-1985,1990 -f run_bard=true -f keep_full=true
gh workflow run teca.yml -f run_bard=false                            # solo build y verificación
gh run list --workflow teca.yml
```

Parámetros: `years` (`2023`; acepta `2023`, `1980-2025`, `1980-1985,1990`; válido 1940..2026, se valida en el job `plan`),
`run_bard` (false), `hours` (`00,06,12,18`), `keep_full` (false), más `months`, `source` y `area`.

Cada año es un job de la matriz `bard` (`fail-fast: false`, `max-parallel: 20`): un año que falla no cancela a los demás. Los runners
hospedados admiten ~20 jobs concurrentes, así que 46 años (1980-2025) correrían en ~3 tandas de ~3-4 h cada una. Estimación sin verificar.

Después de BARD, cada job recorta a Neuquén (`tools/teca/crop_bard.py --area=-34,-74,-43,-66`, misma caja que `NEUQUEN_BOX` del backend)
y falla si el recorte no tiene pasos de tiempo. El recorte conserva `ar_probability` y `ar_binary_tag` sin cambios dentro de la caja
(lon normalizada a -180..180, lat ascendente) y agrega los atributos `crop_area` y `source_files`.

## Artefactos

```sh
gh run download <run-id> -n teca-build-logs        # cmake.log, build-tail.txt, verify.txt
gh run download <run-id> -n bard-neuquen-2023      # bard_neuquen_2023.nc (recorte) + logs (retención 90 días)
gh run download <run-id> -p 'bard-neuquen-*'       # todos los años
gh run download <run-id> -n bard-2023-<area>       # salida completa, solo si keep_full=true
```

Los logs se suben siempre, también si falla (el error exacto queda en `build-tail.txt` / `bard.log` / `crop.log`).
La salida completa del hemisferio (`bard-<año>-<área>`) solo se sube con `keep_full=true`.
La instalación de TECA se cachea (clave: tag + hash de `tools/teca/environment.yml`).

## Datos

ERA5 (single levels), flujos verticalmente integrados de vapor de agua (este y norte), por defecto área N -15, O -95, S -60, E -40,
mes a mes; `fetch_era5_ivt.py` calcula `IVT` = |(u, v)| en kg m-1 s-1. Fuente: ERA5, Copernicus Climate Change Service
(C3S), licencia CC-BY 4.0 (ver `docs/research/data-access.md`).

`--source` elige de dónde se leen los mismos campos ERA5 (el archivo `ivt_YYYY-MM.nc` es idéntico en formato):

- `arco` (por defecto): Zarr público ARCO-ERA5 de Google Cloud (`gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3`),
  acceso anónimo, sin cola ni credenciales. Los chunks son una hora global completa, así que se baja el campo global de cada
  paso pedido (~3 MB por variable y paso; ~9 GB por año a 4 horas/día) aunque se recorte al área. `--workers` por defecto: 2.
  El atributo `source` del archivo lo nombra como "ERA5 ... via ARCO-ERA5 (Google Cloud public dataset), CC-BY 4.0".
- `cds`: API de Copernicus (CDS). Se agregó porque CDS rechaza los pedidos con "Maximum number queued requests for this dataset
  has been reached" aun siendo secuenciales (runs 42263508664 y 42272035914), algo fuera de nuestro control. Hay que aceptar la
  licencia de ERA5 en CDS con la cuenta dueña del token y definir el secreto de repositorio `CDSAPI_KEY` (token personal de
  https://cds.climate.copernicus.eu/api); el workflow solo escribe las credenciales con `source: cds`.

`--area=N,W,S,E` (grados, O/E en -180..180; usar `=` porque los valores empiezan con `-`) cambia el área en ambas fuentes; por defecto
el círculo completo del hemisferio sur, `-10,-180,-80,179.75` (con `arco` no cuesta más descarga, los chunks ya son
globales). En el workflow es el input `area`. Motivo: BARD necesita un dominio amplio. En la ventana regional `-15,-95,-60,-40`
(run 42277026996, 2023) `ar_probability` nunca pasó de ~0.39 y no marcó ningún río atmosférico; con el hemisferio sur (run
42285391428, junio-julio 2023) llega a 1.0 y marca 30 de 244 pasos en una caja sobre Neuquén. Recortar a la región después de BARD.

Tamaño estimado por año (4 horas/día, grilla 0.25°, 221x181 puntos lon x lat): descarga con CDS ~0.4-0.8 GB (con `arco`, ~9 GB, ver arriba), IVT ~0.2-0.4 GB comprimido,
salida BARD de orden 0.3-1 GB. Estimación sin verificar.

## Caché y reintentos

La caché de IVT solo se usa cuando el run tiene un único año: con muchos años los 10 GB de caché del repo desalojarían la instalación de TECA (que se restaura con `fail-on-cache-miss`). Con un año, los meses descargados se cachean con clave `ivt-<año>-<horas>-a<área>-<run_id>`, donde `<área>` es el input `area` con `,` -> `_`
y `.` -> `p` (p. ej. `a-10_-180_-80_179p75`), así que áreas distintas nunca se mezclan. Agregar una versión (`ivt-v2-`) cuando
cambien `VARIABLES` o el `AREA` por defecto en `fetch_era5_ivt.py`. El run de BARD pasa `--periodic_in_x 1` solo si el área abarca
el círculo completo (E - O >= 359), si no 0, y la salida completa (opcional) se llama `bard-<año>-<área>`. Los `raw_*` parciales se borran antes de guardar
la caché. Los reintentos (ambas fuentes) esperan `--retry-wait` × intento (60 s por defecto). Con `cds` las descargas son secuenciales (`--workers 1`) porque CDS rechaza pedidos en paralelo; si la cola está llena
espera `--queue-wait` (300 s) y reintenta sin gastar reintentos, hasta `--queue-timeout` (3600 s) en total. Un solo run por rama a la vez
(`concurrency`). Si BARD no produce ningún `bard_*.nc`, el paso falla.

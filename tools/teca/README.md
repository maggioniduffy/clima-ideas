# TECA / BARD en GitHub Actions

Workflow manual `.github/workflows/teca.yml` (F0.9). Compila TECA 6.0.0 (solo apps C++, sin MPI ni bindings Python)
con conda-forge, verifica `teca_bayesian_ar_detect --help` y, opcionalmente, corre BARD (detector bayesiano de
ríos atmosféricos) sobre un año de ERA5. No corre en push ni PR.

## Lanzar

```sh
gh workflow run teca.yml -f year=2023 -f run_bard=true      # build + BARD
gh workflow run teca.yml -f run_bard=false                  # solo build y verificación
gh run list --workflow teca.yml
```

Parámetros: `year` (2023), `run_bard` (false), `hours` (`00,06,12,18`).

## Artefactos

```sh
gh run download <run-id> -n teca-build-logs   # cmake.log, build-tail.txt, verify.txt
gh run download <run-id> -n bard-2023         # máscara netCDF (ar_probability, ar_binary_tag) + logs
```

Los logs se suben siempre, también si falla (el error exacto queda en `build-tail.txt` / `bard.log`).
La instalación de TECA se cachea (clave: tag + hash de `tools/teca/environment.yml`).

## Datos

ERA5 (single levels), flujos verticalmente integrados de vapor de agua (este y norte), área N -15, O -95, S -60, E -40,
mes a mes; `fetch_era5_ivt.py` calcula `IVT` = |(u, v)| en kg m-1 s-1. Fuente: ERA5, Copernicus Climate Change Service
(C3S), licencia CC-BY 4.0 (ver `docs/research/data-access.md`). Hay que aceptar la licencia de ERA5 en CDS con la cuenta
dueña del token y definir el secreto de repositorio `CDSAPI_KEY` (token personal de https://cds.climate.copernicus.eu/api).

Tamaño estimado por año (4 horas/día, grilla 0.25°, 301x221 puntos): descarga ~0.4-0.8 GB, IVT ~0.2-0.4 GB comprimido,
salida BARD de orden 0.3-1 GB. Estimación sin verificar.

## Caché y reintentos

Los meses descargados se cachean con clave `ivt-<año>-<horas>-<run_id>`. Agregar una versión (`ivt-v2-`) cuando cambien `AREA` o
`VARIABLES` en `fetch_era5_ivt.py`, para no reutilizar archivos viejos. Los `raw_*` parciales se borran antes de guardar
la caché. Los reintentos de CDS esperan `--retry-wait` × intento (60 s por defecto). Las descargas son secuenciales (`--workers 1`) porque CDS rechaza pedidos en paralelo; si la cola está llena
espera `--queue-wait` (300 s) y reintenta sin gastar reintentos, hasta `--queue-timeout` (3600 s) en total. Un solo run por rama a la vez
(`concurrency`). Si BARD no produce ningún `bard_*.nc`, el paso falla.

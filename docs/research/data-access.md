# F0.8 — Acceso a datos · Neuquén (lluvia extrema / inundación / flujo de detritos)

Fecha de verificación: 2026-11-05

Método: verificación por `webfetch` sobre fuentes primarias (portales oficiales del proveedor). `websearch` devolvió "cancelled" en todos los intentos, por lo que no se usaron resultados de búsqueda. Todo lo que no se confirmó en la página primaria consultada queda como **sin verificar**. No se descargaron datasets.

## Tabla resumen

| Ítem | Estado | URL de acceso | Método | Resolución temporal / espacial | Licencia | Latencia / retención | Fuente primaria |
|---|---|---|---|---|---|---|---|
| BDHI (INA) — caudales | sin verificar | https://www.argentina.gob.ar/ina | sin verificar | sin verificar | sin verificar | — | Homepage INA verificada; entrada BDHI no visible en página consultada |
| AIC — caudales | sin verificar | https://www.aic.gob.ar/ ; https://www.aic.gob.ar/estaciones.aspx | portal (listado de estaciones) | sin verificar para serie histórica descargable | sin verificar | — | https://www.aic.gob.ar/estaciones.aspx lista estaciones con lat/lon; nota dice medias diarias (temperaturas, caudales, HR) y precipitación 06:00–06:00 |
| SMN Neuquén Aero — lluvia horaria | sin verificar | https://www.smn.gob.ar/ (403) | sin verificar | sin verificar (horaria pedida) | sin verificar | — | Homepage devolvió 403, sin evidencia primaria |
| AIC — lluvia (Neuquén / cuencas) | sin verificar | https://www.aic.gob.ar/estaciones.aspx | portal | Diaria 06:00–06:00 (nota de estaciones); horaria sin verificar | sin verificar | — | https://www.aic.gob.ar/estaciones.aspx |
| CAMELS-CL | sin verificar | sin verificar | sin verificar | sin verificar | sin verificar | — | Sin URL primaria confirmada |
| Licencia ERA5 | available | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels | portal + API (CDS) | Horaria; 0.25°×0.25° atmósfera | CC-BY licence | Actualización diaria; ver ERA5T abajo | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels |
| Licencia IMERG | available | https://gpm.nasa.gov/data/imerg ; https://gpm.nasa.gov/data/policy | portal + PPS FTP + Giovanni | Semihoraria, diaria, mensual; Early/Late/Final | "Freely available at all levels" (política GPM), sin licencia CC citada en página | Early 4 h; Late 14 h nominal; Final ~2.5 meses | https://gpm.nasa.gov/data/policy ; https://gpm.nasa.gov/data/imerg |
| Licencia GEFS | sin verificar | https://www.nco.ncep.noaa.gov/pmb/products/gefs/ (404) | sin verificar | sin verificar | sin verificar | sin verificar | Página GEFS específica devolvió 404; inventario GFS verificado no equivale a GEFS |
| Licencia ECMWF Open Data | available | https://www.ecmwf.int/en/forecasts/datasets/open-data ; https://data.ecmwf.int/forecasts/ | portal + cliente Python + espejos AWS/Azure/GCP | IFS 0.25° (y 0.1° desde 2026-10-20); AIFS 0.25° | CC-BY-4.0 | Ver fila operativa abajo | https://www.ecmwf.int/en/forecasts/datasets/open-data |
| Licencia AIFS | available | https://www.ecmwf.int/en/forecasts/datasets/open-data (productos AIFS) | portal (Open Data) | Semihoraria cada 6 h hasta 360 h; 0.25° | CC-BY-4.0 (misma que Open Data) | Ver fila operativa abajo | https://www.ecmwf.int/en/forecasts/datasets/open-data |
| Inventario de aluviones de Neuquén (SEGEMAR) | sin verificar | https://www.argentina.gob.ar/segemar | portal (SIGAM / mapas interactivos: acceso libre verificado); inventario específico sin verificar | sin verificar | sin verificar (SIGAM "libre y gratuita" según homepage) | — | https://www.argentina.gob.ar/segemar |
| Radar SINARAME en Neuquén | sin verificar | https://www.argentina.gob.ar/obras-publicas/hidricas/institucional/sinarame (403); https://radar.smn.gob.ar/ (error de transporte) | sin verificar | sin verificar | sin verificar | sin verificar | Intentos de verificación bloqueados |
| Mapas de suelo para SCS-CN | sin verificar | https://www.argentina.gob.ar/inta (plataforma https://geo.inta.gob.ar/) | portal (INTA Geo verificado); mapa de suelos específico sin verificar | sin verificar | sin verificar | — | https://www.argentina.gob.ar/inta |
| Mapas de cobertura para SCS-CN | sin verificar | https://www.argentina.gob.ar/inta | sin verificar | sin verificar | sin verificar | — | https://www.argentina.gob.ar/inta ; cobertura específica no confirmada |
| Fechas y magnitudes de crecidas/aluviones norte de Neuquén | sin verificar | sin verificar | sin verificar | sin verificar | sin verificar | — | Sin fuente primaria consultada que liste eventos; no inventado |
| Índice ENSO ONI | available | https://www.cpc.ncep.noaa.gov/data/indices/ ; https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt | portal (txt descarga directa) | Media corrida de 3 meses Niño 3.4 (ERSSTv6); serie 1950–actual | sin verificar (página no declara licencia) | — | https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt |
| Índice Niño 3.4 | available | https://www.cpc.ncep.noaa.gov/data/indices/ | portal (txt) | Mensual ERSSTv6 en Niño 3.4 (5°N–5°S, 170–120°O) vía detrend.nino34.ascii.txt | sin verificar | — | https://www.cpc.ncep.noaa.gov/data/indices/ |
| Índice SOI | available | https://www.cpc.ncep.noaa.gov/data/indices/soi | portal (txt) | Mensual: Tahiti − Darwin (1951–presente) | sin verificar | — | https://www.cpc.ncep.noaa.gov/data/indices/soi |
| Pronóstico ENSO IRI | available (portal); sin verificar API/licencia/resolución | https://iri.columbia.edu/ ; tránsito a https://forecast.ccsr.columbia.edu | portal | sin verificar (página raíz confirma enlace a pronóstico ENSO actual; no detalla resolución) | sin verificar | — | https://iri.columbia.edu/ |
| Pronóstico ENSO C3S | sin verificar | https://climate.copernicus.eu/ ; https://cds.climate.copernicus.eu/ | portal CDS (verificado); dataset estacional ENSO específico sin verificar | sin verificar | sin verificar | — | https://climate.copernicus.eu/ ; intentos CDS de dataset estacional devolvieron 404 |
| ECMWF Open Data operativo (latencia/retención) | available | https://www.ecmwf.int/en/forecasts/datasets/open-data | portal + cliente Python | Ciclos 00/06/12/18 UTC; AIFS cada 6 h hasta 360 h; IFS hasta 360 h (00/12) | CC-BY-4.0 | Retención ~2–3 días (12 corridas); 0.1° publicado 2 h después de 0.25°; AIFS en cuanto se produce; baja resolución al final del horario de difusión | https://www.ecmwf.int/en/forecasts/datasets/open-data |
| GEFS operativo (latencia/retención) | sin verificar | https://www.nco.ncep.noaa.gov/pmb/products/gefs/ (404) | sin verificar | sin verificar | sin verificar | sin verificar | Página GEFS específica 404; página GFS https://www.nco.ncep.noaa.gov/pmb/products/gfs/ verificada no (*) sustituye a GEFS |
| ERA5T (latencia) | available | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels | portal + API (CDS) | Horaria 0.25°; 1940–presente; GRIB | CC-BY | Latencia ~5 días; versión final 2–3 meses después | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels |
| ERA5-Land (latencia) | available (dataset); sin verificar cifra de latencia | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land | portal + API (CDS) | Horaria; 0.1°×0.1° nativa 9 km; ene 1950–presente; GRIB | CC-BY | Actualización diaria (página); días exactos sin verificar | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land |

Notas:

* (*) La página GFS verificada (https://www.nco.ncep.noaa.gov/pmb/products/gfs/) lista GRIB2 vía NOMADS https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod con resoluciones 0.25°/0.5°/1.0° y horarios 00/06/12/18. Esas cifras son de GFS, no de GEFS; por tanto no se trasladan a GEFS en la tabla.
* IMERG: Early 4 h, Late 14 h nominal (12 h reciente según FAQ), Final ~2.5 meses en sección de descargas (FAQ: ~3.5 meses). Se reporta el rango tal cual en la página https://gpm.nasa.gov/data/imerg.
* AIC estaciones: coordenadas y lista verificadas en https://www.aic.gob.ar/estaciones.aspx (ej. PASEO DE LA COSTA −38.977561, −68.047644; CHOS MALAL AEROP −37.441110, −70.225830). La página describe medias diarias y precipitación 06:00–06:00 del día anterior; no declara API, resolución para series históricas descargables ni licencia.
* INA: homepage verificada https://www.argentina.gob.ar/ina enumera Observatorio Hidrológico Nacional, RINA, enlace SINARAME, pero no exhibe endpoint BDHI. Por eso BDHI permanece sin verificar.
* SEGEMAR: homepage https://www.argentina.gob.ar/segemar declara "Banco Nacional de Información Geológica — Acceda de forma libre y gratuita al SIGAM y MAPAS INTERACTIVOS". No se confirmó inventario de aluviones de Neuquén (cobertura/resolución/licencia).
* INTA: homepage https://www.argentina.gob.ar/inta anuncia INTA Geo https://geo.inta.gob.ar/ e Información Agroclimática, sin confirmar mapas de suelo/cobertura para SCS-CN.
* CPC índices: página https://www.cpc.ncep.noaa.gov/data/indices/ define ONI como media trimestral Niño 3.4 ERSSTv6; Niño 3.4 mensual vía detrend.nino34.ascii.txt; SOI Tahiti − Darwin. Archivo SOI https://www.cpc.ncep.noaa.gov/data/indices/soi incluye columnas de anomalía y estandarizado (1951–presente).
* IRI: https://iri.columbia.edu/ anuncia cierre de Data Library y tránsito de pronósticos a https://forecast.ccsr.columbia.edu, con enlace a pronóstico ENSO actual en https://iri.columbia.edu/our-expertise/climate/forecasts/enso/current/. No se verificó API, licencia ni resolución.
* C3S: https://climate.copernicus.eu/ confirma CDS en https://cds.climate.copernicus.eu/ implementado por ECMWF; el dataset específico de pronóstico estacional ENSO no se confirmó (404).

## Pasadas 2 y 3 (2026-11-05, con búsqueda web)

Estas pasadas reemplazan las filas equivalentes de la tabla de arriba cuando hay conflicto. Los snippets de búsqueda
son indicios, no verificación: lo que no se leyó en la página primaria sigue "sin verificar".

| Ítem | Estado | URL de acceso | Método | Resolución | Licencia | Latencia / retención | Fase |
|---|---|---|---|---|---|---|---|
| SNIH (contiene la BDHI) | available, con aceptación de términos | https://snih.hidricosargentina.gob.ar | Web, pestaña "Datos Históricos" por estación | diario/horario sin verificar; IDs de estaciones (Limay, Neuquén, Agrio, Curí Leuvú, Chos Malal, Andacollo) sin verificar | términos de uso, texto sin leer | red estadística, no de alerta (dice la página) | 2 |
| AIC caudales y lluvia | restricted | https://www.aic.gob.ar/estaciones.aspx ; https://www.aic.gob.ar/terminos-condiciones.aspx | Listado web; series por solicitud/acuerdo (según vignette de hydrotoolbox, snippet) | medias diarias; lluvia 06–06 | reproducción citando "la AIC como fuente" y fecha; no es licencia abierta | sin verificar | 2 |
| Radar SMN Neuquén (RM7/RMA7, SINARAME) | available (imágenes); volúmenes sin verificar | smn.gob.ar (no se pudo leer: 402/403) | Visualización web y app; volúmenes: pedido a SMN, procedimiento sin verificar | alcance 240 km (hasta 400 km con menor precisión); banda sin verificar | sin verificar | sin verificar | 3 |
| Archivo de volúmenes RMA (referencia) | restricted | https://data.eol.ucar.edu/dataset/553.022 | FTP con acuerdo de usuario, CFRadial | solo RMA1 Córdoba; ~0,5 GB/h | acuerdo de usuario | — | 3 |
| SMN horario Neuquén Aero (87715) | sin verificar | https://www.smn.gob.ar/descarga-de-datos (402) | sin verificar | sin verificar | Disposición 25 SMN: acceso libre bajo CC (versión sin verificar, fuente secundaria) | sin verificar | 3 |
| NOAA ISD 877150 (Neuquén Aero, alternativa) | sin verificar | https://noaa-isd-pds.s3.amazonaws.com/index.html | S3 anónimo | horaria (según Tutiempo) | sin verificar | sin verificar | 3 |
| GEFS operativo | available | https://registry.opendata.aws/noaa-gefs/ (s3://noaa-gefs-pds) | S3 anónimo | 21 miembros, 4 corridas/día, 16 días; GRIB2 0,5° y 0,25° | datos NOAA abiertos, con atribución | latencia y retención no declaradas; archivo desde 2018 visto | 6 |
| C3S estacional (Niño 3.4) | available | https://climate.copernicus.eu/seasonal-forecasts | Gráficos; datos vía CDS (cuenta) | mensual, publicado el día 10 | términos del CDS (sin verificar en página) | — | 5, 6 |
| IRI ENSO | available (solo visualización) | https://iri.columbia.edu/our-expertise/climate/forecasts/enso/current/ | Sin descarga ("no longer providing forecast data") | trimestral, 27 modelos | CC BY 4.0 (página quick look) | mensual, día 19 | 5 |
| CAMELS-CL | available; solo Chile (inferido) | http://camels.cr2.cl ; DOI 10.1594/PANGAEA.894885 | Descarga PANGAEA | 516 cuencas | CC-BY-4.0 (snippet) | — | 2 |
| Suelos INTA (GeoINTA) | available; licencia sin verificar | https://geo.inta.gob.ar/ | Visor y geoservicios | por capa, sin verificar | sin texto de licencia | — | 4 |
| SoilGrids 250 m | available | https://soilgrids.org/ | GeoTIFF, WCS | 250 m | CC-BY-4.0 (snippet) | — | 4 |
| ESA WorldCover 2021 | available | https://worldcover2021.esa.int/download | Descarga, AWS | 10 m | CC-BY-4.0 (snippet) | — | 4 |
| MapBiomas Argentina | sin verificar (503) | https://argentina.mapbiomas.org | Descarga, GEE | anual 1985–2024 (snippet) | acceso abierto, tipo sin especificar | — | 4 |
| Inventario de remoción en masa | parcial | https://repositorio.segemar.gob.ar/handle/308849217/4372 ; .../4416 | PDFs SEGEMAR (Ruta 7 Lagos; Cerro de la Virgen, Chos Malal 2023) | por tramo / evento | sin verificar | — | 4 |
| NASA Global Landslide Catalog | available | https://catalog.data.gov/dataset/global-landslide-catalog-export | CSV, SHP | evento puntual | no indicada | — | 4 |
| DesInventar Argentina | sin verificar para Neuquén | https://online.desinventar.org | Consulta web | base de prensa desde 1995 (snippet) | sin verificar | — | 4 |

Eventos verificados: remoción en masa en Cerro de la Virgen (RP43, Chos Malal), 1 de agosto de 2023, 4 heridos, sin
volumen (informe SEGEMAR y prensa). Crecidas del Curí Leuvú y decreto de desastre hídrico (julio 2023): solo snippets.

Pendientes para las fases que los usan (no bloquean la fase 0): pedido formal de volúmenes del radar de Neuquén al SMN
(fase 3); IDs y términos de SNIH para Limay, Neuquén, Agrio y Curí Leuvú (fase 2); acuerdo de datos con la AIC
(fase 2); serie horaria de Neuquén Aero por SMN o ISD (fase 3); inventario de aluviones del norte (fase 4).

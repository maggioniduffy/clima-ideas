# Fase 1 — Datos FIRMS

Estado: pendiente · Depende de: 0 (SA0.8) · Refs: `../docs/architecture.md`

## Objetivo

Focos de calor de MODIS y VIIRS 2000–hoy, filtrados y en una grilla global liviana para consultar cualquier área.

## Datos

MODIS C6.1 (Terra desde 11/2000, Aqua desde 7/2002), VIIRS 375 m (S-NPP desde 1/2012, NOAA-20, NOAA-21).
Archivo standard para la historia; NRT para el mes en curso.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| SA1.1 | Descarga idempotente del archivo histórico (global o por país, según SA0.8) | Sonnet escribe, opencode corre | Archivos con checksum + unit de idempotencia |
| SA1.2 | Ingesta a Parquet con esquema único (sensor, satélite, fecha/hora, día/noche, lat, lon, confianza, FRP, tipo) | Sonnet | Unit sobre filas sintéticas de cada sensor |
| SA1.3 | Filtros: solo `type` vegetación (sin fuentes fijas ni mar adentro); confianza MODIS ≥ umbral, VIIRS nominal o alta; umbral configurable | Sonnet | Unit: cada filtro descarta lo esperado |
| SA1.4 | Grilla global: conteo por celda (0,1° y 0,25°) × día × sensor × día/noche | Sonnet escribe, opencode corre | Parquet particionado por año + unit de agregación |
| SA1.5 | Detecciones crudas de Argentina en DuckDB para consultas y CSV | Sonnet | Consulta por polígono < 2 s en Córdoba |
| SA1.6 | Ingesta NRT del mes en curso por API de área | Sonnet | Una corrida trae el último día disponible |
| SA1.7 | Perfil de datos: focos por año, sensor y región; huecos | opencode | `reports/01/SA1.7.md` |

## Abierto

- Volumen global de VIIRS: si no entra en disco o en tiempo, la grilla global se limita a Sudamérica y el resto
  de las áreas se consulta por API al momento (decide Opus tras SA0.8).

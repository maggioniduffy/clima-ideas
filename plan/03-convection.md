# Fase 3 — Convección en la meseta y la Confluencia

Estado: en curso (F3.0 hecha: sin lluvia horaria de estación; la pregunta va reformulada) · Depende de: 0 · Refs: `docs/architecture.md`

## Pregunta

¿Cada cuánto se repite una lluvia como la de abril de 2014 y cuánto la subestiman los productos globales?
Si F3.0 no encuentra lluvia horaria de estación, la segunda parte se reformula: IDF solo con IMERG y sesgo medido
a 24 h contra totales diarios de estación.

## Datos

IMERG 30 min (2000–hoy), SMN Neuquén Aero, estaciones AIC (Plottier). Acceso horario según F0.8.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F3.0 | Comprobar lluvia horaria de Neuquén Aero en NOAA ISD 877150 (S3 anónimo): período, huecos y licencia. SMN horario sigue sin verificar y AIC es restringido | opencode | Informe en `reports/03/F3.0.md` con sí o no y por qué |
| F3.1 | Ingesta IMERG recortado a la Confluencia y meseta | Sonnet escribe, opencode corre | Zarr 2000–hoy |
| F3.2 | Ingesta de estaciones con control de calidad | Sonnet | Parquet + unit de QC |
| F3.3 | Curvas IDF (duraciones 30 min–24 h) estación vs. IMERG | Sonnet | Unit con serie sintética de cuantiles conocidos |
| F3.4 | Sesgo de IMERG en eventos conocidos; corrección por cuantiles | opencode analiza, Sonnet implementa | Informe de sesgo + función QM testeada |
| F3.5 | Capa: curva IDF lado a lado + replay del temporal de abril de 2014 | Sonnet | e2e: replay y comparación |
| F3.6 | Frecuencia de días convectivos extremos por fase ENSO (F0.10), primavera y verano | opencode analiza | Tabla con n de años, test de permutación y "sin verificar" donde no alcance; conteos en el formato de F1.9 ("5 de 7 primaveras Niño"), nunca "de cada 10" |

## Entregable

Curva IDF de Neuquén capital, estación e IMERG lado a lado, con el sesgo medido.

## Abierto

- Sin lluvia horaria de estación (F3.0), IDF solo con IMERG y marcada así; el sesgo se mide a 24 h.

## Avance

- 2026-11-16 F3.0 hecha (`reports/03/F3.0.md`, veredicto parcial): ISD 877150 tiene 68 archivos anuales
  1939–2025 y 0 % de horas con lluvia de 1 h utilizable en todos los años, así que no sirve para la IDF de
  30 min–1 h. Trae acumulados SYNOP de 6 h y 24 h con huecos de hasta 116 días y condición 3; abril de 2014 aparece
  (7/4 12Z: 118 mm/24 h, 54 mm/6 h). Decisión: rige la reformulación de la "Pregunta" (IDF solo con IMERG y
  marcada así). En F3.4 los p6/p24 de ISD sirven para contrastar eventos con la bandera `cond=3`, no para ajustar
  sesgo. El sesgo a 24 h espera una serie diaria de estación verificada (SMN o AIC: sin verificar).
- 2026-11-16 F3.1 en curso, solo investigación (`reports/03/F3.1-access.md`, en inglés). Acceso: IMERG V07 Final
  semihorario (`GPM_3IMERGHH`, CMR `C2723754847-GES_DISC`) por NASA Harmony, recorte bbox −70/−40/−67/−37,5 y
  variable `Grid/precipitation`; requiere cuenta Earthdata con el EULA de GES DISC aceptado (hecho) y credenciales en
  `.env` (`EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD`). Prueba de un mes (abril de 2014, 1440 medias horas): Harmony
  procesa en 138 s; descarga 66 MB en 660 s con 4 hilos; Zarr del mes 355 KB; sin errores. Harmony no concatena:
  un archivo por media hora. 7/4/2014 en la celda de Neuquén Aero: Final 92,0 mm/día y 15,4 mm/h máx.; Late
  (copia pública dynamical.org) 59,4 mm y 10,7 mm/h; ISD 118 mm/24 h (F3.0). Extrapolado a 317 meses: ≈ 113 MB
  de Zarr y ≈ 70 h secuencial. Pendiente: medir descarga con más hilos (prueba interrumpida; ojo, `download_all`
  de harmony-py es un generador: armar la lista de futures antes de esperar, y fijar `NUM_REQUESTS_WORKERS`),
  varios meses en vuelo, y escribir `odd/tasks/` + el módulo `io/imerg.py`.

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
| F3.3 ✅ | Curvas IDF (duraciones 30 min–24 h) estación vs. IMERG | Sonnet | Unit con serie sintética de cuantiles conocidos |
| F3.4 ✅ | Sesgo de IMERG en eventos conocidos; corrección por cuantiles | opencode analiza, Sonnet implementa | Informe de sesgo + función QM testeada |
| F3.5 | Capa: curva IDF lado a lado + replay del temporal de abril de 2014 | Sonnet | e2e: replay y comparación |
| F3.6 ✅ | Frecuencia de días convectivos extremos por fase ENSO (F0.10), primavera y verano | opencode analiza | Tabla con n de años, test de permutación y "sin verificar" donde no alcance; conteos en el formato de F1.9 ("5 de 7 primaveras Niño"), nunca "de cada 10" |

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
- 2026-11-16 F3.1 código hecho (`odd/tasks/imerg-ingest.md`): `clima-nqn imerg fetch/combine` (`io/imerg.py`), un Zarr
  por mes y uno combinado. Prueba real del 7/4/2014 reproduce 92,015 mm/día y 15,41 mm/h. Detalles de los archivos de
  Harmony: la variable está en el grupo `Grid` y el tiempo viene con calendario "julian" (se conservan las etiquetas).
  Benchmark de 32 hilos descartado por el usuario. Corrida completa en GitHub Actions (`.github/workflows/imerg.yml`,
  un job por año).
- 2026-11-19 F3.1 hecha. Corrida encadenada en Actions (`odd/tasks/imerg-ingest.md`, L9–L15): artifact `imerg-neuquen`
  (run 44455941236, retención 90 días, no está en el repo), IMERG V07 Final semihorario 2000-06-01 a 2025-09-30,
  444 144 pasos × 25 lat × 31 lon, `missing_months` vacío. 2025-10 en adelante todavía no existe como Final en Harmony
  ("No matching granules"); la latencia real de Final es mayor que los 4 meses asumidos (sin verificar cuánto).
- 2026-11-20 IMERG Final 2000-06..2025-09 respaldado en R2 privado (`nqn-raw/imerg/final-v07/`, sha256 verificado;
  `odd/tasks/imerg-ingest.md` L17). Final termina en 2025-09 en NASA CMR; 2025-10..2026-10 se baja como IMERG Late
  (producto aparte, sin ajuste mensual con pluviómetros, nunca mezclado con Final; L16). El `last_month` por defecto
  del workflow sale ahora del último mes completo en CMR.
- 2026-11-20 F3.3 primera versión (`reports/03/F3.3.md`, `stages/convection/idf.py`): IDF solo con IMERG Final, sin
  corrección de sesgo, celda de Neuquén Aero, 25 años hidrológicos 2000/01–2024/25, GEV por L-momentos con Gumbel y
  empírico al lado. T 10: 17,9 mm/h a 1 h (IC 90 % 15,0–19,8) y 78,7 mm a 24 h (59–97); Gumbel dentro del IC de la GEV
  en todos los casos. Abril de 2014 en IMERG: 108 mm en 24 h, T ≈ 25 años (14–100). Falta aplicar la corrección de F3.4.
- 2026-11-20 F3.4 hecha (`reports/03/F3.4.md`, `io/isd.py`, `stages/convection/bias.py`): IMERG/estación a 24 h 0,92
  (IC90 0,82–1,02; n = 350 pares húmedos, 2000–2025) y 0,88 a 6 h (0,81–0,97); en 16 extremos ≥ 20 mm comprobables
  0,67 (0,12–1,53 por evento); abril de 2014 12Z–12Z: 97,6 contra 118 mm. Muchos p24 grandes de ISD son imposibles
  (> 150 mm repetidos) y se filtran. Corrección por cuantiles probada con validación dejando un año afuera: no mejora a un
  factor único y no sirve en extremos. Decisión (Opus; advisor vencido el 2026-11-17): la IDF de F3.3 queda sin
  corregir y muestra los factores 0,92 y 0,67 como sensibilidad. Comandos: `clima-nqn convection idf|bias`.
- 2026-11-20 F3.6 hecha (`reports/03/F3.6.md`, `stages/convection/enso.py`): sin señal de ENSO en días convectivos
  extremos (IMERG Final, celda de Neuquén Aero, SON 2000–2024 y DJF 2000/01–2024/25, ONI ±0,5). Umbral principal p99
  conjunto 12,6 mm/h: solo 5 días, todos en primavera (1 de 8 primaveras Niño, 2 de 10 neutras, 0 de 7 Niña). Ningún
  test pasa BH < 0,05 en la principal ni en 4 sensibilidades (p95, regional, p99 y p95 por estación). Con tan pocos
  días la prueba no tiene potencia: ausencia de señal no es ausencia de efecto.

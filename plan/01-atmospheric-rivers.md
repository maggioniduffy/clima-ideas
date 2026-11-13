# Fase 1 — Ríos atmosféricos en la cordillera

Estado: hecha · Depende de: 0 · Refs: `docs/architecture.md` (contrato de capas)

## Pregunta

¿Cuántos ríos atmosféricos llegan a la cordillera neuquina por año y cuánta lluvia extrema explican?

## Datos

ERA5 1980–hoy: componentes de IVT, precipitación, isoterma de 0 °C. Licencia según F0.8.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F1.1 ✅ | Script de descarga ERA5 desde ARCO-ERA5 (Zarr público en Google Cloud, sin cola ni clave; `tools/teca/fetch_era5_ivt.py --source arco`) por recorte y variables, idempotente | Sonnet escribe, opencode corre | Zarr completo en `data/raw/era5/` |
| F1.2 ✅ | Detección con TECA BARD en jobs paralelos (matriz de GitHub Actions por año o por mes; BARD tarda ~2,5 h por año en el hemisferio sur) | opencode corre, Opus valida | Máscara diaria de ríos atmosféricos |
| F1.3 ✅ | Catálogo: eventos que tocan el polígono de cordillera (fecha, duración, IVT máx., isoterma 0 °C) | Sonnet | Parquet + unit tests con máscara sintética |
| F1.4 ✅ | Fracción de días de lluvia extrema (p99) que coinciden con un evento | opencode | Informe con cifras, fuente y período |
| F1.5 ✅ | Contraste con literatura de ríos atmosféricos en los Andes | opencode | Tabla: nuestro conteo vs. publicado |
| F1.6 ✅ | Capa del visor: eventos en la línea de tiempo + replay de IVT por hora | Sonnet | e2e: elegir evento, reproducir, inspeccionar |
| F1.7 ✅ | ML (media): detector preentrenado tipo ClimateNet vs. BARD | opencode corre, Sonnet integra | Acuerdo entre métodos medido; opcional |
| F1.8 ✅ | Ríos atmosféricos por fase ENSO (F0.10): conteo, IVT y lluvia por estación del año; test de permutación | opencode analiza, Sonnet codifica el test | Tabla Niño/Neutro/Niña con p-valor y n de años + unit del test |
| F1.9 ✅ | Días de lluvia extrema (≥ p99 de F1.4) por estación y fase ENSO, y contra el ONI, 1980–2025; regla fijada antes de correr (ver "Regla de F1.9") | Sonnet codifica, Opus corre y revisa | `reports/01/F1.9.md` con años por fase, conteos "k de n", test de permutación y sensibilidad p95 y rectángulo |

## Regla de F1.9 (fijada el 2026-11-12, antes de correr)

- Unidad: estación-año (DJF, MAM, JJA, SON; diciembre va al DJF del año siguiente; se descartan estaciones
  incompletas en los bordes), 1980–2025, como F1.8.
- Serie: lluvia diaria ERA5 (días UTC, convención de F1.4), media del polígono de cordillera de F1.3/F1.4.
- Día extremo: media diaria ≥ p99 de todos los días del registro (definición principal de F1.4, 29,2 mm/día; se
  recalcula igual y se comprueba).
- Por estación-año: número de días extremos y si hubo al menos uno.
- Fase: media del ONI de los tres meses de la estación; Niño ≥ +0,5, Niña ≤ −0,5 (como F1.8).
- Pruebas por estación: Niño − Niña en la media de días extremos, permutación de etiquetas (10 000, semilla 0,
  bilateral); prueba de 3 grupos con F; BH sobre las 4 estaciones. Contra el ONI: ρ de Spearman con p por
  permutación (10 000, semilla 0), BH sobre las 4 estaciones.
- Formato: "5 de 7 inviernos Niño tuvieron al menos un día extremo", nunca "de cada 10".
- Sensibilidad junto a la cifra principal: p95 sobre el polígono, y p99 propio del rectángulo anterior. "Robusto"
  solo si dirección y resultado BH coinciden en las tres variantes.

## Entregable

Catálogo de ríos atmosféricos + fracción de lluvia extrema explicada, visible como capa con replay.

## Avance

- F1.1 hecha (2026-11-08): run 42437929137 de `era5.yml`, 1980–2025, 46 jobs, ~100 MB por año. Zarr horario de `viwve`,
  `viwvn`, `tp`, `deg0l` sobre `NEUQUEN_BOX` -34,-74,-43,-66, fuente ARCO-ERA5 (CC-BY 4.0).
- F1.2 hecha (2026-11-08): run 42437931768 de `teca.yml` (3 intentos: jobs sin runner, y una falla transitoria de
  `setup-micromamba`), 46 recortes `bard-neuquen-<año>` 1980–2025.
- F1.3 hecha: 433 eventos, 9,4/año con el polígono recortado (`reports/01/F1.3.md`, run 42516927153); con el rectángulo
  anterior eran 480, 10,4/año.
- F1.4 hecha: 58,0 % de los días ≥ p99 (29,2 mm/día, media del polígono) coinciden con un RA (IC 50,5–65,2 %), tasa base
  3,7 %, razón 15,8; p95: 30,7 %; por celda: 65,9 % (`reports/01/F1.4.md`). Con el rectángulo: 63,3 %, 4,2 %, 35,3 %, 70,8 %. Umbral p99 confirmado como definición
  principal; p95 y por celda quedan como sensibilidad.
- F1.5 hecha (2026-11-08, entorno `clima-ideas` con acceso a doi.org y revistas): 4 de 7 estudios verificados en texto
  completo (Viale et al. 2018, Valenzuela y Garreaud 2019, Viale y Nuñez 2011, Saavedra et al. 2020); Guan y Waliser
  2015, Rutz et al. 2019 y Campos y Rondanelli 2023 siguen sin verificar (Wiley responde 403). Comparación: ≈ 13,5 días/año
  con RA vs. 15–20 al este de los Andes al sur de 35° S (Viale 2018); 58,0 % de extremos con RA vs. 27–70 % en Chile
  centro-sur con umbral ≥ 35 mm/día (Valenzuela y Garreaud 2019).
- F1.6 hecha y revisada en el visor con la capa real (2026-11-08): rampa secuencial de alto contraste en ambos temas,
  leyenda (satura en 1200 kg m-1 s-1), contorno provincial (Natural Earth 1:10m, dominio público), polígono de
  cordillera y marcador de Neuquén capital; inspector sin scroll a 1400x820. Capa completa en el visor local
  (2026-11-08): artefacto `ar-events-layer` del run 42516927153, 433 eventos 1980–2025, todos con frames de IVT.
- Hallazgo del visor: el polígono de cordillera (71,95–70 O) se sale al oeste del límite provincial, sobre Chile, en
  buena parte de la cordillera. Afecta F1.3/F1.4. Corregido: el polígono ahora es la provincia (Natural Earth 1:10m)
  recortada al oeste de 70° O (`backend/src/clima_nqn/stages/ar/geo/`, 88 celdas BARD contra 140 del rectángulo);
  F1.3/F1.4/F1.8 re-corridos con el polígono (run 42516927153 de `ar-catalog.yml`). La cordillera no se define por cota con el DEM (decisión del usuario, 2026-11-08).
- Relieve en el visor (2026-11-08): Copernicus GLO-30, rampa pizarra monocroma con sombreado (referencia: mockup de
  diseño, `docs/design.md`), debajo del IVT semitransparente (0,5 con relieve; casi opaco sin relieve); IVT y relieve
  recortados a la provincia más una franja de 10 km (reemplazado: ahora cubren todo el recorte ERA5, ver V1–V4); leyenda abajo a la derecha. Visor adaptable: por debajo de 800 px
  capas e inspector pasan a paneles desplegables.
- F1.7 hecha para 2023 con el polígono provincial (run 42520253919): ClimateNet (`climatenet_new/model/weights.pth`) vs.
  BARD kappa 0,18, peor que el baseline IVT ≥ 250 (kappa 0,24); ClimateNet marca RA en 24,5 % de los pasos vs. 3,3 % de
  BARD y se parece más al umbral de IVT (kappa 0,54). Con el rectángulo (run 42503142531) los kappa eran los mismos
  (25,8 % vs. 3,8 % de pasos). El ML no mejora al baseline (`reports/01/F1.7.md`).
- F1.8 hecha: con el polígono, 3 de 16 pruebas Niño−Niña con p < 0,05 (SON: días con RA, IVT máx. medio 527 vs. 435
  kg m⁻¹ s⁻¹, fracción de lluvia) y ninguna sostiene p BH < 0,05 (`reports/01/F1.8.md`). Con el rectángulo eran 6 de 16
  y el IVT máx. medio de SON sí sostenía BH: el resultado no es robusto a la elección del polígono.
- F1.8 en el visor (pedido del usuario, 2026-11-08): la capa `ar-events` publica `F1.8.json` como `enso.json`
  (`clima-nqn ar layer --enso-report`); botón "ENSO por estación" abre un panel con la tabla por estación. En el
  panel, "¿Sostenida?" usa p BH < 0,05 (el informe usa p < 0,05). Cifras de SON revisadas contra `reports/01/F1.8.md`
  con la capa real. F1.7 sigue solo como informe.
- F1.9 hecha (2026-11-13, regla fijada antes de correr): umbral p99 29,2 mm/día (= F1.4), 169 días extremos. Ninguna
  estación sostiene p BH < 0,05 en Niño − Niña. SON: 6 de 14 primaveras Niño y 1 de 14 Niña con al menos un día
  extremo (p 0,047 sin ajustar, p BH 0,19); ρ con el ONI 0,38, p BH 0,043 solo con p99 en el polígono (0,055 con p95,
  0,060 con el rectángulo): no robusto. JJA: 7 de 7 inviernos en ambas fases (`reports/01/F1.9.md`).
- Panel ENSO reescrito (pedido del usuario, 2026-11-12): veredicto en lenguaje llano, un punto por año agrupado por
  fase, la tabla de F1.8 detrás de "ver detalle" y el bloque de F1.9 (`enso-extremes.json`, `ar layer --extremes-report`).

## Mejoras del visor (pedido del usuario, 2026-11-08)

Tras ver la capa completa (433 eventos) en el visor, costaba leer qué muestra. Hechas (2026-11-09):

- [x] V1 Texto de ayuda en el panel derecho cuando no hay evento elegido: qué es un río atmosférico (AMS Glossary) y
  qué es el IVT (umbral de referencia ~250, Rutz et al. 2014).
- [x] V2 Más mapa: columnas laterales 200 / 260 px (antes 240 / 300); inspector sin scroll a 1400x820.
- [x] V3 Relieve con más contraste (sombreado 0,25–1,5, exageración 3,5, rampa estirada) y IVT a 0,7 sobre el relieve.
  El polígono de cordillera no se dibuja (decisión del usuario).
- [x] V4 IVT transparente bajo 150 kg m⁻¹ s⁻¹, alfa con smoothstep hasta 0,95 en ≥ 400; la leyenda lo indica.
- [x] Más área: IVT y relieve cubren todo el recorte ERA5 (34–43 °S, 74–66 °O), sin recorte a la provincia;
  relieve regenerado con paso 1/66° (304 920 puntos; 2 teselas oceánicas sin DEM).

## Rediseño de la capa (pedido del usuario, 2026-11-13)

Los ríos atmosféricos quedaban perdidos: mapa vacío hasta elegir uno de 433 eventos de una lista plana, y sin
relación visible con los caudales. Detalle y registro en `odd/tasks/ar-viewer-rework.md`.

- [x] V5 Lista por año con interruptores, y dentro de cada año sus meses; sin grilla (decisión del usuario).
- [x] V6 Picos: orden por IVT máximo, lluvia total o duración, e interruptor "top N"; marcas más grandes en la
  línea de tiempo. Por ranking, sin categorías.
- [x] V7 Mapa: sin evento elegido, cantidad de eventos que alcanzaron IVT ≥ 250 en cada celda para los años y
  meses activos; con evento, su huella (IVT máximo por celda), el núcleo y la celda del pico. El núcleo de IVT
  es por donde pasa la humedad, no donde más llueve; no hay lluvia por celda.
- [x] V8 Relación con caudales: las crecidas que coinciden con un río atmosférico (F2.3) llevan al evento; el
  evento muestra el caudal diario de las estaciones alrededor de su ventana. Tabla por evento y estación
  (caudal previo, pico en [inicio, fin + 10 días], demora). "Coincide con", nunca "causó".
- V5–V8 hechas (2026-11-13; commits 147c33c, 8fec2af, e8a2071, 19bd6b0, 7bcc9b9): verificadas con vitest, pytest y
  Playwright sobre datos de prueba. Sin verificar con datos reales: falta regenerar la capa (`clima-nqn ar layer`,
  `clima-nqn ar response`, `clima-nqn flow causes` y `flow layer`) y publicarla. La ventana de 10 días es un supuesto.

## Abierto

- Pocos años por fase ENSO: informar n y no afirmar diferencias que el test no sostiene.

- Resuelto: el umbral de lluvia extrema es p99 diario (F1.4); p95 y por celda quedan como sensibilidad.

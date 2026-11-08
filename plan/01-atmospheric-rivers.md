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
  cordillera y marcador de Neuquén capital; inspector sin scroll a 1400x820.
- Hallazgo del visor: el polígono de cordillera (71,95–70 O) se sale al oeste del límite provincial, sobre Chile, en
  buena parte de la cordillera. Afecta F1.3/F1.4. Corregido: el polígono ahora es la provincia (Natural Earth 1:10m)
  recortada al oeste de 70° O (`backend/src/clima_nqn/stages/ar/geo/`, 88 celdas BARD contra 140 del rectángulo);
  F1.3/F1.4/F1.8 re-corridos con el polígono (run 42516927153 de `ar-catalog.yml`). La cordillera no se define por cota con el DEM (decisión del usuario, 2026-11-08).
- Relieve en el visor (2026-11-08): Copernicus GLO-30, rampa pizarra monocroma con sombreado (referencia: mockup de
  diseño, `docs/design.md`), debajo del IVT semitransparente (0,5 con relieve; casi opaco sin relieve); IVT y relieve
  recortados a la provincia más una franja de 10 km; leyenda abajo a la derecha. Visor adaptable: por debajo de 800 px
  capas e inspector pasan a paneles desplegables.
- F1.7 hecha para 2023 con el polígono provincial (run 42520253919): ClimateNet (`climatenet_new/model/weights.pth`) vs.
  BARD kappa 0,18, peor que el baseline IVT ≥ 250 (kappa 0,24); ClimateNet marca RA en 24,5 % de los pasos vs. 3,3 % de
  BARD y se parece más al umbral de IVT (kappa 0,54). Con el rectángulo (run 42503142531) los kappa eran los mismos
  (25,8 % vs. 3,8 % de pasos). El ML no mejora al baseline (`reports/01/F1.7.md`).
- F1.8 hecha: con el polígono, 3 de 16 pruebas Niño−Niña con p < 0,05 (SON: días con RA, IVT máx. medio 527 vs. 435
  kg m⁻¹ s⁻¹, fracción de lluvia) y ninguna sostiene p BH < 0,05 (`reports/01/F1.8.md`). Con el rectángulo eran 6 de 16
  y el IVT máx. medio de SON sí sostenía BH: el resultado no es robusto a la elección del polígono.

## Abierto

- Pocos años por fase ENSO: informar n y no afirmar diferencias que el test no sostiene.

- Umbral de "lluvia extrema" (p99 diario propuesto). Opus confirma tras F1.4.

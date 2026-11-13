# Fase 2 — Crecidas de ríos

Estado: tareas hechas (F2.1–F2.7); cierra cuando la capa con la ficha de crecida esté publicada (F0.11) · Depende de: 1, acceso a caudales (F0.8) · Refs: `docs/architecture.md`

## Pregunta

¿Qué tan raras fueron las crecidas grandes y qué parte explican los ríos atmosféricos o la lluvia sobre nieve?
Alcance real: ríos Neuquén, Agrio y Curi Leuvú. El Limay queda fuera: no hay estación natural con datos.

## Datos

Caudal medio diario del SNIH (contiene la BDHI; parámetro 101, año hidrológico desde abril; citar SIPH/SNIH y fecha
de actualización). Con datos y aguas arriba de las presas: 12004 Paso de Indios (Neuquén, 1945–2026), 12010 Bajada
del Agrio (1953–2026), 12012 Los Maitenes (Curi Leuvú, 1989–2021). 11803 Paso Flores (Limay) excluida por regulada;
12013 Chos Malal y 11804 Paso Limay no devuelven datos. AIC: restringido. Para lluvia sobre nieve (F2.3): isoterma
de 0 °C de ERA5 (`deg0l`, ya descargada en F1.1) y nieve de ERA5 a 0,25° (`snow_depth`, ARCO-ERA5); ERA5-Land queda
como mejora y pide clave de CDS. CAMELS-CL (F2.5): PANGAEA, CC-BY-4.0, solo Chile.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F2.1 ✅ | Ingesta de caudales diarios con control de huecos | Sonnet escribe, opencode descarga | Parquet por estación + reporte de huecos |
| F2.2 ✅ | Máximos anuales y GEV con intervalo de confianza (`pyextremes`) | Sonnet | Unit: recupera parámetros de una GEV sintética |
| F2.3 ✅ | Etiquetar crecidas mayores con el catálogo F1.3 y lluvia sobre nieve | opencode | Tabla de crecidas con causa probable + sensibilidad a la ventana de días entre río atmosférico y pico |
| F2.4 ✅ | Capa: estaciones + panel de período de retorno y serie | Sonnet | e2e: elegir estación, ver curva y crecidas |
| F2.5 ✅ | ML (alta): LSTM de caudal diario; preentreno en CAMELS-CL, ajuste en Neuquén; baselines GR4J y persistencia | Sonnet implementa, opencode entrena, Opus revisa métricas; advisor si hace falta | NSE/KGE en test vs. baselines |
| F2.6 ✅ | Ficha de crecida: pronóstico LSTM de próximos días con incertidumbre vs. observado | Sonnet | e2e sobre un evento pasado |
| F2.7 ✅ | Máximos anuales y caudal estacional por fase ENSO; GEV con ONI como covariable vs. estacionaria. Su resultado decide si se hace el modelo estacional F6.2 | Sonnet; advisor si hace falta | Comparación por verosimilitud + unit con GEV sintética dependiente de covariable |

## Avance

- F2.1 (2026-11-09): años completos 12004 80 de 82, 12010 66 de 73, 12012 25 de 32 (`reports/02/F2.1.md`).
- F2.2 (2026-11-09): 12004 xi = 0,336, Q100 = 10 649 m³/s (IC 5 980–20 908); el pico del 2023-06-26 (11 895 m³/s)
  da T ≈ 134 años por GEV (81 empírico). 12010 xi = 0,122 (`reports/02/F2.2.md`).
- F2.4 (2026-11-09): capa `flood-stations` con curva de período de retorno, serie y crecidas mayores.
- F2.3 (2026-11-12): catálogo 1980–2025. Crecidas con un río atmosférico en [pico − 3 d, pico]: 12004 30 de 45
  (66,7 %; por azar 14,8 %), 12010 31 de 44 (70,5 %; 15,2 %), 12012 17 de 25 (68 %; 16,6 %); p de permutación 0,0001,
  sin ajustar entre ventanas ni estaciones. Con lluvia sobre nieve probable: 6, 13 y 3. El pico del 2023-06-26 queda
  como «río atmosférico» (la nieve subió de 61 a 76 mm en la ventana). Nieve: ERA5 a 0,25° (ARCO), no ERA5-Land;
  cuencas aproximadas por rectángulos, sin verificar (`reports/02/F2.3.md`).
- F2.7 (2026-11-12): por la regla fijada, «señal», sostenida por un solo test: GEV con ONI abr–sep en 12010,
  μ₁ = 191 m³/s por unidad de ONI, p BH 0,019 (permutación 0,0011); 12004 p BH 0,082; ningún test por fase pasa.
  Se mantiene con control de tendencia y en 1953–2009. Con el ONI de ene–mar (conocido el 1 de abril) no hay
  señal: 12010 p de permutación 0,565 y μ₁ de signo contrario (corregido tras la revisión: la primera corrida
  promediaba tres valores que llegaban a abril; daba 0,559). La compuerta para F6.2 no pasa: F6.2 corre sin
  ENSO o queda en baselines; la decisión es del usuario (`reports/02/F2.7.md`).
- Advisor (2026-11-12): ¿registrar «señal» tal cual y qué falta antes de abrir F6.2? Recomendó mantener el veredicto
  de la regla, leerlo como señal débil y concurrente, y condicionar F6.2 a un ONI rezagado. Decisión: adoptado.
- F2.5 (2026-11-12): test 2014–2025, mediana de tres estaciones. Simulación: LSTM NSE 0,51 frente a GR4J+CemaNeige
  0,49 (KGE 0,50 frente a 0,53); gana en 12004 (0,58 frente a 0,49), empata en 12010 y 12012. Pronóstico: la persistencia
  gana a 1 día (0,78 frente a 0,70); el LSTM gana desde 2 días (0,64 frente a 0,56) y a 7 días 0,64 frente a 0,05.
  Sensibilidad: sin preentrenamiento empeora en las tres; con test 1980–1991 el LSTM gana claro en 12004 y 12010
  (0,74 y 0,63 frente a 0,43 y 0,44). Junio de 2023 en 12004: momento acertado, pico subestimado unas 3 veces
  (≈ 3800–4600 frente a 11 895 m³/s). Preentreno CAMELS-CL de PANGAEA (forzante CR2MET; Caravan no descargable,
  Zenodo 403). Primera evaluación con un error de normalización, corregido en c5db09b (`reports/02/F2.5.md`).
- F2.6 (2026-11-12): ficha de crecida en el panel de estación: 3 crecidas de test por estación (incluye 2023-06-26 en
  12004 y 12010), emisión de 7 a 0 días antes del pico, plazos 1–7, mediana, banda 90 %, persistencia y observado;
  aviso fijo "Pronóstico retrospectivo con meteorología observada (ERA5), no pronóstico operativo. Experimental, no es
  una alerta." e2e de Playwright sobre fixture; revisada en el navegador con datos reales.
- Detalle y decisiones: `odd/tasks/floods.md` (F2.1–F2.4, F2.7) y `odd/tasks/streamflow-lstm.md` (F2.5, F2.6).

## Entregable

Períodos de retorno con IC para una estación natural, crecidas etiquetadas por causa, LSTM comparado.

## Abierto

- 12012 Los Maitenes: xi = 0,631 con 25 años; el IC no es confiable y la capa lo debe decir.
- Calificador `D` en 336 filas de 12010: significado sin verificar.
- El bootstrap de F2.2 no cuenta ni registra los remuestreos que quedan en el límite xi = 0,99.
- F2.4: tema claro sin revisar a ojo.
- F2.3: cuencas aproximadas por rectángulos y nieve de ERA5 a 0,25° sin contrastar con observaciones; delinear
  las cuencas con el DEM y repetir con ERA5-Land (pide clave de CDS del usuario).
- F2.3: el caudal diario está en hora local (UTC−3) y el catálogo en UTC; la coincidencia por día es aproximada.
- F2.7: el mecanismo entre ENSO y los picos queda sin verificar (F1.8 no halló señal en los ríos atmosféricos).
  El umbral de la regla se fijó en el encargo de la tarea, sin registro previo en la especificación.
- F2.5: el LSTM aprovecha poco el caudal observado (pierde con la persistencia a 1 día); la banda del 90 % es ancha en
  12004 y 12010 (cubre 94–99 %) y angosta en 12012; subestima los picos grandes (2023).
- F2.5: Caravan (ERA5-Land) como preentreno si el usuario baja `Caravan-nc.tar.gz` (24,8 GB) desde el navegador.
- F2.5: área SNIH de 12012 igual a la de 12013 Chos Malal (2131 km²): posible copia en los metadatos, sin verificar.
- F2.5: GR4J con una sola capa de nieve; bandas de elevación de CemaNeige pendientes.
- Fase 6: comprobar si una versión CUDA de torch soporta la GTX 1050 (Pascal, 2 GB) y sumarla como grupo opcional
  aparte, sin tocar la CI.
- Efecto de presas: usar solo estaciones aguas arriba para la GEV.

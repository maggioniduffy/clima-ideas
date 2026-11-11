# Fase 2 — Crecidas de ríos

Estado: en curso (F2.1, F2.2 y F2.4 hechas) · Depende de: 1, acceso a caudales (F0.8) · Refs: `docs/architecture.md`

## Pregunta

¿Qué tan raras fueron las crecidas grandes y qué parte explican los ríos atmosféricos o la lluvia sobre nieve?
Alcance real: ríos Neuquén, Agrio y Curi Leuvú. El Limay queda fuera: no hay estación natural con datos.

## Datos

Caudal medio diario del SNIH (contiene la BDHI; parámetro 101, año hidrológico desde abril; citar SIPH/SNIH y fecha
de actualización). Con datos y aguas arriba de las presas: 12004 Paso de Indios (Neuquén, 1945–2026), 12010 Bajada
del Agrio (1953–2026), 12012 Los Maitenes (Curi Leuvú, 1989–2021). 11803 Paso Flores (Limay) excluida por regulada;
12013 Chos Malal y 11804 Paso Limay no devuelven datos. AIC: restringido. Para lluvia sobre nieve (F2.3): isoterma
de 0 °C de ERA5 (`deg0l`, ya descargada en F1.1) y nieve de ERA5-Land. CAMELS-CL (F2.5): PANGAEA, CC-BY-4.0, solo Chile.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F2.1 ✅ | Ingesta de caudales diarios con control de huecos | Sonnet escribe, opencode descarga | Parquet por estación + reporte de huecos |
| F2.2 ✅ | Máximos anuales y GEV con intervalo de confianza (`pyextremes`) | Sonnet | Unit: recupera parámetros de una GEV sintética |
| F2.3 | Etiquetar crecidas mayores con el catálogo F1.3 y lluvia sobre nieve | opencode | Tabla de crecidas con causa probable + sensibilidad a la ventana de días entre río atmosférico y pico |
| F2.4 ✅ | Capa: estaciones + panel de período de retorno y serie | Sonnet | e2e: elegir estación, ver curva y crecidas |
| F2.5 | ML (alta): LSTM de caudal diario; preentreno en CAMELS-CL, ajuste en Neuquén; baselines GR4J y persistencia | Sonnet implementa, opencode entrena, Opus revisa métricas; advisor si hace falta | NSE/KGE en test vs. baselines |
| F2.6 | Ficha de crecida: pronóstico LSTM de próximos días con incertidumbre vs. observado | Sonnet | e2e sobre un evento pasado |
| F2.7 | Máximos anuales y caudal estacional por fase ENSO; GEV con ONI como covariable vs. estacionaria. Su resultado decide si se hace el modelo estacional F6.2 | Sonnet; advisor si hace falta | Comparación por verosimilitud + unit con GEV sintética dependiente de covariable |

## Avance

- F2.1 (2026-11-09): años completos 12004 80 de 82, 12010 66 de 73, 12012 25 de 32 (`reports/02/F2.1.md`).
- F2.2 (2026-11-09): 12004 xi = 0,336, Q100 = 10 649 m³/s (IC 5 980–20 908); el pico del 2023-06-26 (11 895 m³/s)
  da T ≈ 134 años por GEV (81 empírico). 12010 xi = 0,122 (`reports/02/F2.2.md`).
- F2.4 (2026-11-09): capa `flood-stations` con curva de período de retorno, serie y crecidas mayores.
- Detalle y decisiones: `odd/tasks/floods.md`.

## Entregable

Períodos de retorno con IC para una estación natural, crecidas etiquetadas por causa, LSTM comparado.

## Abierto

- 12012 Los Maitenes: xi = 0,631 con 25 años; el IC no es confiable y la capa lo debe decir.
- Calificador `D` en 336 filas de 12010: significado sin verificar.
- El bootstrap de F2.2 no cuenta ni registra los remuestreos que quedan en el límite xi = 0,99.
- F2.4: tema claro sin revisar a ojo.
- Efecto de presas: usar solo estaciones aguas arriba para la GEV.

# Fase 6 — Predicción a futuro (experimental)

Estado: en curso (F6.1, F6.2, F6.3 de día de riesgo, F6.4, F6.6, F6.8 y F6.9 hechos, F6.5 en código; registro diario con día de riesgo «Experimental» y climatología de caudal) · Depende de: 0 (F0.10), 2 (F2.5), 5 (F5.3) · Refs: `docs/architecture.md`

Mide si los modelos predicen mejor que la climatología algo que todavía no pasó. Desde el 2026-11-12 (`plan.md`,
Rumbo 7) una variable y anticipación que pasa la compuerta de evidencia se muestra como "Perspectiva de riesgo"
para usuarios técnicos; el resto queda "Experimental". No es una alerta oficial en ningún caso.

## Pregunta

Entrenando con datos pasados y actuales, ¿las predicciones de lo que viene aciertan más que los baselines?

```
datos pasados y actuales --- entrenamiento ---> predicciones futuras ---> verificación al llegar lo observado
```

## Horizontes

| Horizonte | Qué se predice | Entradas | Baselines |
|---|---|---|---|
| Corto (1–10 días) | Día de riesgo (F5.3) y caudal diario (LSTM F2.5) | ECMWF open data y GEFS operativos, ERA5T, caudal reciente | Climatología del día, persistencia |
| Estacional (1–6 meses) | Terciles de lluvia en cordillera, cantidad de ríos atmosféricos y caudal medio de la estación | Nieve y humedad de suelo ERA5-Land y caudal reciente primero; ONI actual y pronosticado (F0.10, C3S) como una entrada más | Climatología, persistencia, análogos de años con la misma fase ENSO |

## Datos

Los de las fases 1, 2, 3 y 5, más entradas operativas con su latencia (F0.8). Entrenamiento hasta la fecha de
emisión; nada posterior.

## Tareas

Orden: F6.1 y F6.4 primero, con baselines solos (climatología, persistencia), para que el registro junte
predicciones puntuadas antes del invierno de 2027; los modelos se suman cuando existan. F6.2 se hace solo si F2.7
encuentra señal de ENSO en el caudal; si no, el horizonte estacional queda en baselines y se informa así.

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F6.1 ✅ | Ingesta operativa idempotente de entradas actuales (ERA5T, ERA5-Land, ECMWF open data, GEFS, ONI, caudal); verificar antes la latencia real del caudal en tiempo real (SNIH dice no ser red de alerta; AIC restringida) | Sonnet escribe, Haiku corre | Latencia de caudal medida y anotada en `docs/research/data-access.md` + una corrida trae el último día disponible + unit de idempotencia |
| F6.2 ✅ (caudal 1–3 meses supera la climatología; lluvia y ríos atmosféricos no) | Modelo estacional (regresión logística y LightGBM) + baselines, validado según "Validación (F6.2)" | Sonnet implementa, Haiku entrena | RPS y Brier por año de test vs. cada baseline + unit de particiones sin fuga |
| F6.3 ✅ (día de riesgo; caudal bloqueado) | Corrida de corto plazo: F5.3 y LSTM F2.5 alimentados con pronósticos operativos | Sonnet | Predicción emitida para hoy con incertidumbre |
| F6.4 ✅ | Registro de predicciones congeladas: append-only con fecha de emisión, versión de modelo y hash de entradas | Sonnet | Unit: no se puede editar ni emitir con fecha pasada |
| F6.5 (código ✅) | Verificación prospectiva: puntuar cada predicción cuando llega lo observado; skill acumulado vs. baselines con IC bootstrap | Sonnet codifica, Haiku corre | Tabla de skill por horizonte + unit de métricas |
| F6.6 ✅ (código; en línea al mergear a `main`) | Capa de predicciones en el visor con dos estados por variable y anticipación ("Experimental" / "Perspectiva de riesgo"): probabilidad vs. climatología, incertidumbre, baseline, historial de aciertos con n prospectivo, POD y FAR; avisos fijos de "Avisos obligatorios"; campo opcional `outlook_status` en el manifiesto | Sonnet | e2e: ver predicción, su estado, su historial, los avisos y los enlaces oficiales |
| F6.7 | Prueba de caudal alto: dejando afuera cada crecida grande (junio de 2023 incluida), con entradas de pronóstico y la latencia de caudal de F6.1, ¿la probabilidad de superar el umbral sube sobre la climatología antes de cada pico y los intervalos cubren los picos cerca de lo nominal? | Haiku corre, Sonnet codifica | Tabla por crecida y anticipación con veredicto + unit de partición sin fuga |
| F6.8 ✅ (código; sin promociones hasta la temporada 2027) | Promoción y descenso: aplica la compuerta por variable, anticipación y región, registra cada cambio de estado con fecha, evidencia y aprobación del usuario; desciende sola según la regla de descenso | Sonnet | Unit: no promueve sin aprobación ni con anticipaciones salteadas; desciende con BSS < 0 en la temporada o con cambio de versión; el descenso de una anticipación arrastra a las más largas |
| F6.9 ✅ (BSS 0,09 conjunto con ERA5; con IVT GEFS ninguna anticipación pasa) | Propuesta (2026-11-13), depende de F5.9 y F5.10: climatología condicional de caudal alto a partir de la tabla evento × estación (`responses.json`, V8 de la fase 1): frecuencia de superar el umbral según IVT máximo, isoterma de 0 °C y mes. Es un modelo simple más para el criterio 3 de la compuerta, no un atajo: pasa por los mismos criterios | Sonnet codifica, Haiku corre | BSS vs. climatología y persistencia con IC bootstrap por evento + unit de partición sin fuga |

## Validación (F6.2)

Nada de k-fold aleatorio: días vecinos y meses de un mismo año ENSO filtran información entre entrenamiento y test.

- **Externa, un año afuera con separación:** cada año hidrológico es una vez el test; se quitan del entrenamiento
  los 6 meses anteriores y posteriores a ese año. Se informa el skill por año y por fase ENSO.
- **Interna, anidada:** hiperparámetros y selección de variables se eligen solo dentro del entrenamiento de cada
  partición externa, con origen móvil sobre esos años. El año de test externo nunca toca esa elección.
- **Entradas tal como estaban disponibles en la fecha de emisión:** pronósticos con reforecasts GEFS (F5.1), no
  con ERA5 del período pronosticado; ONI y pronóstico ENSO del mes de emisión, no la versión revisada posterior
  (sin verificar si hay archivo histórico de pronósticos IRI/C3S: lo resuelve F0.8); ERA5/ERA5-Land solo hasta
  la fecha de emisión menos su latencia operativa.
- **Control:** el mismo esquema con origen móvil puro (entrenar hasta el año t, predecir t+1), para ver si el
  skill cae en los años recientes.
- Unit: ninguna fecha de test, separación incluida, aparece en el entrenamiento de su partición, y ninguna entrada
  tiene fecha de disponibilidad posterior a la de emisión.

Nota F6.9 (2026-11-22): F5.10 muestra que el IVT pronosticado (GEFS c00) conserva acierto 1–2 días más que la
lluvia (hasta 6–8 días), pero no gradúa la intensidad dentro de los eventos: usarlo como predictor de llegada,
junto con la lluvia pronosticada (`reports/05/F5.10.md`).

## Compuerta de evidencia (perspectiva de riesgo)

Decidida el 2026-11-12 (consulta al advisor en `odd/tasks/risk-outlook-rule.md`). Se aplica por variable, por
anticipación y por región (o estación, para caudal): cada región tiene su propio estado y una región que no pasa
no bloquea a otra; hasta pasarla, la salida es "Experimental".

**Evento independiente** (criterios 1 y 5): días de riesgo seguidos de un mismo sistema cuentan como uno, y un mismo
sistema que afecta a varias regiones también cuenta como uno. Los mínimos de eventos se cuentan sobre estos eventos
agrupados de todas las regiones, nunca como suma de conteos por región; el BSS y su IC se calculan por región.

1. **Hindcast (F5.8, F6.2):** BSS > 0 frente a la climatología y frente al baseline simple (regresión logística para
   día de riesgo; persistencia y GR4J para caudal), con IC 95 % bootstrap por evento o año que excluya 0, en test
   temporal y con entradas tal como estaban disponibles. Al menos **20 eventos independientes** en test. Si el
   modelo mostrado es el propio baseline simple (criterio 3), basta superar a la climatología y a la persistencia.
2. **Anticipaciones contiguas:** la anticipación L pasa solo si pasan todas las más cortas.
3. **Modelo más simple:** se muestra el modelo más simple que supera a climatología y persistencia, y puede ser el
   baseline simple (regresión logística, GR4J); LightGBM o el LSTM solo si superan con IC al baseline simple. Misma
   regla para día de riesgo y caudal.
4. **Caudal alto (F6.7):** solo como probabilidad de superar un umbral, nunca magnitud del pico, y solo si pasa la
   prueba dejando afuera cada crecida grande. Caudales fuera del rango de entrenamiento se muestran como "fuera del
   rango entrenado".
5. **Prospectiva (F6.4, F6.5):** una temporada húmeda completa (mayo–septiembre) y al menos **10 eventos
   independientes** agrupados en el registro, lo que llegue último; el BSS prospectivo no contradice al hindcast
   (estimación ≥ 0).
6. **Aprobación:** cada promoción la aprueba el usuario (F6.8).
7. **Descenso automático:** vuelve a "Experimental" si el BSS prospectivo de una temporada es < 0, o si cambia la
   versión del modelo o de sus entradas (el historial es por versión congelada). Si desciende una anticipación,
   descienden también todas las más largas de esa variable y región (criterio 2).

Sin tope fijo de falsas alarmas: con eventos raros el FAR es alto por construcción. POD y FAR se muestran junto a la
salida, sin destacar ninguna probabilidad. Las probabilidades mostradas se limitan al bin más alto con muestras
suficientes en el hindcast.

## Avisos obligatorios

En toda salida de esta fase, en español:

- "No es una alerta oficial. Ante una diferencia, siga los avisos de SMN, AIC y Defensa Civil", con enlaces.
- Estado ("Experimental" o "Perspectiva de riesgo"), fecha de emisión, versión del modelo, período de
  entrenamiento, fuentes de entrada y su latencia.
- Probabilidad junto a la climatológica, con incertidumbre; historial de aciertos con n, POD y FAR.
- Público: usuarios técnicos; no indica qué hacer.

## Fuera de alcance

Niveles de alerta, colores o umbrales destacados; consejos de acción; mancha de inundación o lugares de impacto;
magnitud de picos o hidrogramas; perspectivas convectivas o subdiarias; horizonte estacional como perspectiva (queda
"Experimental"); avisos por correo, Telegram u otro envío; cualquier texto que sugiera reemplazar a SMN, AIC o
Defensa Civil.

## Entregable

Predicciones emitidas y congeladas antes de conocer el resultado, con su skill frente a climatología medido sobre
lo que ya se observó.

## Reglas

- Toda predicción muestra incertidumbre, fuente, período de entrenamiento y fecha de emisión.
- Nada se evalúa con datos que el modelo vio; la verificación usa solo predicciones del registro F6.4.
- Si un modelo no supera a la climatología, se informa así.

## Avance

- F6.4 (2026-11-21): registro en `backend/src/clima_nqn/forecast/registry.py`. JSON Lines con append + fsync y cadena
  de hashes SHA-256 (`seq`, `prev_hash`, `record_hash`). `verify()` detecta edición, borrado o reorden. Un recorte al
  final deja la cadena válida, así que el hash de cabeza que devuelve `verify()` se guarda aparte. La fecha de
  emisión la pone el reloj del registro (tolerancia ±5 min), `valid_date` = día de emisión + anticipación, y no se
  admiten duplicados por (versión, variable, región, anticipación, día). 17 unit. Todavía no emite predicciones:
  espera a F6.1.

- F6.1 (2026-11-22): `clima-nqn ops ingest` (`backend/src/clima_nqn/ops/ingest.py`) guarda cada día
  `<fuente>/<fecha>.parquet` de caudal SNIH (60 días), ONI, lluvia ERA5T por cuenca (14 días) y lluvia diaria por
  cuenca de ECMWF IFS (AWS) y GEFS (media y control) a 1–10 días, con `available_on`, licencia y un `manifest.json`
  con el rezago. Escritura atómica, se saltea lo ya guardado, una fuente caída no frena a las otras. 19 unit.
  Latencias medidas (`reports/06/F6.1-latency.md`): **SNIH no tiene tiempo real**: último caudal el 2026-03-31 en
  Paso de Indios y Bajada del Agrio (236 días), 2021 o nada en las otras cuatro; ERA5T 7 días con días enteros
  vacíos; ECMWF y GEFS < 1 día; el portal de ECMWF guarda ~3 días, por eso se archiva a diario. Corrida real:
  4 de 5 fuentes ok (caudal: sin filas recientes). Solo 3 estaciones tienen caja de cuenca (`snow.UPSTREAM_BOXES`).
- Decisión del usuario (2026-11-22): archivar pronósticos y emitir solo climatología de caudal; la persistencia
  queda en pausa hasta tener caudal en tiempo real (pedir acceso a la AIC). La climatología se puntúa cuando SNIH
  cargue los datos; las predicciones siguen congeladas antes de conocerlos.
- Baselines (2026-11-22): `forecast/baselines.py`, climatología del día del año (±7 días, cuantiles 5–95 %) y
  persistencia (razón logarítmica por anticipación y mes, horizonte efectivo = anticipación + rezago), variables
  `caudal_diario` y `p_caudal_alto` (umbral provisional p95 del período de entrenamiento, intervalo de Wilson 90 %).
  `clima-nqn forecast emit`. El registro ganó un campo libre `details` (compatible hacia atrás).
- F6.5 código (2026-11-22): `forecast/scoring.py`, error absoluto, CRPS aproximado por pinball sobre los cuantiles
  5–95 % y Brier; skill 1 − S/S_clim sobre casos pareados, IC 95 % bootstrap por bloques de semana, POD y FAR con
  p > 0,5, "insuficiente" con menos de 10 eventos. Solo puntúa registros del registro F6.4. `clima-nqn forecast score`.
- Dónde corre (Abierto, decidido 2026-11-22): `.github/workflows/forecast-daily.yml`, todos los días a las 10:17 UTC
  (ingesta, emisión y, los lunes, puntuación), con commit sin force a la rama `data/forecast-registry`. El
  entrenamiento es una foto congelada de SNIH (`training/flow`) cuyo hash va en la versión del modelo. Los
  programados solo corren desde `main`.
- F6.3 (2026-11-22): `ops ingest --sources gefs_regions,era5t_regions` (GEFS 0,25° operativo, 5 miembros, medias
  regionales de F5.3; ERA5T regional para puntuar) y `forecast emit-riskday` con la logística congelada
  (`backend/models/riskday-logistic-v1.json`, ajuste 2000–2014, reproduce el BSS de F5.8 con diferencia 0) más su
  climatología mensual; 60 registros por día, «Experimental». `forecast score --era5t-regions` puntúa
  `p_dia_riesgo`. Corre en `forecast-daily.yml`. Caudal (LSTM) no: sin caudal en tiempo real. Informe
  `reports/06/F6.3.md`.

- Tope (2026-11-22): `hindcast gate` agrega `prob_cap_vigente` (bins de confiabilidad con L−1, L y L+1, no creciente):
  100 % hasta 3–4 días, 40–70 % a 7 y 30–40 % a 10; el resto de F5.8 no cambió. Va en
  `backend/models/riskday-logistic-v1.caps.json` (el JSON del modelo y su versión no cambian) y `emit-riskday` lo
  copia a `details.prob_cap`.
- F6.8 (2026-11-22): `forecast/status.py`, bitácora `status/outlook.jsonl` con cadena SHA-256. `forecast promote`
  exige `--approved-by` y `--approved-on`, pase de hindcast (F5.8), temporada mayo–sep completa con ≥ 10 eventos
  agrupados entre regiones y skill ≥ 0, y anticipaciones contiguas; nunca la corre el workflow. `forecast
  demote-auto` (job diario) desciende con skill < 0 en la última temporada completa o con cambio de versión, y
  arrastra a las anticipaciones más largas. `forecast score` gana la tabla por temporada (`seasons`) y los eventos
  agrupados (`events_pooled`). 20 unit.

- F6.6 (2026-11-22): capa `forecast-outlook` (`clima-nqn forecast outlook-layer`: última emisión de la logística y su
  climatología, estado F6.8, hindcast F5.8, historial prospectivo F6.5, avisos y enlaces) y `ForecastPanel` en el
  visor: probabilidad junto a la climatológica con intervalos, "> tope" (también en los extremos del intervalo),
  estado en texto neutro, historial con n, POD y FAR o "Historial insuficiente". El manifiesto gana `outlook_status`
  opcional. `clima-nqn publish --layer` sube una sola capa y fusiona su entrada en el `layers.json` en línea (se niega
  si no lo puede leer). El job diario construye y publica la capa al bucket `nqn`. e2e `web/e2e/forecast.spec.ts`.
  Enlace a Defensa Civil igual al del panel de F5.6, sin verificar (no se pudo abrir desde el entorno).

- F6.9 (2026-11-23): `stages/flood/conditional_clim.py`, `clima-nqn flow conditional-clim`. Tabla evento × estación
  con la regla V8 (433 eventos, 1137 pares); superar el p95 del caudal diario según terciles de IVT máximo, terciles de
  isoterma de 0 °C y temporada (mayo–sep), contraído hacia la frecuencia de la estación (Beta, 2 pseudo-eventos);
  dejando afuera grupos de eventos con separación de 10 días. Entradas ERA5: BSS 0,09 [0,04; 0,14] frente a la
  climatología y 0,10 [0,02; 0,19] frente a la persistencia (no operativa), conjunto; por estación solo 12012 excluye 0.
  Sensibilidad: con la mediana de los máximos anuales como umbral, 0,05 [−0,01; 0,10]. Con IVT GEFS c00 (F5.10):
  0,06 a 1 día y < 0 desde 7, ningún IC excluye 0 (el IVT GEFS es media diaria y el de ERA5 máximo horario: sin
  corregir). Informe `reports/06/F6.9.md`. En la tabla de F6.7 no entra por día de emisión (pide rasgos de evento).
- F6.2 (2026-11-23): paquete `stages/seasonal`, `clima-nqn seasonal fetch-state|validate|report|reference`. Sin ENSO
  como entrada: nieve y agua de suelo ARCO-ERA5 a la emisión − 5 días, lluvia de 30 y 90 días, mes y anticipación.
  Validación de "Validación (F6.2)": 44 años de test, separación de 6 meses, selección anidada; control de origen móvil.
  RPSS frente a la climatología: caudal medio 12004 +0,16 [0,10; 0,22] a 1 mes y +0,09 a 3; 12010 +0,10 a 1 mes y
  +0,07 a 3; desde 4 meses el IC incluye 0. Lluvia en cordillera −0,01; ríos atmosféricos sin skill frente a la
  climatología empírica. El caudal pierde contra la persistencia del caudal del mes anterior, que no existe al emitir.
  Modelos congelados `backend/models/seasonal-v1/` (logística). Emisión mensual «Experimental» (`forecast
  emit-seasonal`, día 1 en `forecast-daily.yml`): baselines para las cuatro variables y la logística solo para caudal a
  1–3 meses; variable `seas_p_tercil_alto`, `lead_days` hasta el primer día del mes objetivo. Informe
  `reports/06/F6.2.md`.

## Abierto

- Pronóstico ENSO: IRI ya no ofrece descarga de datos; queda C3S por CDS. Archivo histórico de pronósticos emitidos:
  sin verificar.
- "Modelo bueno" para mostrarse como perspectiva: lo fija la compuerta de evidencia (2026-11-12). F5.8 (2026-11-22):
  ~14 eventos independientes agrupados por temporada mayo–septiembre (13,6 en test), así que alcanza un invierno.
  Pasan el hindcast: día de riesgo con la logística hasta 9 (cordillera norte), 10 (sur) y 7 días (Confluencia).
- Caudal en tiempo real: SNIH no lo tiene; pedir a la AIC acceso operativo (restringido). Sin eso, F6.3 y F6.7 de caudal no son verificables en el día.
- `registry.append` relee la cadena entera en cada llamada; la emisión usa `append_many` (una verificación por lote).
- ARCO-ERA5 iba 6,2 días atrasado el 2026-11-23 (F6.2 supuso 5): si falta la hora de emisión − 5 días, la emisión
  estacional sale solo con baselines (`model_skipped`). En la prueba del 2026-11-01 el agua de suelo estaba +2 a +4 σ:
  extrapolación; falta marcar entradas fuera del rango entrenado.
- La verificación estacional tarda meses en juntar muestras; el hindcast de F6.2 da la primera estimación.

## Plan de cierre de la fase (2026-11-22)

Cuatro olas, en este orden por el calendario (la temporada prospectiva mayo–sep 2027 solo cuenta si el día de
riesgo ya se emite antes de mayo): 1) F6.3 + F6.5 de día de riesgo; 2) tope de probabilidad, F6.8 y F6.6;
3) F6.7 y F6.9 (caudal alto, hindcast); 4) F6.2 estacional. La fase queda "en curso" hasta la temporada 2027.

Decisiones del usuario (2026-11-22):

- F6.2 se hace **sin ENSO como entrada** (nieve y humedad de suelo, lluvia previa), aunque F2.7 no pasó su
  compuerta; ENSO queda como baseline de análogos. El estacional nunca se promueve.
- F6.3 usa la logística **congelada con el ajuste 2000–2014**, el mismo modelo que evaluó F5.8.
- Tope de probabilidad: confiabilidad agrupando las anticipaciones L−1, L y L+1, con tope no creciente en L; por
  encima se muestra "> tope".

Decisiones de implementación: GEFS operativo 0,25° (`pgrb2sp25`) con los 5 miembros del reforecast (`c00`,
`p01`–`p04`); incertidumbre por 200 bootstraps de bloques de eventos de los coeficientes (intervalo 90 %);
nieve y humedad de suelo de ARCO-ERA5 (`sd`, `swvl1–3`) en vez de ERA5-Land (ERA5-Land: sensibilidad pendiente).
El archivo operativo de `noaa-gefs-pds` cubre junio de 2023 (comprobado), así que F6.7 puede incluir esa crecida.

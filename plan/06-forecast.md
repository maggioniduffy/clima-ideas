# Fase 6 — Predicción a futuro (experimental)

Estado: pendiente · Depende de: 0 (F0.10), 2 (F2.5), 5 (F5.3) · Refs: `docs/architecture.md`

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
| F6.1 | Ingesta operativa idempotente de entradas actuales (ERA5T, ERA5-Land, ECMWF open data, GEFS, ONI, caudal); verificar antes la latencia real del caudal en tiempo real (SNIH dice no ser red de alerta; AIC restringida) | Sonnet escribe, opencode corre | Latencia de caudal medida y anotada en `docs/research/data-access.md` + una corrida trae el último día disponible + unit de idempotencia |
| F6.2 | Modelo estacional (regresión logística y LightGBM) + baselines, validado según "Validación (F6.2)" | Sonnet implementa, opencode entrena; advisor si hace falta | RPS y Brier por año de test vs. cada baseline + unit de particiones sin fuga |
| F6.3 | Corrida de corto plazo: F5.3 y LSTM F2.5 alimentados con pronósticos operativos | Sonnet | Predicción emitida para hoy con incertidumbre |
| F6.4 | Registro de predicciones congeladas: append-only con fecha de emisión, versión de modelo y hash de entradas | Sonnet | Unit: no se puede editar ni emitir con fecha pasada |
| F6.5 | Verificación prospectiva: puntuar cada predicción cuando llega lo observado; skill acumulado vs. baselines con IC bootstrap | Sonnet codifica, opencode corre | Tabla de skill por horizonte + unit de métricas |
| F6.6 | Capa de predicciones en el visor con dos estados por variable y anticipación ("Experimental" / "Perspectiva de riesgo"): probabilidad vs. climatología, incertidumbre, baseline, historial de aciertos con n prospectivo, POD y FAR; avisos fijos de "Avisos obligatorios"; campo opcional `outlook_status` en el manifiesto | Sonnet | e2e: ver predicción, su estado, su historial, los avisos y los enlaces oficiales |
| F6.7 | Prueba de caudal alto: dejando afuera cada crecida grande (junio de 2023 incluida), con entradas de pronóstico y la latencia de caudal de F6.1, ¿la probabilidad de superar el umbral sube sobre la climatología antes de cada pico y los intervalos cubren los picos cerca de lo nominal? | opencode corre, Sonnet codifica | Tabla por crecida y anticipación con veredicto + unit de partición sin fuga |
| F6.8 | Promoción y descenso: aplica la compuerta por variable, anticipación y región, registra cada cambio de estado con fecha, evidencia y aprobación del usuario; desciende sola según la regla de descenso | Sonnet | Unit: no promueve sin aprobación ni con anticipaciones salteadas; desciende con BSS < 0 en la temporada o con cambio de versión; el descenso de una anticipación arrastra a las más largas |

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

## Abierto

- Pronóstico ENSO: IRI ya no ofrece descarga de datos; queda C3S por CDS. Archivo histórico de pronósticos emitidos:
  sin verificar.
- "Modelo bueno" para mostrarse como perspectiva: lo fija la compuerta de evidencia (2026-11-12). Si F5.8 muestra
  menos de 10 eventos independientes esperables por temporada, la espera prospectiva pasa a dos inviernos.
- Dónde corre la ingesta periódica (cron local o CI programado). Decide Opus en F6.1.
- La verificación estacional tarda meses en juntar muestras; el hindcast de F6.2 da la primera estimación.

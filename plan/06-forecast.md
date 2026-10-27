# Fase 6 — Predicción a futuro (experimental)

Estado: pendiente · Depende de: 0 (F0.10), 2 (F2.5), 5 (F5.3) · Refs: `docs/architecture.md`

Experimental: nadie la usa para decidir. Sirve para medir si los modelos predicen mejor que la climatología
algo que todavía no pasó.

## Pregunta

Entrenando con datos pasados y actuales, ¿las predicciones de lo que viene aciertan más que los baselines?

```
datos pasados y actuales --- entrenamiento ---> predicciones futuras ---> verificación al llegar lo observado
```

## Horizontes

| Horizonte | Qué se predice | Entradas | Baselines |
|---|---|---|---|
| Corto (1–10 días) | Día de riesgo (F5.3) y caudal diario (LSTM F2.5) | ECMWF open data y GEFS operativos, ERA5T, caudal reciente | Climatología del día, persistencia |
| Estacional (1–6 meses) | Terciles de lluvia en cordillera, cantidad de ríos atmosféricos y caudal medio de la estación | ONI actual y pronosticado (F0.10, IRI/C3S), nieve y humedad de suelo ERA5-Land, caudal reciente | Climatología, persistencia, análogos de años con la misma fase ENSO |

## Datos

Los de las fases 1, 2, 3 y 5, más entradas operativas con su latencia (F0.8). Entrenamiento hasta la fecha de
emisión; nada posterior.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F6.1 | Ingesta operativa idempotente de entradas actuales (ERA5T, ERA5-Land, ECMWF open data, GEFS, ONI, caudal) | Sonnet escribe, opencode corre | Una corrida trae el último día disponible + unit de idempotencia |
| F6.2 | Modelo estacional (regresión logística y LightGBM) + baselines, validado según "Validación (F6.2)" | Sonnet implementa, opencode entrena | RPS y Brier por año de test vs. cada baseline + unit de particiones sin fuga |
| F6.3 | Corrida de corto plazo: F5.3 y LSTM F2.5 alimentados con pronósticos operativos | Sonnet | Predicción emitida para hoy con incertidumbre |
| F6.4 | Registro de predicciones congeladas: append-only con fecha de emisión, versión de modelo y hash de entradas | Sonnet | Unit: no se puede editar ni emitir con fecha pasada |
| F6.5 | Verificación prospectiva: puntuar cada predicción cuando llega lo observado; skill acumulado vs. baselines con IC bootstrap | Sonnet codifica, opencode corre | Tabla de skill por horizonte + unit de métricas |
| F6.6 | Capa "Experimental" en el visor: predicciones vigentes, incertidumbre e historial de aciertos; aviso fijo "Experimental, no es una alerta"; campo opcional `experimental` en el manifiesto | Sonnet | e2e: ver predicción, su historial y el aviso |

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

## Entregable

Predicciones emitidas y congeladas antes de conocer el resultado, con su skill frente a climatología medido sobre
lo que ya se observó.

## Reglas

- Toda predicción muestra incertidumbre, fuente, período de entrenamiento y fecha de emisión.
- Nada se evalúa con datos que el modelo vio; la verificación usa solo predicciones del registro F6.4.
- Si un modelo no supera a la climatología, se informa así.

## Abierto

- Qué cuenta como "modelo bueno" (por ejemplo: skill > 0 vs. climatología con IC que excluya 0 tras N
  predicciones). Lo decide el usuario después de ver resultados.
- Dónde corre la ingesta periódica (cron local o CI programado). Decide Opus en F6.1.
- La verificación estacional tarda meses en juntar muestras; el hindcast de F6.2 da la primera estimación.

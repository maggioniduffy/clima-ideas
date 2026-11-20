# Fase 2 — Armonización MODIS–VIIRS

Estado: pendiente · Depende de: 1 · Refs: `../plan/06-forecast.md` (Validación F6.2)

## Pregunta

¿Cómo convertir 2000–hoy en una sola serie donde el sensor de origen ya no importe, en las dos escalas y sin
cortarse cuando MODIS deje de operar?

## Enfoque

Solapamiento 2012–hoy: los dos sensores miden lo mismo. VIIRS ve más focos chicos por su resolución (375 m vs.
1 km), y los horarios de paso difieren. Con ese período se calibra en los dos sentidos:

- **Hacia MODIS:** VIIRS → "MODIS-equivalente". Serie larga y comparable con la literatura.
- **Hacia VIIRS (serie inversa):** MODIS → "VIIRS-equivalente" para 2000–2011. Estima cuántos focos habría
  registrado VIIRS en un área y período, con incertidumbre; no ubica focos individuales que MODIS no detectó.
  En la UI dice "estimado", nunca "detectado".
- **Continuidad:** cuando MODIS se apague, cada año nuevo de VIIRS (S-NPP, NOAA-20, NOAA-21 y siguientes JPSS,
  sin verificar fechas) entra a las dos series con la calibración congelada.

Supervisado, no aprendizaje por refuerzo: hay pares observados (MODIS y VIIRS, misma celda y día) y no hay
agente, entorno ni recompensa.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| SA2.1 | VIIRS reagrupado a celdas de 1 km por día (una detección por celda), pares de pasos similares (Aqua ~ S-NPP) | Sonnet | Unit: N detecciones en una celda cuentan como 1 |
| SA2.2 | Baseline: factor de escala MODIS/VIIRS por región y mes del año, en los dos sentidos | Sonnet | Unit con datos sintéticos de factor conocido |
| SA2.3 | Ajuste de cuantiles por región | Sonnet | Unit: recupera la distribución objetivo en sintético |
| SA2.4 | LightGBM hacia MODIS: conteo MODIS-equivalente desde conteos VIIRS por confianza, FRP, día/noche, mes, latitud, cobertura del suelo | Sonnet implementa, opencode entrena | Error por año de test vs. SA2.2 y SA2.3 |
| SA2.5 | Validación año afuera con separación y selección anidada (esquema F6.2 de clima-ideas) | Sonnet | Unit: ningún día de test en entrenamiento |
| SA2.6 | Efecto de la deriva orbital de Terra y Aqua en los años recientes (sin verificar magnitud) | opencode | `reports/02/SA2.6.md` con cifras |
| SA2.7 | Serie inversa: LightGBM con objetivo Poisson o Tweedie que estima conteos VIIRS por celda y día desde conteo y FRP de MODIS, ángulo de escaneo, día/noche, mes, cobertura del suelo y focos de días vecinos; intervalos por regresión cuantílica | Sonnet implementa, opencode entrena | Error y cobertura de intervalos por año de test vs. SA2.2 inverso |
| SA2.8 | Validación hacia atrás: entrenar con 2016 en adelante y evaluar en 2012–2015, para simular estimar el pasado y ver si la relación cambia con el tiempo | Sonnet | Tabla de error por región y año; unit: ningún año de test en entrenamiento |
| SA2.9 | Áreas quemadas MCD64A1 (2000–) como variable de SA2.7 para fuegos que MODIS no marcó como foco; Landsat solo si SA0.8 confirma acceso y cobertura | Sonnet escribe, opencode corre | Error de SA2.7 con y sin la variable |
| SA2.10 | Continuidad post-MODIS: calibración congelada con versión y fecha; ingesta de un año VIIRS nuevo actualiza las dos series sin recalibrar | Sonnet | Unit: agregar un año no cambia los valores previos |
| SA2.11 | Serie final en dos escalas (MODIS-eq y VIIRS-eq) con banda de incertidumbre; manifiesto con método, versión de calibración, fuente y período | Sonnet | Capa publicada + e2e de carga |

## Entregable

Tabla de error por método, sentido y región, incluida la validación hacia atrás. Se publica el método que gane en
test; si LightGBM no supera al factor de escala, se informa así y se usa el factor. Tendencia observada
2000–hoy por región con su intervalo; ninguna proyección de décadas (requiere escenarios climáticos, fuera de
alcance).

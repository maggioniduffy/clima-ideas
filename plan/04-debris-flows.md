# Fase 4 — Aluviones: susceptibilidad y un caso a fondo

Estado: pendiente · Depende de: 2, 3 (lluvias de diseño) · Refs: `docs/architecture.md`

## Pregunta

¿Dónde se concentra el agua sobre rutas y localidades, y con qué lluvia?

## Datos

Copernicus GLO-30 (reusar F0.5), suelo y cobertura (F0.8), lluvias de diseño de F2 y F3.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F4.1 | Cuencas chicas con desagüe sobre Rutas 5 y 7 y barrios bajo bardas (pysheds) | Sonnet | GeoParquet de cuencas + unit con DEM sintético |
| F4.2 | Caudal pico por SCS-CN para cada lluvia de diseño | Sonnet | Unit contra ejemplo de manual |
| F4.3 | Capa: cuencas ordenadas por caudal pico | Sonnet | e2e: elegir cuenca e inspeccionar |
| F4.4 | Caso HEC-RAS 2D de un cañadón vs. evento conocido | Opus (difícil) + usuario si requiere GUI | Mancha simulada vs. registro del evento |
| F4.5 | ML (alta): emulador U-Net entrenado con cientos de simulaciones | Sonnet implementa, opencode corre simulaciones y entreno | Error vs. HEC-RAS medido |
| F4.6 | Escenarios: elegir período de retorno y ver la mancha del emulador | Sonnet | e2e del selector y la mancha |

## Entregable

Mapa de cuencas por caudal pico + un caso HEC-RAS validado + emulador comparado.

## Abierto

- HEC-RAS en Linux: probar el motor 2D por línea de comando; si no, el usuario corre la GUI. Decide Opus en F4.4.
- Sin inventario de aluviones: no hay ML de susceptibilidad (ver `NEUQUEN_PLAN.md`).

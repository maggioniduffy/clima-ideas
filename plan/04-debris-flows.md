# Fase 4 — Aluviones: susceptibilidad y un caso a fondo

Estado: pendiente · Depende de: 2, 3 (lluvias de diseño); la extensión, de F4.4a · Refs: `docs/architecture.md`

## Pregunta

¿Dónde se concentra el agua sobre rutas y localidades, y con qué lluvia?

## Datos

Copernicus GLO-30 (reusar F0.5), suelo y cobertura (F0.8), lluvias de diseño de F2 y F3.

## Tareas

Núcleo: F4.1–F4.3. Extensión: F4.4–F4.6, solo si F4.4a da bien (ver `plan.md`, Rumbo 2). La fase no bloquea a la 5 ni a la 6.

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| F4.1 | Cuencas chicas con desagüe sobre Rutas 5 y 7 y barrios bajo bardas (pysheds) | Sonnet | GeoParquet de cuencas + unit con DEM sintético |
| F4.2 | Caudal pico por SCS-CN para cada lluvia de diseño | Sonnet | Unit contra ejemplo de manual |
| F4.3 | Capa: cuencas ordenadas por caudal pico | Sonnet | e2e: elegir cuenca e inspeccionar |
| F4.4a | Prueba de factibilidad: motor 2D de HEC-RAS por línea de comando en Linux sobre un caso de ejemplo, y un evento neuquino con mancha o daños documentados para comparar | Opus; advisor si hace falta | Informe con sí o no para cada punto; con un no, F4.4–F4.6 no se hacen |
| F4.4 | Caso HEC-RAS 2D de un cañadón vs. evento conocido | Opus (difícil; advisor si hace falta) + usuario si requiere GUI | Mancha simulada vs. registro del evento |
| F4.5 | ML (alta): emulador U-Net entrenado con cientos de simulaciones | Sonnet implementa, opencode corre simulaciones y entreno | Error vs. HEC-RAS medido |
| F4.6 | Escenarios: elegir período de retorno y ver la mancha del emulador | Sonnet | e2e del selector y la mancha |

## Entregable

Núcleo: mapa de cuencas por caudal pico. Extensión: un caso HEC-RAS validado y el emulador comparado.

## Abierto

- HEC-RAS en Linux: probar el motor 2D por línea de comando; si no, el usuario corre la GUI. Decide Opus en F4.4a.
- Sin inventario de aluviones: no hay ML de susceptibilidad (ver `NEUQUEN_PLAN.md`).

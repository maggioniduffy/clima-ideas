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
| F4.4a ✅ | Prueba de factibilidad: motor 2D de HEC-RAS por línea de comando en Linux sobre un caso de ejemplo, y un evento neuquino con mancha o daños documentados para comparar | Opus | Informe con sí o no para cada punto; con un no, F4.4–F4.6 no se hacen |
| F4.4 ⏸ | Caso HEC-RAS 2D de un cañadón vs. evento conocido | Opus (difícil) + usuario si requiere GUI | Mancha simulada vs. registro del evento |
| F4.5 ⏸ | ML (alta): emulador U-Net entrenado con cientos de simulaciones | Sonnet implementa, opencode corre simulaciones y entreno | Error vs. HEC-RAS medido |
| F4.6 ⏸ | Escenarios: elegir período de retorno y ver la mancha del emulador | Sonnet | e2e del selector y la mancha |

## Entregable

Núcleo: mapa de cuencas por caudal pico. Extensión: un caso HEC-RAS validado y el emulador comparado.

## Avance

- F4.1 y F4.2, código (2026-11-21): `backend/src/clima_nqn/stages/debris/` con pysheds 0.5 (D8 con relleno de
  depresiones) y SCS-CN (Ia = 0,2 S, Tc por el método del retardo SCS, hidrograma unitario triangular, qp = 0,208 A Q / Tp).
  Comando `clima-nqn debris catchments`. Cuencas chicas entre 0,1 y 25 km² (elección propia, sin verificar). CN es una
  entrada, todavía sin fuente. Hay 11 unit: DEM sintético en V y TR-55 con CN 80 y P = 5 in, Q = 2,89 in (número
  reproducido con la fórmula; página sin verificar). Corrida real pendiente: Overpass está bloqueado desde la sesión,
  así que faltan las líneas de las Rutas 5 y 7 y los barrios bajo las bardas.
- F4.4a (2026-11-21): informe `reports/04/F4.4a.md`, solo documentación (sin descargar ni correr binarios; la red de la
  sesión no llega a hec.usace.army.mil). Motor 2D en Linux: sin verificar; imágenes Docker de terceros muestran
  `RasUnsteady` para Linux que calcula desde entradas HDF ya preprocesadas en Windows, así que una geometría nueva
  pide la GUI. Evento con mancha documentada: no se encontró; abril de 2014 en la capital solo tiene prensa (204,6 mm
  SMN, sin polígono). Decisión de Opus: con el punto 2 en no, F4.4–F4.6 no se abren (Rumbo 2). Se reabren si aparece
  una mancha o un mapa de daños de un evento neuquino; ANUGA (Apache 2.0, Linux) queda anotado como motor alternativo.

## Abierto

- HEC-RAS en Linux: sin verificar (F4.4a). Para confirmarlo hace falta permitir hec.usace.army.mil y que el usuario
  autorice bajar y correr el binario de USACE.
- Mancha del evento de abril de 2014: buscar en UNCo, INA, municipio y Defensa Civil; sin ella la extensión no se abre.
- Sin inventario de aluviones: no hay ML de susceptibilidad (ver `NEUQUEN_PLAN.md`).

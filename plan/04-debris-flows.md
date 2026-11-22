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
| F4.1 ✅ | Cuencas chicas con desagüe sobre Rutas 5 y 7 y barrios bajo bardas (pysheds) | Sonnet | GeoParquet de cuencas + unit con DEM sintético |
| F4.2 ✅ | Caudal pico por SCS-CN para cada lluvia de diseño | Sonnet | Unit contra ejemplo de manual |
| F4.3 ✅ | Capa: cuencas ordenadas por caudal pico | Sonnet | e2e: elegir cuenca e inspeccionar |
| F4.4a ✅ | Prueba de factibilidad: motor 2D de HEC-RAS por línea de comando en Linux sobre un caso de ejemplo, y un evento neuquino con mancha o daños documentados para comparar | Opus | Informe con sí o no para cada punto; con un no, F4.4–F4.6 no se hacen |
| F4.4 ⏸ | Caso HEC-RAS 2D de un cañadón vs. evento conocido | Opus (difícil) + usuario si requiere GUI | Mancha simulada vs. registro del evento |
| F4.5 ⏸ | ML (alta): emulador U-Net entrenado con cientos de simulaciones | Sonnet implementa, Haiku corre simulaciones y entreno | Error vs. HEC-RAS medido |
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
- F4.1 corrida real (2026-11-21): blancos de IGN Argentina por WFS. Las "Rutas 5 y 7" son provinciales (RP 5 y RP 7,
  capa `ign:vial_provincial`, DVP Neuquén, recortadas a la provincia) y los barrios son las plantas urbanas de
  Neuquén, Plottier y Centenario (`ign:areas_de_asentamientos_y_edificios_020105`, base de 2010; extensión actual
  sin verificar). Hay 841 cuencas de 0,1 a 25 km²: RP 7 675, RP 5 83 y plantas urbanas 83.
- F4.2 y F4.3 (2026-11-21): CN por escenarios de TR-55 (decisión del usuario): matorral desértico en condición pobre,
  GH B 77, C 85 y D 88, con 85 como central. Son escenarios, no medidos; valores y tabla sin verificar contra el
  documento. Lluvia de diseño: IDF de F3.3 (celda IMERG de la capital, sin corregir, piso); usarla cerca de Añelo
  queda sin verificar. Capa `debris-catchments` con mapa por caudal pico, T y CN a elegir, ranking y ficha por
  cuenca. Hay pytest, vitest y e2e de Playwright. La mayor a T 10 y CN 85 es la cuenca 455 sobre la RP 7 (22,4 km²,
  14,6 m³/s, rango 8,6–17,8, duración crítica 12 h). Corregido el mismo día, ver la línea siguiente.
- F4.3 franjas (2026-11-21): la cuenca 455 y las franjas del cruce RP 5–RP 7 son un artefacto del D8 sobre terreno
  plano, no un error de código: el DEM ajusta un plano con RMSE 1,4 m en 2 km (pendiente ≈ 1 %), las direcciones
  decodifican bien (0,5 % de celdas cuesta arriba, todas por relleno) y el relleno no lo explica (7–13 % de celdas
  rellenadas). Se marca `planar_flow` si la rectangularidad es ≥ 0,85 con elongación ≥ 3, o si la elongación es ≥ 15
  (franjas diagonales escalonadas). Es un criterio propio, sin verificar: marca 334 de 841, con poca variación ante
  otros cortes. Esas cuencas quedan fuera del mapa y del ranking, salvo con el interruptor. Además, 10 cuencas que se
  superponen en más del 50 % con otra de distinto blanco (corrida urbana contra RP 7) quedan fuera del ranking.
  Quedan 497 cuencas con cauce en el ranking. La mayor a T 10 y CN 85 pasa a ser la 184 sobre la RP 5 (18,6 km²,
  12,8 m³/s, rango 7,4–15,6).
- F4.3 zoom (2026-11-21): `MapCanvas` recibe `focus` ({bounds, ifNeeded}) y encuadra con zoom máximo 13 y salto
  directo con `prefers-reduced-motion`. Elegir desde la lista siempre encuadra; un clic en el mapa encuadra solo si
  la cuenca está fuera de vista o se ve demasiado chica.
- F4.3 cauces (2026-11-21): `channel` por D-infinito (`reports/04/F4.3-channels.md`): área acumulada en el desagüe >= 0,05
  km² y prominencia >= 3 sobre la mediana de las celdas vecinas que alimentan el destino (±500 m); criterio propio, sin
  verificar. Separa las franjas finas (prominencia ≈ 1; 237 de las 334 de forma), pero deja como cauce a la 455, la 467
  y 11 más de más de 2 km² (prominencia 231–1459, contra 5000–9900 de 184, 185, 207 y 146). La capa usa `channel`: 583
  con cauce. Decisión de Opus (2026-11-21): se exigen las dos reglas (cauce por D-infinito y forma no laminar). Las
  bandas grandes convergen solo sobre una línea de celdas pegada a la ruta (el terraplén en el DEM), no sobre un cauce
  natural. Un K de 2500–3000 quedaba ajustado a seis cuencas elegidas a mano. Quedan 476 en el ranking (355 laminares,
  10 superpuestas); 455, 467 y 468 quedan fuera. Las 97 cuencas en las que las reglas no coinciden quedan sin verificar.
- Publicación (2026-11-21): capa `debris-catchments` subida al bucket R2 `nqn` (`catchments.geojson`, `peaks.json` y
  `manifest.json`). El índice `layers.json` se fusionó con el publicado (5 capas) en lugar de regenerarlo, porque la
  sesión solo tenía esta capa en `data/processed`. La web se desplegó desde `main` (Deploy web, corrida 4, éxito).

## Abierto

- F4.3: quedan unas pocas franjas cortas en el cruce RP 5–RP 7 (elongación < 15) que el criterio no atrapa.
- F4.3: los dos criterios (D-infinito y forma) son propios y sin verificar. Falta una referencia independiente
  (imagen satelital o terreno) para las 97 cuencas en las que las reglas no coinciden y para saber si el agua cruza
  la ruta en un punto (alcantarilla) o a lo largo de la traza.

- HEC-RAS en Linux: sin verificar (F4.4a). Para confirmarlo hace falta permitir hec.usace.army.mil y que el usuario
  autorice bajar y correr el binario de USACE.
- Mancha del evento de abril de 2014: buscar en UNCo, INA, municipio y Defensa Civil; sin ella la extensión no se abre.
- Sin inventario de aluviones: no hay ML de susceptibilidad (ver `NEUQUEN_PLAN.md`).

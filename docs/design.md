# Diseño

## Referencia

Dirección "B · Arena" del lienzo de diseño del usuario: https://claude.ai/artifact/D1rzvKD5vcN8ddDPvZstjN. Artboards: `Arena.dc.html` (claro), `Arena-Oscuro.dc.html` (oscuro), `Arena-Crecidas.dc.html` (estado de detalle de una capa) y `Arena-Movil.dc.html` (390 px de ancho). Los datos de los gráficos, `[fecha]`, `[Q]` y las cifras grandes de los artboards son marcadores: la app muestra solo valores reales. Reemplaza al mockup anterior (`Mockup.dc.html`). Inspiración: `inspiration/README.md`.

## Reglas de UI

- Una leyenda corta de una línea bajo cada cifra grande y la etiqueta "Experimental" están permitidas; ninguna otra etiqueta, badge ni descripción secundaria: jerarquía, color y forma explican.
- Nunca blanco ni negro puros: claros con tono crema, oscuros con tono carbón. Única excepción: `--chart-surface` (blanco puro en claro).
- Mismo layout en ambos temas: mismas regiones y mismas cajas; solo cambian los tokens.
- El acento es el mismo en ambos temas y se reserva para lo que importa (evento, selección, cabezal, barra destacada); siempre con `--casing` o texto oscuro.
- Solo lo que funciona: no se muestran navegación de secciones, filtros ni botones sin acción.
- Perspectiva de riesgo (reglas de `CLAUDE.md`): nunca niveles, colores, umbrales destacados ni consejos de acción. Siempre con incertidumbre, baseline, historial de aciertos y enlace a los avisos oficiales (SMN, AIC, Defensa Civil). Solo en el visor y solo si pasa la compuerta de `plan/06-forecast.md`; lo que no pasa se marca "Experimental". No es un sistema de alerta oficial.

## Tokens

Los valores viven en `web/src/theme/tokens.css` y `tokens.ts`; `tokens.test.ts` verifica que coincidan y el contraste WCAG AA de los pares de texto.

| Token | Claro | Oscuro | Uso |
|---|---|---|---|
| `--bg` | `#E4E2DC` | `#101114` | Página detrás del marco |
| `--frame-0` / `--frame-1` / `--frame-2` | `#F3F2EE` / `#F1EEE4` / `#F6E9B5` | `#1B1C20` / `#1D1D1F` / `#2E2814` | Degradado del marco, 160°, paradas 0 / 55 / 100 % |
| `--surface` | `#FBFAF7` | `#26272C` | Tarjetas |
| `--raised` | `#EFECE4` | `#2A2B30` | Botones neutros, pista del control segmentado, fila seleccionada |
| `--border` | `#D8D4C8` | `#3C3D43` | Trazos finos en gráficos y listas |
| `--text` | `#1C1C1C` | `#F1EFE8` | Texto |
| `--text-muted` | `#5E5E5E` | `#A9A9A4` | Leyendas |
| `--ctrl` | `#1C1C1C` | `#F1EFE8` | Píldora activa, botón primario |
| `--on-ctrl` | `#F3F2EE` | `#1B1C20` | Texto sobre `--ctrl` |
| `--inverse` / `--on-inverse` | `#1C1C1C` / `#F3F2EE` | `#F1EFE8` / `#1B1C20` | La única tarjeta invertida (perspectiva / modelo) |
| `--accent` | `#F5CF4B` | `#F5CF4B` | Selección, evento, cabezal, barra destacada |
| `--casing` | `#1C1C1C` | `#101114` | Contorno de las marcas de acento |
| `--chart-surface` | `#FFFFFF` | `#1B1C20` | Fondo de los gráficos: plano, sin textura |
| `--water` | `#3A6E8F` | `#7FA9C6` | Ríos en el mapa |
| `--relief-0..3` | `#A7AEAF` `#77848A` `#4A5A64` `#2A343B` | `#4E5F6A` `#7D8D96` `#B3BEC4` `#ECE7DC` | Relieve, de bajo a cumbres |

Comunes a ambos temas: `--main #3E505B`, `--secondary #A4AF69` (banda "normal", climatología), espaciado `--space-1..6` (4, 8, 12, 16, 24, 32 px), radios `--radius-sm/md/lg` (4, 8, 12 px), `--radius-card` (28 px), `--radius-frame` (36 px), `--radius-pill` (999 px) y las rampas IVT, de conteo, de lluvia y de escombros (sin cambios). En oscuro `--ctrl` es claro: el glifo de acento del botón de reproducir lleva contorno `--casing` en ese tema.

## Tipografía

Outfit (Google Fonts, 300/400/500/600) para todo el texto de la interfaz; token `--font-sans`. IBM Plex Mono con numerales tabulares solo para números dentro de gráficos, tablas y la línea de tiempo (clase `.num`); token `--font-mono`. Ambas se cargan en `index.html`.

- Cuerpo 15 px / 1,4.
- Título de tarjeta 22 px / 400.
- `h1` de página 44 px / 400 (30 px hasta 800 px de ancho).
- Cifras grandes 64–72 px / 300 con numerales tabulares y una leyenda de 13 px en `--text-muted` debajo.

## Superficies

- Fondo de página `--bg` con 24 px de relleno. Un solo marco (radio 36 px, relleno 24/28 px, degradado `--frame-0/1/2` a 160°) contiene todo.
- Tarjetas: `--surface`, radio 28 px, relleno 20 px, sin bordes y sin textura (se eliminaron los puntos y el brillo `.tx`).
- Píldoras y controles segmentados: radio 999 px.

## Controles

- Objetivos de 44 px. Botones neutros sobre `--raised`; el primario (reproducir) redondo de 44 px sobre `--ctrl` con glifo de acento.
- Píldoras de capa: un `<label>` que envuelve la casilla oculta visualmente (`layer-toggle-<id>`); activa = relleno `--ctrl`. Pueden estar varias activas. Logo: píldora con contorno de 1 px `--text` ("Clima Ideas"); botón de tema redondo de 44 px.
- Controles segmentados (pestañas de vistas, regiones, ENSO, métricas, hindcast, vista IVT, fondo del mapa; clases `.seg`, `.conv-seg`, `.fc-tabs`, `.enso-tabs`, `.enso-metrics`): pista en píldora (radio 999 px) sobre `--raised`, opción activa `--ctrl` con texto `--on-ctrl`, segmentos de al menos 44 px. Solo tokens: dentro de la tarjeta inversa (`data-tone="inverse"`) `--raised`, `--ctrl` y `--on-ctrl` se reasignan y el control se lee igual en ambos temas. Sin radios de 4 / 7 / 8 / 10 px en controles.
- Avisos y llamadas (`.fc-notices`, `.debris-warn`): radio 20 px, relleno `--raised`, sin bordes duros. Subtarjetas y pozos de gráficos: radio 20 px (`--radius-sub`). Filas elegibles: radio 20 px. Selectores y botones neutros: píldora.
- Tablas: líneas finas `--border` entre filas (sin cajas), encabezado de 12 px en `--text-muted`, números en mono (`.num`) solo en celdas numéricas. Títulos de sección dentro de los paneles: Outfit 400.
- Tiradores: la línea de acento aparece solo con hover (en dispositivos con hover), `:focus-visible` o durante el arrastre; nunca de forma persistente (tras soltar un arrastre con el puntero se quita el foco).
- Panel expandido: la columna cubre el mapa (que queda oculto) y usa los mismos controles; se verifica en claro y oscuro.
- Fila de lista seleccionada: fondo `--raised` y un punto de 8 px en `--accent`.
- Foco visible: anillo de 2 px en `--accent` con 2 px de separación (enlaces, botones, campos y separadores).
- Las marcas de acento en el mapa y los gráficos llevan un contorno `--casing`.

## Layout

- Cabecera: píldora del logo, píldoras de capas y botón de tema. En escritorio no hay `aside` de capas; hasta 800 px las píldoras se desplazan en horizontal en una sola fila (sin cajón). El botón ENSO vive en la cabecera de la tarjeta de eventos.
- Fila principal: `h1` con el título de la capa elegida; a la derecha hasta 3 cifras grandes que el panel de la capa ya calcula (eventos mostrados, estaciones, cuencas), cada una con su leyenda y la fuente y el período de la capa en una línea apagada. Sin nada que mostrar, solo el `h1`. Nunca resultados de estudio escritos a mano.
- Cuerpo: grilla de tarjetas. La tarjeta del mapa ocupa 2 columnas (mínimo 420 px de alto); luego inspector, detalle y lista de eventos. La tarjeta de perspectiva / modelo usa `--inverse`. Hasta 800 px todo se apila en orden: cabecera, `h1`, cifras, mapa, tarjetas. Los tiradores siguen entre el mapa y la columna de tarjetas y sobre la línea de tiempo.
- El inspector muestra filas etiqueta a la izquierda y valor a la derecha; la fuente y el período se conservan. Sin evento elegido, la ayuda del mapa queda en un desplegable (`details`). La tarjeta de detalle aloja los gráficos de la estación y la tabla ENSO cuando corresponden; sin contenido no se muestra. La lista de eventos tiene filas de 48 px (punto, nombre, valor y fecha en mono) y el conteo en el título.
- Replays apilados: con la capa de ríos atmosféricos (evento elegido) y la de convección activas, cada replay es una fila propia (`.timeline-row`, controles y pista propios), nunca superpuestas. La tira crece para contenerlas (`timelineMinFor`: 184 px con el temporal, 304 px con ambos) y pasa a la forma de tarjeta de radio 28 px cuando supera 200 px.
- Línea de tiempo: una píldora `--surface` (radio 999 px) con etiqueta, pista de 6 px sobre `--raised` con progreso en `--accent`, hora en `.num` y botón de reproducir redondo de 44 px sobre `--ctrl` con glifo de acento. Anterior / siguiente: redondos de 44 px sobre `--raised`. Las marcas conservan su posición porcentual y su color.
- Gráficos: barras y puntos en `--text`, el destacado en `--accent` con `--casing`, fondos en `--chart-surface`; números mono solo dentro de los gráficos. Contraste de tinta verificado en `tokens.test.ts`; los escenarios de sensibilidad usan `--water`.
- Con la capa de convección activa a 1440x900 la columna no se desplaza: tarjetas compactas, solo el gráfico IDF en la tarjeta de detalle y las notas largas (leyenda, extrapolación †, sesgo, celda, sensibilidad, replay) en un `<details>` "Ver notas" cerrado; fuente, período, licencia, la etiqueta "IDF solo con IMERG, sin corrección de sesgo" y la marca † de T 100 siempre visibles. El replay del temporal vive en la línea de tiempo y sigue el mismo cursor que los cuadros de lluvia del mapa.
- Leyendas del mapa en un solo contenedor abajo a la izquierda (`.map-legends`, pila vertical sin superposición), con el selector de vista como control segmentado; los relojes (`.map-clocks`) arriba a la derecha durante una reproducción.

## Mapa base y cámara

- Mapa base ráster con datos de OpenStreetMap dibujado por deck.gl (`TileLayer` + `BitmapLayer`) como capa inferior: CARTO `light_all` en claro y `dark_all` en oscuro (`https://{a-d}.basemaps.cartocdn.com/{style}/{z}/{x}/{y}@2x.png`). Atribución siempre visible en la tarjeta del mapa: "© OpenStreetMap contributors © CARTO". Los términos de CARTO para este uso están sin verificar. Las capas de referencia y de datos van encima.
- Control segmentado abajo a la derecha del mapa: "Relieve", "Mapa", "Ambos" (por defecto "Ambos", relieve con opacidad reducida, 0,55 de partida). Se guarda en `localStorage` (`map-background`); un valor inválido vuelve al defecto.
- Cámara limitada al área cubierta (caja ERA5, 34–43 °S, 74–66 °O, ver `docs/architecture.md`, "Área del visor"): el zoom mínimo es aquel en que la caja cubre la tarjeta, el centro se acota para que a inclinación 0 ningún borde de la caja entre en la tarjeta, zoom máximo 12. El lienzo llena la tarjeta en todo tamaño y bajo él el color de la tarjeta es el del mapa base, nunca el de la página.

## Tiradores de arrastre

- Hay tiradores para el ancho de la columna de tarjetas y el alto de la línea de tiempo, ubicados en los huecos entre regiones.
- Arrastrar por debajo del mínimo del panel lo colapsa a 0: el panel queda oculto (`hidden`, fuera del orden de tabulación) y el mapa ocupa el espacio. El tirador permanece en el borde para poder arrastrarlo de vuelta.
- Teclado: las flechas redimensionan (16 px), Inicio colapsa, Fin maximiza, Enter o doble clic restablece el tamaño por defecto. `aria-valuemin` es 0 y `aria-valuenow` es 0 cuando está colapsado. El mapa conserva al menos 320 × 200 px.
- Tamaños y estado colapsado se guardan en `localStorage` (`panel-sizes`); las claves inválidas o ausentes vuelven al defecto.

## Pantallas angostas

En pantallas de hasta 800 px las píldoras de capas se desplazan en una fila (sin cajón). Se apilan cabecera, `h1`, cifras, mapa, tarjetas y línea de tiempo y la página se desplaza; no hay tiradores.

## Rampa IVT (secuencial)

Tokens `--ivt-0..5` por tema (tokens.css / tokens.ts), 6 paradas parejas sobre 0–1200 kg m⁻¹ s⁻¹ (satura en 1200, "≥1200").
Alfa por celda según el IVT (`ivtAlpha`): 0 hasta 150 kg m⁻¹ s⁻¹ (`IVT_ALPHA_LOW`), sube con smoothstep hasta 0,95 en 400 (`IVT_ALPHA_HIGH`); donde no hay río la capa es transparente y se ve el relieve. La leyenda lo indica ("Bajo ~150: transparente"). Dos vistas, elegibles con un control segmentado en la leyenda (solo con la capa de ríos atmosféricos activa; `data-testid` `ivt-view-drape` / `ivt-view-isolines`):

- **Color sobre relieve** (por defecto): con el relieve activo, el IVT del cuadro se interpola bilinealmente sobre cada punto del relieve y lo tiñe: color = mezcla(gris neutro, rampa IVT) con peso `ivtAlpha / 0,95` (0 bajo 150, 1 desde 400), multiplicada por el gris del sombreado (`0,35 + 0,75·sombra`, máx. 1); el relieve sigue legible bajo el río y, sin río, queda gris sombreado. Sin relieve, el raster de celdas translúcido de siempre.
- **Isolíneas**: el relieve conserva su rampa pizarra y el IVT se dibuja como curvas de nivel en 250, 500, 750 y 1000 kg m⁻¹ s⁻¹, coloreadas con la rampa en cada nivel, de 1,5 / 2 / 2,5 / 3 px (más grueso = más intenso) y con un halo del color de fondo para legibilidad; la leyenda lista los cuatro niveles.

En ambas vistas las celdas ERA5 siguen siendo seleccionables (hover/clic) aunque no se vean. El raster y el relieve cubren todo el recorte ERA5 (ver `docs/architecture.md`, "Área del visor"). Claro: pálido a violeta profundo. Oscuro: azul tenue a amarillo claro.

| Token | Claro | Oscuro |
|---|---|---|
| `--ivt-0` | `#DCE6BE` | `#22384A` |
| `--ivt-1` | `#8CCBB0` | `#2B5F80` |
| `--ivt-2` | `#3FA3B8` | `#1E9A9C` |
| `--ivt-3` | `#2B6FB0` | `#6BCB6C` |
| `--ivt-4` | `#38399A` | `#E3E24A` |
| `--ivt-5` | `#5A1A72` | `#F8F5B4` |

## Panel de crecidas

Gráficos SVG propios, solo con tokens: curva GEV y serie diaria en `--text`, banda IC 95 % y máximos anuales en `--text-muted` (banda translúcida), las 5 mayores crecidas en `--accent` con borde `--casing`. Los puntos y estaciones del mapa son `--ctrl`; el seleccionado va en `--accent` con contorno `--casing`; las reguladas se dibujan huecas con contorno.

## Capa de convección (F3.5)

Panel en la tarjeta de detalle: curvas IDF (eje x logarítmico de duración, eje y logarítmico; una curva continua por período de retorno, Gumbel a trazos, banda IC 90 % del T elegido, escenarios de sensibilidad ÷ 0,92 y ÷ 0,67 en puntos, T = 100 marcado "†" y atenuado como extrapolación) y replay del temporal de abril de 2014 con el acumulado de IMERG contra el total de la estación (punto en `--accent` con `--casing`). El mapa pinta la lluvia semihoraria con la rampa azul monocromática `--rain-0..4` (umbrales 0, 1, 3, 8 y ≥20 mm/h, parejos en la leyenda; transparente bajo 0,1 mm/h): sin colores de advertencia. Pie con fuente, período, el aviso de sesgo y "No es un sistema de alerta oficial".

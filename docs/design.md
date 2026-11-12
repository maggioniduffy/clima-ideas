# Diseño

## Referencia

Mockup del usuario: https://claude.ai/artifact/LPUfQ1KS8iZA9rkipwoi3Y (`project/Mockup.dc.html`). El objetivo son los artboards de "Mockup con datos de ejemplo"; los wireframes no son el objetivo. Tema claro con acento azul, tema oscuro con acento amarillo. El relieve usa su rampa monocromática pizarra (tokens `--relief-0..3`, con sombreado), no una hipsométrica verde/marrón. Inspiración: `inspiration/README.md`.

## Reglas de UI

- Sin etiquetas, badges ni descripciones secundarias: jerarquía, color y forma explican.
- Nunca blanco ni negro puros: claros con tono crema, oscuros con tono azul.
- Mismo layout en ambos temas: mismas regiones y mismas cajas; solo cambian los tokens.
- Acento reservado para lo que importa (evento, anomalía, selección).
- Solo lo que funciona: no se muestran navegación de secciones, filtros ni botones sin acción.

## Tokens

Los valores viven en `web/src/theme/tokens.css` y `tokens.ts`; `tokens.test.ts` verifica que coincidan. El acento es por tema.

| Token | Claro (crema) | Oscuro (azul) | Uso |
|---|---|---|---|
| `--bg` | `#F1EEE6` | `#16212A` | Fondo de página |
| `--surface` | `#F9F7F2` | `#1F2D37` | Tarjetas y barra superior |
| `--raised` | `#EFECE4` | `#2A3A46` | Botones neutros, fila seleccionada |
| `--border` | `#DDD8CD` | `#3E505B` | Trazos finos dentro de gráficos |
| `--text` | `#2A343B` | `#ECE7DC` | Texto |
| `--text-muted` | `#5F6468` | `#A3AEB4` | Texto secundario |
| `--ctrl` | `#3E505B` | `#4D6372` | Control primario (reproducir) |
| `--on-ctrl` | `#F5F2EA` | `#ECE7DC` | Texto sobre `--ctrl` |
| `--accent` | `#8EB8E5` | `#FDDA0D` | Eventos, anomalías, selección, foco |
| `--water` | `#3A6E8F` | `#7FA9C6` | Ríos en el mapa |
| `--casing` | `#2A343B` | `#16212A` | Contorno de las marcas de acento |
| `--relief-0` | `#A7AEAF` | `#4E5F6A` | Relieve, bajo |
| `--relief-1` | `#77848A` | `#7D8D96` | Relieve, medio |
| `--relief-2` | `#4A5A64` | `#B3BEC4` | Relieve, alto |
| `--relief-3` | `#2A343B` | `#ECE7DC` | Relieve, cumbres |

Comunes a ambos temas: `--main #3E505B` (primario, texto fuerte en claro), `--secondary #A4AF69` (banda "normal", climatología), espaciado `--space-1..6` (4, 8, 12, 16, 24, 32 px), radios `--radius-sm/md/lg` (4, 8, 12 px) y la rampa IVT (más abajo). Contraste mínimo WCAG AA.

## Tipografía

IBM Plex Sans para el cuerpo y los títulos; IBM Plex Mono con numerales tabulares solo para números, fechas y unidades (clase `.num`). Cuerpo 14 px / 1,4. Títulos de tarjeta 14 px / 600; título de página y del inspector 16 px / 600. Se cargan desde Google Fonts en `index.html` (sin CSP que lo bloquee); tokens `--font-sans` y `--font-mono`.

## Superficies

- Sin bordes entre regiones. Fondo de página `--bg`, con 8 px de relleno y 8 px entre regiones.
- Cada panel es una tarjeta `--surface` con radio 8 px y relleno 16 px.
- Textura (clase `.tx`, también en la barra superior): en claro, puntos `radial-gradient(rgba(42,52,59,0.09) 0.9px, transparent 1.3px)` a 5 × 5 px más un brillo diagonal `linear-gradient(135deg, rgba(255,255,255,0.45) 0%, transparent 55%)`; en oscuro, ninguno de los dos. Los dos valores salen de las variables `--tex` y `--shine` de cada tema.

## Controles

- Objetivos de 44 px, radio 8 px, sin borde. Botones neutros sobre `--raised`; el primario (reproducir) sobre `--ctrl` con texto `--on-ctrl`.
- Casillas de 18 px con `accent-color: var(--ctrl)`; filas de 40 px. Fila de lista seleccionada: fondo `--raised` y un punto de 8 px en `--accent`.
- Foco visible: anillo de 2 px en `--accent` con 2 px de separación (enlaces, botones, campos y separadores).
- Las marcas de acento en el mapa y los gráficos llevan un contorno `--casing`.

## Layout

- Barra superior (mínimo 56 px, `--surface`, con textura): marca del logo, "Clima Ideas", `h1` de la página y botón de tema de 44 px.
- Cuerpo: panel de capas (`aside`) de 240 px por defecto; columna principal con la tarjeta del mapa (flex 1, mínimo 400 px de alto), una fila de tarjetas debajo (inspector `1 1 300px`, gráficos de detalle `1,6 1 420px`, lista de eventos `1 1 300px`) y la tira de línea de tiempo.
- El inspector muestra filas etiqueta a la izquierda y valor mono a la derecha (mínimo 28 px); la fuente y el período se conservan. La tarjeta de detalle aloja los gráficos de la estación y la tabla ENSO cuando corresponden; sin contenido no se muestra. La lista de eventos tiene filas de 48 px (punto, nombre, valor y fecha en mono) y el conteo en el título.
- Línea de tiempo: botones anterior / reproducir / siguiente de 44 px; pista con línea base de 2 px, marcas en acento y cabezal de 5 px en acento; hora de la reproducción en mono.
- Mapa en una tarjeta redondeada; leyenda abajo a la izquierda sin borde; mientras hay una reproducción activa, un reloj arriba a la derecha muestra su fecha y hora.

## Tiradores de arrastre

- Hay tiradores para el ancho de capas, el alto de la fila de tarjetas y el alto de la línea de tiempo, ubicados en los huecos de 8 px entre regiones.
- Arrastrar por debajo del mínimo del panel lo colapsa a 0: el panel queda oculto (`hidden`, fuera del orden de tabulación) y el mapa ocupa el espacio. El tirador permanece en el borde para poder arrastrarlo de vuelta.
- Teclado: las flechas redimensionan (16 px), Inicio colapsa, Fin maximiza, Enter o doble clic restablece el tamaño por defecto. `aria-valuemin` es 0 y `aria-valuenow` es 0 cuando está colapsado. El mapa conserva al menos 320 × 200 px.
- Tamaños y estado colapsado se guardan en `localStorage` (`panel-sizes`); las claves inválidas o ausentes vuelven al defecto.

## Pantallas angostas

En pantallas de hasta 800 px el panel de capas es un cajón. Las tarjetas se apilan debajo del mapa y la página se desplaza; no hay tiradores.

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

Gráficos SVG propios, solo con tokens: curva GEV y serie diaria en `--text`, banda IC 95 % y máximos anuales en `--text-muted` (banda translúcida), las 5 mayores crecidas en `--accent` con borde `--text`. Los puntos del mapa son `--main` (acento si está seleccionada) y las estaciones reguladas se dibujan huecas con contorno.

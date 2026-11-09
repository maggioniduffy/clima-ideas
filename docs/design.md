# Diseño (provisorio)

Referencia visual: el mockup del usuario, https://claude.ai/artifact/LPUfQ1KS8iZA9rkipwoi3Y. El relieve usa su rampa monocromática pizarra (tokens `--relief-0..3`, con sombreado), no una hipsométrica verde/marrón.

Base inicial; el usuario lo va a profundizar. Inspiración: `inspiration/README.md`.

## Reglas de UI

- Sin etiquetas, badges ni descripciones secundarias: jerarquía, color y forma explican.
- Nunca blanco ni negro puros: claros con tono crema, oscuros con tono azul.
- Mismo layout en ambos temas: barra superior, panel de capas, lienzo, inspector, línea de tiempo.
- Acento reservado para lo que importa (evento, anomalía, selección).

## Colores de marca

| Token | Valor | Uso |
|---|---|---|
| `--main` | `#3E505B` | Primario, controles, texto fuerte en claro |
| `--accent` | `#8EB8E5` | Eventos, anomalías, selección |
| `--secondary` | `#A4AF69` | Banda "normal", climatología |

## Neutros

| Token | Claro (crema) | Oscuro (azul) |
|---|---|---|
| `--bg` | `#F5F2EA` | `#16212A` |
| `--surface` | `#ECE8DE` | `#1F2D37` |
| `--raised` | `#E2DDD1` | `#2A3A46` |
| `--border` | `#D3CDBF` | `#3E505B` |
| `--text` | `#2A343B` | `#ECE7DC` |
| `--text-muted` | `#6E7377` | `#A3AEB4` |

Valores neutros a ajustar; contraste mínimo WCAG AA.

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

## Tipografía

Monoespaciada para datos e instrumentos; una sans para títulos. IBM Plex Mono (400, 500) para datos y IBM Plex Sans (400, 500, 600) para títulos, cargadas desde Google Fonts en `index.html` (sin CSP que lo bloquee); tokens `--font-mono` y `--font-sans`.

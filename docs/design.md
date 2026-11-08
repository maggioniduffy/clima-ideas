# Diseño (provisorio)

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
Raster casi opaco (alfa 0,85–0,95). Claro: pálido a violeta profundo. Oscuro: azul tenue a amarillo claro.

| Token | Claro | Oscuro |
|---|---|---|
| `--ivt-0` | `#DCE6BE` | `#22384A` |
| `--ivt-1` | `#8CCBB0` | `#2B5F80` |
| `--ivt-2` | `#3FA3B8` | `#1E9A9C` |
| `--ivt-3` | `#2B6FB0` | `#6BCB6C` |
| `--ivt-4` | `#38399A` | `#E3E24A` |
| `--ivt-5` | `#5A1A72` | `#F8F5B4` |

## Tipografía

Monoespaciada para datos e instrumentos; una sans para títulos. Elección pendiente.

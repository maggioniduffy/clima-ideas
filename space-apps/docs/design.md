# Diseño

Fuente: canvas "Clima Ideas — Main page wireframe" (https://claude.ai/artifact/LPUfQ1KS8iZA9rkipwoi3Y),
artboard Mockup. Reglas generales: [../../docs/design.md](../../docs/design.md) (sin badges ni descripciones
secundarias, nunca blanco ni negro puros, acento solo para lo que importa).

## Layout

Barra superior: título de la app, "NASA Space Apps 2026 · Desafío CONAE", autor "Faustino Maggioni Duffy",
selector de tema e idioma. Panel izquierdo: área, período, sensor. Centro: mapa. Inspector derecho: cifras del
área. Franja inferior: calendario año×mes y anomalías. Mismo layout en ambos temas; a ancho de teléfono los
paneles se apilan.

Pestañas Mapa / Dashboard en el centro. Dashboard: grilla de gráficos del área (serie mensual, totales por año,
estacionalidad, anomalía, día/noche y FRP, ENSO y sequía); pasar el cursor por un mes lo resalta en todos los
gráficos y en el calendario. Paleta de series y rampas: las de "Rampas", con datos en IBM Plex Mono.

## Tokens

| Token | Claro | Oscuro |
|---|---|---|
| `--bg` | `#F1EEE6` | `#16212A` |
| `--surface` | `#F9F7F2` | `#1F2D37` |
| `--raised` | `#EFECE4` | `#2A3A46` |
| `--border` | `#DDD8CD` | `#3E505B` |
| `--text` | `#2A343B` | `#ECE7DC` |
| `--muted` | `#5F6468` | `#A3AEB4` |
| `--ctrl` | `#3E505B` | `#4D6372` |
| `--onctrl` | `#F5F2EA` | `#ECE7DC` |
| `--accent` | `#8EB8E5` | `#FDDA0D` |
| `--secondary` | `#A4AF69` | `#A4AF69` |

Claro: textura de puntos `radial-gradient(rgba(42,52,59,.09) .9px, transparent 1.3px)` a 5 px y brillo
diagonal sutil en superficies. Oscuro: sin textura.

## Tipografía y forma

IBM Plex Sans 400/500/600 para texto (14 px base); IBM Plex Mono 400/500 con cifras tabulares para datos.
Controles de 44 px de alto, radios 8–10 px, foco visible: contorno de 2 px con `--accent`.

## Rampas

- Calendario (conteo): secuencial de un solo tono que crece en luminosidad, validada para daltonismo
  (a definir en SA0.4).
- Anomalía: divergente azul (menos que la mediana) / naranja (más), centro neutro `--raised`.
- `--secondary` marca la banda "normal" (p25–p75).

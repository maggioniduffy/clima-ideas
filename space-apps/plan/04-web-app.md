# Fase 4 — App web

Estado: pendiente · Depende de: 0, 3 · Refs: `docs/design.md`

## Objetivo

La app del desafío con el layout del canvas de diseño: elegir área y período, ver el historial de fuego y
descargarlo.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| SA4.1 | Área: dibujar en el mapa, ingresar lat/lon + radio, "Usar mi ubicación" (pide permiso; radio por defecto ~230 km); vista inicial: provincia de Córdoba | Sonnet | e2e de cada modo; sin permiso queda Córdoba |
| SA4.2 | Mapa deck.gl con focos (crudos o celdas según zoom) y el área seleccionada | Sonnet | e2e: cambia al mover el área |
| SA4.3 | Calendario: heatmap año×mes con rampa secuencial apta para daltonismo; tooltip con conteo y fuente | Sonnet | e2e + vitest de escala de color |
| SA4.4 | Anomalías: año×mes vs. mediana con rampa divergente azul/naranja; mes actual resaltado con el acento | Sonnet | e2e |
| SA4.5 | Inspector: cifras de SA3.4, selector de serie: reportada por sensor, MODIS-equivalente o VIIRS-equivalente (2000–2011 marcado "estimado"), versión de calibración, fuente y período | Sonnet | e2e |
| SA4.6 | Descargas CSV (focos y calendario) | Sonnet | e2e: el archivo baja con las columnas de SA3.6 |
| SA4.8 | Vista "Dashboard" del área seleccionada (pestaña junto al mapa), gráficos enlazados entre sí y con el calendario: serie mensual armonizada con banda de incertidumbre y series por sensor; totales por año; estacionalidad (mediana y p10–p90 por mes con el año en curso encima); anomalía mensual; reparto día/noche y distribución de FRP; fase ENSO y sequía (si existe la fase 5). Cada gráfico con fuente y período, exportable en PNG y CSV | Sonnet | e2e: elegir área → gráficos con los mismos totales que SA3.4; vitest de escalas |
| SA4.7 | Accesibilidad: contraste AA, teclado, foco visible, ancho de teléfono | Sonnet | Playwright + axe sin errores |

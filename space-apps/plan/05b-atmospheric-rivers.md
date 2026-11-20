# Fase 5b — Ríos atmosféricos y fuego (opcional)

Estado: pendiente · Depende de: 4 · Refs: `../plan/01-atmospheric-rivers.md`, `../plan/00-foundations.md` (F0.9)

Solo si la app (fase 4) ya funciona.

## Pregunta

¿La llegada (o la falta) de ríos atmosféricos marca el fin o la severidad de la temporada de fuego? Aplica sobre
todo a cordillera y Patagonia; en Sudamérica subtropical, a la corriente en chorro de capas bajas (sin verificar
cuánto pesa en Córdoba).

## Relación ríos atmosféricos–fuego (hipótesis a medir)

Aportada por el usuario el 2026-10-28; fuente citada: Stanford Doerr School of Sustainability (sin URL, sin
verificar).

1. **Alivio inmediato:** la lluvia intensa apaga o frena incendios activos y humedece suelos secos en sequía.
   Medible: caída de focos en los días posteriores a un río atmosférico.
2. **Riesgo diferido:** un período muy húmedo hace crecer pasto y arbustos que después se secan y dejan
   combustible fino; sube el peligro en la temporada seca siguiente. Medible: días con río atmosférico (o
   lluvia) en la temporada húmeda vs. focos en la seca siguiente, con rezago de meses.
3. **Aluviones después del fuego:** lluvia torrencial sobre un área quemada reciente, que no absorbe agua ni
   sujeta el suelo, dispara aluviones, deslaves e inundaciones repentinas. Conecta con la fase 4 de
   clima-ideas ([../../plan/04-debris-flows.md](../../plan/04-debris-flows.md)): áreas quemadas como factor de
   susceptibilidad.

## Tareas

| ID | Tarea | Agente | Hecho cuando |
|---|---|---|---|
| SA5b.1 | Si la fase 1 de clima-ideas tiene eventos, importarlos; si no, IVT de ERA5 para la región | opencode | Eventos o IVT diario en Zarr |
| SA5b.2 | Detector baseline: IVT ≥ 250 kg m⁻¹ s⁻¹ con persistencia mínima | Sonnet | Unit sobre campo sintético |
| SA5b.3 | TECA BARD solo si clima-ideas F0.9 lo dejó andando; comparar con SA5b.2 | opencode | Tabla de coincidencia, o "no usado" |
| SA5b.4 | Días con río atmosférico por mes: fila extra del calendario y variable para la fase 6 | Sonnet | e2e |
| SA5b.5 | Medir las relaciones 1 y 2: focos antes y después de cada evento (composición de eventos) y correlación con rezago entre temporada húmeda y seca | opencode analiza, Sonnet codifica | `reports/05b/SA5b.5.md` con IC, o "sin señal" |
| SA5b.6 | Relación 3: lista de eventos de lluvia intensa sobre áreas quemadas en los 12 meses previos (áreas quemadas MCD64A1/VNP64A1) como insumo para clima-ideas fase 4 | opencode | Tabla de casos con fecha, área y fuente |

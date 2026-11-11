# Plan de desarrollo: Neuquén, lluvias extremas y aluviones

Índice de fases. Fuente de alcance: `NEUQUEN_PLAN.md` (el resto de las ideas del repo queda fuera), más ENSO como
eje de análisis en las fases 1, 2, 3 y 5 y la fase 6 de predicción experimental (pedido del usuario, 2026-10-27).
Producto: pipeline Python por etapa que publica capas en un visor web.

## Fases

| # | Fase | Archivo | Depende de | Estado |
|---|---|---|---|---|
| 0 | Bases: monorepo, visor, API, contrato de capas, acceso a datos | [plan/00-foundations.md](plan/00-foundations.md) | — | hecha, salvo F0.11 (publicar en línea) |
| 1 | Ríos atmosféricos en la cordillera | [plan/01-atmospheric-rivers.md](plan/01-atmospheric-rivers.md) | 0 | hecha (F1.7 solo 2023; 3 estudios de F1.5 sin verificar) |
| 2 | Crecidas de ríos + LSTM de caudal | [plan/02-floods.md](plan/02-floods.md) | 1, caudal SNIH | en curso (F2.1, F2.2, F2.4 hechas; siguen F2.3 y F2.7) |
| 3 | Convección e IDF en la Confluencia | [plan/03-convection.md](plan/03-convection.md) | 0 | pendiente (lluvia horaria de estación sin verificar: F3.0) |
| 4 | Aluviones: cuencas chicas (núcleo); HEC-RAS y emulador (extensión) | [plan/04-debris-flows.md](plan/04-debris-flows.md) | núcleo: 2, 3 · extensión: F4.4a | pendiente |
| 5 | Predicción retrospectiva | [plan/05-hindcast.md](plan/05-hindcast.md) | 1 (ríos atmosféricos) · 3 (convección) | pendiente |
| 6 | Predicción a futuro (experimental) | [plan/06-forecast.md](plan/06-forecast.md) | 0, 2, 5 · registro F6.1 + F6.4: solo 0 | pendiente |

## Rumbo (revisión del 2026-11-11)

El rumbo se mantiene: solo Neuquén, de la atmósfera al suelo, cada modelo de ML junto a un baseline, nada sin
verificar dado por cierto, sin alertas. Hilo principal hasta ahora: el 58 % de los días de lluvia ≥ p99 coincide
con un río atmosférico y la crecida de junio de 2023 en Paso de Indios tiene un período de retorno de ≈ 134 años.
Seis ajustes, que salen de los resultados y de `docs/research/data-access.md`:

1. **ENSO pesa más que su evidencia.** En F1.8 ninguna de 16 pruebas sostiene p BH < 0,05 y el resultado cambia
   con el polígono. Queda una comprobación barata por fase; el modelo estacional (F6.2) depende de que F2.7
   encuentre señal en el caudal y usa primero nieve, humedad de suelo y caudal reciente, con ENSO como una entrada más.
2. **La segunda mitad de la fase 4 es la apuesta más débil.** Pide HEC-RAS 2D en Linux (sin probar), cientos de
   simulaciones y un evento con mancha conocida (ninguno verificado). El núcleo es F4.1–F4.3; F4.4–F4.6 son
   extensión y se abren solo si F4.4a da bien.
3. **La fase 4 no está en el camino a la predicción.** La 6 depende de la 2 y la 5; la mitad de ríos atmosféricos
   de la 5 depende solo de la 1. La fase 4 no bloquea nada.
4. **La verificación prospectiva necesita tiempo de calendario.** Los ríos atmosféricos llegan sobre todo en
   invierno y la convección en primavera y verano. F6.1 y F6.4 se adelantan: el registro arranca solo con
   baselines para juntar predicciones puntuadas antes del invierno de 2027.
5. **La pregunta de la fase 3 puede no tener respuesta como está escrita.** Medir cuánto subestiman los productos
   globales exige lluvia horaria de estación (SMN sin verificar, AIC restringido). F3.0 lo comprueba antes de
   empezar; si falla, la pregunta se reformula.
6. **Nada está publicado.** La web estática con capas en R2 se decidió el 2026-11-05 y no estaba en el plan: es
   F0.11. Desde ahí, una fase cierra cuando su capa está en línea.

Regla para tareas de análisis: la cifra principal lleva una comprobación de sensibilidad (otro umbral, polígono
o período) antes de darse por hecha.

## Orden

```
2 (F2.3, F2.7, F2.5) ──> 5 mitad ríos atmosféricos ──> 6 modelos
F0.11 publicar        3 (tras F3.0) ──> 5 mitad convección
F6.1 + F6.4 registro con baselines: en cuanto haya F0.11
4 núcleo: en paralelo, cuando haya lluvias de diseño de 2 y 3
```

## Próximo

1. F2.3: etiquetar las crecidas mayores con el catálogo de ríos atmosféricos y lluvia sobre nieve (cierra el hilo principal).
2. F2.7: ENSO en el caudal; decide si F6.2 se hace.
3. F0.11: publicar las capas de las fases 1 y 2.
4. F3.0: comprobar lluvia horaria en NOAA ISD 877150.
5. F2.5: LSTM de caudal contra GR4J y persistencia (la tarea más larga; habilita F2.6 y la fase 6).

## Advisor (hasta 2026-11-17)

Opus consulta a Fable (subagente `advisor`) cuando se traba al resolver o decidir. Cuándo y cómo: `CLAUDE.md`;
plantilla: `docs/agents.md`. El advisor juzga contra la sección "Rumbo".

## Referencias

| Archivo | Cuándo leerlo |
|---|---|
| [docs/agents.md](docs/agents.md) | Al delegar o consultar al advisor: plantillas de prompt |
| [docs/architecture.md](docs/architecture.md) | Al tocar estructura, contrato de capas, API o tests |
| [docs/design.md](docs/design.md) | Al tocar UI: tokens, temas, reglas de interfaz |
| [docs/research/data-access.md](docs/research/data-access.md) | Antes de empezar una fase: estado y licencia de sus datos |

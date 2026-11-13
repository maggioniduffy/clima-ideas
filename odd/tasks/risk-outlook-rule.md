# Regla de alerta → perspectiva de riesgo

Objetivo: reemplazar "No es un sistema de alerta…" por una regla que permita una perspectiva de riesgo para usuarios
técnicos tras una compuerta de evidencia. Rama: `fm/alert-rule-plan-d909ef`. Solo documentos; sin código.

## Specs

- S1. Decisión del usuario (2026-11-12): "Change it" — "Open the door to warning-like outputs; that needs its own
  plan (validation, responsibility, communication)".
- S2. Respuestas del usuario (2026-11-12): audiencia "Technical users"; salida "Risk outlook" (probabilidad frente a
  la climatología, con incertidumbre e historial, sin niveles de alerta); canal oficial "Defer and link"; entrega
  "Viewer only".
- S3. Texto nuevo de la regla en `CLAUDE.md` y en el Rumbo de `plan.md`.
- S4. Compuerta de evidencia y descenso automático en `plan/06-forecast.md`; tareas de hindcast en `plan/05-hindcast.md`.
- S5. Avisos obligatorios y lista de lo que queda fuera de alcance.

## Tareas

| ID | S | Ruta | Estado |
|---|---|---|---|
| T1 | S1–S5 | inline | hecha: `CLAUDE.md`, `plan.md`, `plan/05-hindcast.md`, `plan/06-forecast.md` |

## Log

- L1 (2026-11-12, pedido de la sesión de origen): planificar el cambio de la regla "No es un sistema de alerta" en
  `CLAUDE.md`, `plan.md` y `plan/06-forecast.md`; preguntar audiencia, tipo de salida, canal oficial y responsabilidad;
  proponer la regla, las tareas que cambian, la evidencia mínima, los avisos y lo que queda fuera.
- L2 (2026-11-12): respuestas del usuario, ver S2.
- L3 (2026-11-12, advisor): pregunta: ¿qué compuerta de evidencia? Recomendación: el hindcast es la prueba y la
  temporada prospectiva comprueba que no lo contradiga; contar eventos independientes; promover anticipaciones
  contiguas; mostrar el modelo más simple que supere a los baselines; ningún tope fijo de falsas alarmas y ninguna
  probabilidad destacada; caudal solo como probabilidad de superar un umbral, con prueba dejando afuera cada crecida
  grande; descenso automático, también al cambiar la versión. Decisión: se adopta tal cual; los umbrales (20 y 10
  eventos) los decide el usuario.
- L4 (2026-11-13): el usuario aprueba la propuesta ("Approve") y los umbrales "20 / 10" (eventos independientes en
  el test del hindcast / en el registro prospectivo). Cambios: regla nueva en `CLAUDE.md`; Rumbo 7 en `plan.md`;
  F5.8 en la fase 5; F6.1 (latencia de caudal), F6.6 (dos estados y avisos), F6.7, F6.8, compuerta, avisos
  obligatorios y fuera de alcance en la fase 6.
- L5 (2026-11-13, revisión de CodeRabbit en el PR 38): se precisa la compuerta: F6.7 solo para caudal alto en
  `plan.md`; estado por región; eventos independientes agrupados también entre regiones para los mínimos de 20 y
  10; el baseline simple puede ser el modelo mostrado; el descenso de una anticipación arrastra a las más largas.
  Decide Opus; no cambia las decisiones del usuario.

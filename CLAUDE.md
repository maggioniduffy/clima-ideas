# clima-ideas

Desarrollo guiado por [plan.md](plan.md) (índice de fases, alcance: Neuquén).

## Flujo

- Empezar toda tarea en modo plan, salvo que se indique lo contrario.
- Cargar solo `plan.md` y la fase activa; las referencias de `docs/` solo cuando la tarea lo pide.
- Al cerrar una tarea: marcarla en su fase y actualizar el estado en `plan.md`.

## Orquestación

| Rol | Agente | Hace |
|---|---|---|
| Plan, orquestación, revisión | Opus (sesión principal) | Divide tareas, delega, revisa diffs e informes |
| Implementar y corregir código | Sonnet (subagente) | Código, unit tests (pytest, vitest) y e2e (Playwright) |
| Investigación, datos grandes, análisis | opencode | Búsquedas web, descargas, consultas pesadas, análisis con informe |
| Consejo en bloqueos y decisiones difíciles | Fable (subagente `advisor`) | Solo lectura: recomienda, no implementa. Hasta el 2026-11-17 |
| Tests simples pero largos | opencode | Suites lentas (`pytest -m slow`), entrenamientos, corridas de pipeline |

En este proyecto opencode reemplaza a Codex para trabajo masivo. Plantillas de prompt: `docs/agents.md`.

Ciclo por tarea:

1. Opus pasa la tarea por referencia: `plan/NN-*.md`, ID de tarea, archivos permitidos, criterio de "hecho".
2. El agente trabaja y devuelve resultado + comandos corridos con su salida resumida.
3. Opus revisa: `git status`, `git diff --stat`, corre un test enfocado, lee solo el resumen del informe.
4. Si falla dos veces o es demasiado difícil, Opus consulta al advisor. Si sigue abierto, o es una decisión de
   producto o de alcance, lo eleva al usuario.

## Advisor (vigente hasta el 2026-11-17)

Fable, como subagente `advisor` (`.claude/agents/advisor.md`). Plantilla de consulta: `docs/agents.md`.

- Consultar cuando: la misma tarea falló dos veces; hay que elegir un método o un diseño y ninguna opción gana
  claro (estadística, particiones de validación, métricas de ML, ítems "Decide Opus"); un resultado contradice
  a uno anterior o a la literatura; un resultado cambiaría la conclusión de una fase o el "Rumbo" de `plan.md`.
- No consultar por: revisión de rutina, lectura masiva (opencode), decisiones de producto o alcance (usuario).
- Límite: una consulta por problema y una repregunta. Opus decide y responde por la decisión.
- Registro: una línea en el `## Avance` de la fase o en el log de `odd/tasks/`: fecha, pregunta, recomendación
  y decisión tomada.
- Vencimiento: después del 2026-11-17 se borran esta sección, la fila de la tabla, el paso 4 vuelve a su texto
  anterior y se borra `.claude/agents/advisor.md`.

## Reglas

- Código, nombres de archivo y commits en inglés. UI en español primero.
- Nada inventado: lo no verificado se marca "sin verificar"; todo dato modelado muestra fuente y período.
- ML solo con un baseline simple al lado.
- No es un sistema de alerta oficial. Desde el 2026-11-12 el proyecto puede mostrar una perspectiva de riesgo a
  1–10 días para usuarios técnicos, solo en el visor, si pasa la compuerta de evidencia de `plan/06-forecast.md`.
  Nunca niveles, colores, umbrales destacados ni consejos de acción. Siempre con incertidumbre, baseline, historial
  de aciertos y enlace a los avisos oficiales (SMN, AIC, Defensa Civil). Lo que no pasa la compuerta se muestra
  como "Experimental"; el resto del proyecto es retrospectivo.

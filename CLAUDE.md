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
| Tests simples pero largos | opencode | Suites lentas (`pytest -m slow`), entrenamientos, corridas de pipeline |

En este proyecto opencode reemplaza a Codex para trabajo masivo. Plantillas de prompt: `docs/agents.md`.

Ciclo por tarea:

1. Opus pasa la tarea por referencia: `plan/NN-*.md`, ID de tarea, archivos permitidos, criterio de "hecho".
2. El agente trabaja y devuelve resultado + comandos corridos con su salida resumida.
3. Opus revisa: `git status`, `git diff --stat`, corre un test enfocado, lee solo el resumen del informe.
4. Si falla dos veces o es demasiado difícil, Opus lo resuelve o lo eleva al usuario.

## Reglas

- Código, nombres de archivo y commits en inglés. UI en español primero.
- Nada inventado: lo no verificado se marca "sin verificar"; todo dato modelado muestra fuente y período.
- ML solo con un baseline simple al lado.
- No es un sistema de alerta oficial. Desde el 2026-11-12 el proyecto puede mostrar una perspectiva de riesgo a
  1–10 días para usuarios técnicos, solo en el visor, si pasa la compuerta de evidencia de `plan/06-forecast.md`.
  Nunca niveles, colores, umbrales destacados ni consejos de acción. Siempre con incertidumbre, baseline, historial
  de aciertos y enlace a los avisos oficiales (SMN, AIC, Defensa Civil). Lo que no pasa la compuerta se muestra
  como "Experimental"; el resto del proyecto es retrospectivo.

# Plantillas de delegación

## Sonnet

```
Task: plan/NN-x.md, <ID>. Read only that file and the refs it names.
Allowed edit surfaces: <paths>
Done when: <criterio de la tarea>
Tests first when a deterministic test applies.
Return: changed files, commands run with results.
```

## opencode

```bash
opencode run --title "<ID>" "<prompt>"
```

Prompt: objetivo, rutas en alcance, restricciones (no editar código fuera de alcance, no secretos),
formato de respuesta, y archivo de salida en `reports/<fase>/<ID>.md`.

## Advisor (Fable, hasta el 2026-11-17)

Subagente `advisor`. Cuándo consultar: `CLAUDE.md`.

```
Question: <la decisión o la falla, en una oración>
Tried: <qué se hizo y qué pasó, con comandos y resultados>
Options: <A / B / C como las ve Opus>
Evidence: <rutas, informes en reports/, ID de tarea en plan/NN-x.md>
Constraints: <reglas del proyecto que aplican>
Return: recommendation, why, risks, what to verify, confidence.
```

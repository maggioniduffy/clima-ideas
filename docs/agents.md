# Plantillas de delegación

## Sonnet

```
Task: plan/NN-x.md, <ID>. Read only that file and the refs it names.
Allowed edit surfaces: <paths>
Done when: <criterio de la tarea>
Tests first when a deterministic test applies.
Return: changed files, commands run with results.
```

## Haiku

Subagente con `model: haiku` (reemplaza a opencode desde el 2026-11-22): investigación, descargas, corridas largas.

```
Task: plan/NN-x.md, <ID>. Objective: <objetivo>.
In scope: <rutas>. Do not edit code outside scope; never print or store secrets.
Unverified facts are marked "sin verificar" with the URL tried.
Write the report to reports/<fase>/<ID>.md.
Return: report summary (≤ 15 lines) + commands run with results.
```

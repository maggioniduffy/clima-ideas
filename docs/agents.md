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

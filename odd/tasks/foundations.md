# Feature: foundations (phase 0)

Objective: skeleton where every later phase only adds layers. Branch: `fm/neuquen-rains-app-3437b1`.
Delivery: ask-on-risk. Runners: pytest (backend), vitest + Playwright (web).

## Specs

Quoted verbatim from `plan/00-foundations.md` (column "Hecho cuando").

- S1 (F0.1) Monorepo: `backend/` (uv, Python 3.12) y `web/` (pnpm, Vite, React, TS); `Makefile`; `data/` en `.gitignore` — "`make dev` levanta API y visor"
- S2 (F0.2) CI: ruff, pytest, eslint, tsc, vitest, Playwright — "CI verde en un PR"
- S3 (F0.3) Tokens de diseño, tema claro/oscuro, `web/src/i18n/es.ts` — "Cambio de tema sin recarga; ningún string fuera de `es.ts`"
- S4 (F0.4) Shell del visor: barra superior, panel de capas, inspector, línea de tiempo, lienzo deck.gl — "Layout fijo en ambos temas"
- S5 (F0.5) Relieve como nube de puntos: GLO-30 de Neuquén, submuestreado a binario Float32 — "Relieve visible, < 15 MB"
- S6 (F0.6) FastAPI: `/health`, `/layers`, `/layers/{id}`; validación del manifiesto con pydantic — "Unit tests de manifiesto válido e inválido"
- S7 (F0.7) Capa de prueba de punta a punta (manifiesto + datos falsos) — "e2e: la capa aparece, se activa e inspecciona"
- S8 (F0.8) Investigación de acceso a datos → `docs/research/data-access.md` — "Cada ítem con estado, URL y licencia, o \"sin verificar\""
- S9 (F0.9) Instalar TECA y correr BARD sobre un año de ERA5 — "Log y máscara de salida, o el error exacto"
- S10 (F0.10) Índice ENSO compartido: ONI mensual (NOAA CPC) 1950–hoy y fase por mes (Niño ≥ +0,5, Niña ≤ −0,5, Neutro) — "Parquet + unit: umbrales y fase sobre una serie sintética"

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T1 F0.8 | S8 | opencode (background) | done | docs/research/data-access.md, 24 items; websearch failed so many "sin verificar" (BDHI, SMN hourly, CAMELS-CL, GEFS, SINARAME, debris inventory, SCS-CN) |
| T2 F0.9 | S9 | opencode (background) | running | install only; ERA5 run blocked on CDS credentials |
| T3 F0.1 | S1 | builder (Sonnet) | done | make dev: /health ok, :5173 200, proxy ok; pytest 1, vitest 1, lint+tsc clean |
| T4 F0.6 | S6 | builder | pending | |
| T5 F0.10 | S10 | builder | pending | |
| T6 F0.3 | S3 | builder | pending | |
| T7 F0.4 | S4 | builder | pending | |
| T8 F0.7 | S7 | builder | pending | |
| T9 F0.5 | S5 | opencode (data) + builder (layer) | pending | |
| T10 F0.2 | S2 | builder | pending | |

Route reason: user's model-roles override (Sonnet implements, Opus reviews).

## Log

- L1 (2026-11-05) User: "Let's start with the Neuquen and rains app (not NASA challenge)"
- L2 (2026-11-05) Plan approved: execute all of phase 0 in this worktree. No `~/.cdsapirc` present: F0.9 ERA5 download expected to be blocked.
- L3 (2026-11-05) User: "Allow opencode run" — F0.9 relaunched, install-only scope in ~/teca-work.
- L4 (2026-11-05) F0.8 opencode exited 1 (websearch "cancelled") but wrote both files; fetch-only evidence. Gaps listed in T1; candidate for a second research pass.

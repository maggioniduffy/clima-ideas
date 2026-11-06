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
| T1 F0.8 | S8 | opencode + 2 Haiku passes | done | gaps per phase listed in data-access.md; remaining "sin verificar" need formal requests (SMN radar, AIC, SNIH IDs) | docs/research/data-access.md, 24 items; websearch failed so many "sin verificar" (BDHI, SMN hourly, CAMELS-CL, GEFS, SINARAME, debris inventory, SCS-CN) |
| T2 F0.9 | S9 | builder → GitHub Actions (manual) | workflow written, run pending merge to main | local build abandoned (coincided with freezes); CDSAPI_KEY secret set by user |
| T3 F0.1 | S1 | builder (Sonnet) | done | make dev: /health ok, :5173 200, proxy ok; pytest 1, vitest 1, lint+tsc clean |
| T4 F0.6 | S6 | builder | done | RED: import errors; GREEN: 33 passed, ruff clean |
| T5 F0.10 | S10 | builder | done | RED: ModuleNotFound; GREEN: full suite 36 passed; real parquet 921 rows 1950-01..2026-09 |
| T6 F0.3 | S3 | builder | done | RED: missing modules; GREEN: 11 tests, lint rule fired on deliberate violation |
| T7 F0.4 | S4 | builder | done | RED: Shell unresolved; GREEN: vitest 13, e2e shell 1 passed (fixed boxes across themes, no reload) |
| T8 F0.7 | S7 | builder | done | no RED recorded (tests written with code); GREEN: pytest api 41, vitest 24, e2e 2 passed; /data guard = manifest allowlist |
| T9 F0.5 | S5 | builder (data, then layer) | done | relief visible (screenshot, 1/8 subset under SwiftShader); vitest 30, e2e 3; follow-ups: contrast, license overflow; | 24 tiles 947 MB; relief.bin 9.67 MB, 805800 pts, 130–4641 m; period = 2021 release (assumption) |
| T10 F0.2 | S2 | builder | done (local), PR #6 open | yaml ok; all job commands pass locally (pytest 54, vitest 24, e2e 2); green PR run pending push |

Route reason: user's model-roles override (Sonnet implements, Opus reviews).

## Log

- L1 (2026-11-05) User: "Let's start with the Neuquen and rains app (not NASA challenge)"
- L2 (2026-11-05) Plan approved: execute all of phase 0 in this worktree. No `~/.cdsapirc` present: F0.9 ERA5 download expected to be blocked.
- L3 (2026-11-05) User: "Allow opencode run" — F0.9 relaunched, install-only scope in ~/teca-work.
- L4 (2026-11-05) F0.8 opencode exited 1 (websearch "cancelled") but wrote both files; fetch-only evidence. Gaps listed in T1; candidate for a second research pass.
- L5 (2026-11-05) User: "If you need to complete f0.8 work with a haiku, do it" — Haiku explorer launched on the "sin verificar" rows; T1 reopened for the merge.
- L6 (2026-11-05) User: "Stop F0.9" (disk at 99%). Stopped; partial env left in ~/miniconda3/envs/teca.
- L7 (2026-11-05) Stopping the client did not stop the opencode service session (it kept installing torch); killed service + pip. Disk freed by user: 69 GB free.
- L8 (2026-11-05) User: "What? There should be more data for that / Or it will be done on other phases? Same for the other points open / Continue with F0" and "But continue with F0.9 too". Second Haiku pass launched with concrete leads (SINARAME RMA, SNIH, SMN 87715, inventories, DesInventar); F0.9 resumed.
- L9 (2026-11-05) Session crashed mid-commit of F0.3 (22:13): branch ref + 20 loose objects empty. Moved empties to ~/git-empty-objects-backup-20261105, reset ref to 1f93e9b, fsck clean, re-committed. User: "resume, max ram 6gb".
- L10 (2026-11-05) Second crash (RAM). Git intact. User: "Resume work, cap the sum of work to 6gb or run only 2 at a time (1 if it's too heavy)". Runtime slice `clima.slice` MemoryMax=6G shared; heavy jobs run one at a time: F0.5 first, then F0.9 TECA build (at 32%).
- L11 (2026-11-05) Freeze investigation: abrupt boots since at least Nov 2, before this work; no OOM/oomd/kernel errors; likely NVIDIA 580/X11 display stack (unproven). User: "Resume, safe mode": shared slice, one heavy job, Playwright on SwiftShader.
- L12 (2026-11-05) Another freeze 22:58. User applied nvme_core.default_ps_max_latency_us=0 (confirmed 0). User: "resume work now, not agressive though": slice 4G + CPUQuota 300%, nice 10, one job at a time.
- L13 (2026-11-05) User: "can we run this TECA phase on the cloud or github actions?" → workflow_dispatch workflow. User set repo secret CDSAPI_KEY via gh (value never seen). Local TECA build stopped.
- L14 (2026-11-05) Freeze at 23:19 with both kernel params active and only a light builder (web reads, no compile). Resumed.
- L15 (2026-11-05) Branch pushed; PR https://github.com/maggioniduffy/clima-ideas/pull/6 opened (ready). Auto-fix on.
- L16 (2026-11-05) User: "merged done". PR #6 merged 02:27Z. Launched teca.yml run 42150504752 (year 2023, run_bard=true, 6-hourly).
- L17 (2026-11-05) Run 42150504752 failed: CMake 4 rejects cmake_minimum_required < 3.5 in TECA 6.0.0; configure error hidden by tee (no pipefail). Fix on fm/teca-cmake-pin: pin cmake>=3.20,<4, pipefail in Configure.

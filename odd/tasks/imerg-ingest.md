# Feature: imerg-ingest (phase 3, F3.1)

Objective: regional IMERG V07 Final half-hourly precipitation for the Confluencia and meseta as Zarr, 2000–present.
Branch: `fm/adoring-lewin-093d89`. Delivery: ask-on-risk. Runner: pytest (backend).

## Specs

Quoted verbatim from `plan/03-convection.md` (column "Hecho cuando"), `CLAUDE.md` and the session's next steps.

- S1 (F3.1) "Ingesta IMERG recortado a la Confluencia y meseta" — "Zarr 2000–hoy".
- S2 (rule, CLAUDE.md) "Nada inventado: lo no verificado se marca \"sin verificar\"; todo dato modelado muestra fuente y período."
- S3 (assumption, Opus, from `reports/03/F3.1-access.md`) Source is `GPM_3IMERGHH` V07 Final (CMR `C2723754847-GES_DISC`)
  via NASA Harmony, bbox west −70.0, south −40.0, east −67.0, north −37.5, variable `Grid/precipitation`. Months not
  yet published as Final are left out and listed; no Late tail in this feature.
- S4 (next steps) "run the 32-way speed test, write the F3.1 plan in `odd/tasks/`, then build `backend/src/clima_nqn/io/imerg.py`."

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T1 parallel download benchmark | S3, S4 | inline (Opus, scratch script) | dropped (L2) | |
| T2 `io/imerg.py` + CLI + tests | S1, S2, S3 | delegated (codex exec), fixed inline by Opus (L3) | done | 7 tests, suite 386 passed, ruff clean |
| T3 full 2000–present run | S1 | GitHub Actions `imerg.yml` (L4) | pending | |

## Log

- L1 (2026-11-16) User (pasted summary of the previous session): "Next steps: run the 32-way speed test, write the
  F3.1 plan in `odd/tasks/`, then build `backend/src/clima_nqn/io/imerg.py`." Plan approved the same day; the full
  run (T3) stays a separate decision.
- L2 (2026-11-16) User: "donde need benchmark, only do it asap". Benchmark stopped before it finished, no result
  recorded; the full run (T3) starts as soon as T2 passes its checks.
- L3 (2026-11-16) Codex wrote the module, CLI and tests but could not run them (no user bus for `systemd-run` in
  its sandbox), and modelled Harmony with an invented API (dict request, string status). Opus fixed: real
  `harmony.Request` via `build_request`, status read from the job dict, naive UTC timestamps, no dask in `combine`.
- L4 (2026-11-16) User: "run it on github actions then"; secrets `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` loaded by
  the user ("listo"). Workflow `.github/workflows/imerg.yml`: one job per year (max 10 at once), last month = today
  minus 4 months, combine job joins whatever succeeded and lists `missing_months`.
- L5 (2026-11-16) Real smoke (2014-04-07, 48 granules): variable lives in group `Grid`, time in a "julian" calendar;
  fixture changed to match (RED 2 failed), fix GREEN 7 passed. Neuquén Aero cell: 92.015 mm/day, 15.41 mm/h max, same
  as `reports/03/F3.1-access.md`. Harmony returns 31 lon columns (−70.05..−67.05) by 25 lat.

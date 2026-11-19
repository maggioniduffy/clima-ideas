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
- L6 (2026-11-16) User: "Entonces que guarde progreso si se corta el run. No era literal el 'asap', me refería a que uses
  la máxima velocidad posible de la computadora". Added `--parallel` months (4), 20 year jobs at once, restore of
  finished months from earlier runs, fetch step stopped at 320 min so the upload runs. First Actions runs failed NASA
  login: the `EARTHDATA_USERNAME` secret arrived with 7 characters instead of 10; user reset it with `gh secret set`.
  One-month test (2014-01) green end to end; fetch step 3 min 16 s. Full run 43949673338 launched.
- L7 (2026-11-16) Run 43949673338: year jobs died with exit 135 (SIGBUS) inside `merge_granules`, e.g. 2008 at
  granule 20080229. Cause: `--parallel` merges several months at once and the HDF5 in the netCDF4 wheels is not
  thread-safe; reproduced locally (8 threads reading granules: exit 135 and 139 without a lock, clean with it). Fix:
  a process-wide lock around granule open+load (downloads stay parallel) and `CFDatetimeCoder` in place of the
  deprecated `use_cftime`, which filled the log with ~30k warning lines. Not a corrupt file or a credentials issue.
- L8 (2026-11-17) Run 43976784052 (with the HDF5 lock): no crash, and the restore worked (e.g. 2004 restored 01-04 from
  43949673338 and skipped them). But no year finished a single new month in 5 h 20 min; every fetch step hit the
  320-min limit with no output after the skips. In the cancelled run, years had 2-4 months done by 2 h 45 min. Likely
  cause (sin verificar): about 76 Harmony jobs from the cancelled run kept running on NASA's side, and the new run
  added about 80 more under the same account, so the queue stalled. The lock is unlikely: the parallel CLI test and an
  8-thread stress run both finish with it. `fetch_month` polls without logging, so the run cannot tell which. Harmony
  is not reachable from the Claude container (proxy 403).
- L9 (2026-11-17) User: "Run again in small chunks ... save progress so the next run starts from the latest advance".
  imerg.yml is now one job per month (artifact imerg-month-YYYY-MM). plan cancels leftover Harmony jobs, counts done
  months (month artifacts plus the newest legacy imerg-neuquen-YYYY per year), and picks the next 48 missing months
  (6 at a time). Each fetch logs Harmony status every minute, cancels its job at 40 min, and never leaves one running.
  continue dispatches the next run while months remain and the run saved at least one; combine runs when none remain.
- L10 (2026-11-17) Run #10 (commit af4d9b2): all 12 month jobs failed with `harmony job ... not done by deadline`. The
  run log shows each Harmony job advancing about 1 %/min and reaching about 46 % at the 40-min deadline, where
  `fetch_month` cancelled it, and the next `plan` cancelled the rest; so NASA-side progress was thrown away every run
  and no month could finish (`continue` correctly refused to chain with 0 artifacts). Total NASA-side time per month:
  sin verificar (extrapolating the rate gives roughly 90 min). Fix: jobs carry a per-month label
  `clima-nqn-imerg-YYYY-MM` and outlive the GitHub job; `fetch_month` reuses the newest active or successful job for
  the month (`find_job`) and on deadline raises without cancelling; `cancel-running --keep-months` spares the batch's
  jobs and cancels older duplicates; `continue` chains after a run with no month finished, up to 2 in a row (`stalls`
  input). Harmony is not reachable from the Claude container, so the real check is a dispatch with `max_months=6`.
- L11 (2026-11-18) Runs 44191824663 / 44199224540: the second run cancelled the first run's jobs anyway. harmony-py
  adds label `harmony-py` to every job it submits, and the `cancel-running --label harmony-py` call had no
  `--keep-months`. Even resubmitted from zero, 3 of 6 months (2004-08/09/10) finished inside 40 min (1488 granules
  each) and the other 3 reached ~92 %. Fix: pass `--keep-months "$BATCH"` to the harmony-py cancel too. Run 13 had
  already planned on the old commit.
- L12 (2026-11-18) Run 44212694407 (commit 5a2016d): plan cancelled 0 jobs; fetch logged `reusing harmony job`
  (2004-11 resumed at 87 %, reached 98 % at the deadline). Months done so far: 2004-05..10 and 2005-05. Throughput
  is about 1-3 months per ~50-min run with 6 jobs; the last ~10 % of a job is slow (sin verificar por qué).
- L13 (2026-11-18) Chain stopped after run 44235849670: runs 15 (2004-11, 2004-12), then 16-18 finished no month, so
  the stall rule (3 idle runs) ended it. Jobs were still advancing (2005-06 69→92 %, 2005-11 43→67 % in 40 min); a
  month now takes ~3 h on Harmony. Stall limit raised to 6 idle runs (~5 h); relaunched with stalls=0.
  Done: 2004-05..12, 2005-05.
- L14 (2026-11-18) User: "Metele mas paralelismo y que siga". Relaunched with jobs=12, max_months=12. Runs 20, 22,
  23 each finished all 12 months in ~20 min (plan ~7 min + fetch ~10 min): 36 months in 1 h, vs ~1-3 per 50-min run
  before. Whether the gain is the parallelism or a lighter Harmony queue at this hour is sin verificar.
- L15 (2026-11-19) Chain finished at run 44455941236 (runs 24-37 at 12 parallel, ~30-40 min each). combine uploaded
  artifact `imerg-neuquen` (37 MB zip, 90 days): 2000-06-01..2025-09-30, time 444144 × lat 25 × lon 31, float32,
  `missing_months` empty. The 10 months 2025-10..2026-07 failed in seconds with Harmony "No matching granules": not yet
  published as Final, so the default last_month (today minus 4) is too recent (real Final latency sin verificar).
  F3.1 closed. Open: the plan's harmony-py cancel takes ~10 min per run (pages the whole job history); the Zarr lives
  only as an Actions artifact (expires 2027-02-16).

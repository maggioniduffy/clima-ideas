# Feature: streamflow LSTM (phase 2, F2.5–F2.6)

Objective: daily streamflow LSTM (pretrained on CAMELS-CL, fine-tuned on Neuquén) against GR4J and persistence, and a flood card with retrospective forecasts.
Branch: `fm/phase-2-5-2-6-0a8ee1`. Delivery: ask-on-risk. Runners: pytest (backend), vitest + Playwright (web).

## Specs

Quoted verbatim from `plan/02-floods.md` and `CLAUDE.md`; design decisions from the approved plan (2026-11-12) are marked as assumptions.

- S1 (F2.5) "ML (alta): LSTM de caudal diario; preentreno en CAMELS-CL, ajuste en Neuquén; baselines GR4J y persistencia" — "NSE/KGE en test vs. baselines".
- S2 (F2.6) "Ficha de crecida: pronóstico LSTM de próximos días con incertidumbre vs. observado" — "e2e sobre un evento pasado".
- S3 (rules, CLAUDE.md) "Nada inventado: lo no verificado se marca \"sin verificar\"; todo dato modelado muestra fuente y período." "ML solo con un baseline simple al lado." "No es un sistema de alerta."
- S4 (rule, plan.md) "la cifra principal lleva una comprobación de sensibilidad (otro umbral, polígono o período) antes de darse por hecha."
- S5 (assumption, forcing) Daily means over `io/snow.UPSTREAM_BOXES`, hydrological years 1980–2025: `tp` and `deg0l` from the phase-1 artifacts of run 42437929137; 2 m temperature (mean/min/max) from a new `era5.yml` run with a `variables` input whose default keeps the current four; PET by Oudin.
- S6 (assumption, pretraining) CAMELS-CL via Caravan (CC-BY 4.0); fallback PANGAEA; last resort no pretraining, reported as such.
- S7 (assumption, models) LSTM modes `sim` (forcing only; vs GR4J+CemaNeige by NSE/KGE) and `forecast` (plus observed flow up to the issue day, leads 1–7; vs persistence and GR4J per lead). GR4J+CemaNeige in numpy, calibrated on KGE.
- S8 (assumption, splits) Hydrological years: train 1980–2006, validation 2007–2013, test 2014–2025; nothing tuned on test. Sensitivity: no pretraining; alternate split with test 1980–1991.
- S9 (assumption, uncertainty) 5-seed ensemble plus validation residual quantiles, 90 % band; labeled "pronóstico retrospectivo con meteorología observada (ERA5), no pronóstico operativo".
- S10 (assumption, dependency) torch CPU-only in a dependency group `ml`; API and CI do not install it.

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T0 Caravan feasibility + phase-1 cube download | S5, S6 | explorer + Opus (`gh run download`) | done (CAMELS-CL from PANGAEA; cube download running) | L2 |
| T1a `era5 fetch --variables` + workflow run for t2m | S5, S3 | builder (code), Opus dispatches | done | L3, L5 |
| T1 basin forcing (`io/forcing.py`) | S5, S3 | builder, parallel with T2 | done | 3173f18; L5 |
| T2 GR4J+CemaNeige, persistence, NSE/KGE | S7 | builder, parallel with T1 | done | 3173f18; L6 |
| T3 LSTM (torch) | S1, S6–S10 | builder; verifier (Risk 5) | done | L7, L9 |
| T4 runs + `reports/02/F2.5.md` | S1, S3, S4, S8 | opencode runs, Opus reviews | pending | |
| T5 F2.6 flood card | S2, S3, S9 | builder (backend+web unit) | pending | |
| T6 close + PR | — | Opus | pending | |

## Log

- L1 (2026-11-12) User: "Continue with phase 2.5 and 2.6". On the plan: "Can't ypu fetch it?" (the phase-1 ERA5 cube) — yes: 46 artifacts of run 42437929137 still available (≈ 100 MB each, expire 2027-02-06). Plan approved.
- L2 (2026-11-12) T0 explorer report. Caravan v1.6 (Zenodo 15529786, CC BY 4.0) includes CAMELS-CL (`camelscl`, 314 basins), but it ships only as the full `Caravan-nc.tar.gz` (24.8 GB) with no per-subset download. Zenodo answers 403 to `curl` from this machine, and a browser user agent was not used (the classifier denied it as bot-check circumvention). Decision (Opus), per S6: use the fallback, CAMELS-CL from PANGAEA (DOI 10.1594/PANGAEA.894885, CC-BY-4.0, Alvarez-Garreton et al. 2018), about 0.2 GB. Its forcing is CR2MET (P, Tmin/Tmax/Tmean) with Hargreaves PET, which does not match the Neuquén ERA5 forcing, and the report must say so. Caravan stays an option if the user downloads the archive in a browser. Files go to `data/raw/camels-cl/zip/`. PANGAEA does not state units for P and T: check them on the data (mm/d, °C expected).
- L3 (2026-11-12) T1a: `era5 fetch --variables` and `era5.yml` inputs `variables`/`name` (defaults unchanged, pinned by test); 6 new tests, test_era5 19 passed; ARCO store checked live: `2m_temperature` present, units K. Commit on the branch, pushed; run 43326516635 dispatched (`variables=2m_temperature`, `name=t2m`, 1980–2025). CAMELS-CL zips on disk (9 files, ≈ 180 MB): wide TSV, one row per date and one column per gauge; CR2MET from 1979; attributes file transposed.
- L4 (2026-11-12) Phase-1 cube on disk: 46 artifacts of run 42437929137 (4.4 GB) moved to `data/raw/era5/neuquen/<year>.zarr` in the main checkout; `era5.is_complete` passes for all 46 (1980–2025, all months and hours).
- L5 (2026-11-12) T1/T2 committed (3173f18): suite 303 passed, ruff clean. t2m run 43326516635: 47 jobs green; 46 stores in `data/raw/era5/t2m/`. `flow forcing` on real data (32 s first run): 50 406 rows, 1980-01-01..2025-12-31, only 3 NaN precip (2025-12-31, no 2026 store). Annual means 12004 / 12010 / 12012: P 836 / 756 / 721 mm, Oudin PET 601 / 635 / 564 mm, Tmean 6.7 / 7.6 / 5.8 °C, deg0l 1531 / 1688 / 1356 m. Plausible; boxes still approximate.
- L6 (2026-11-12) Early T4 baseline (scratch script, not committed; default split; GR4J+CemaNeige calibrated on hydro years 1980–2006 with 1 year warm-up, best of 3 DE seeds, ≈ 100 s per station; flow in mm/d with SNIH area, 12012 with box area). Test 2014–2025 NSE / KGE: GR4J 12004 0.486 / 0.456, 12010 0.517 / 0.675, 12012 0.195 / 0.593. Validation: 12004 0.788 / 0.773, 12010 0.557 / 0.607, 12012 −2.737 / −0.442 (GR4J fails on the small, flashy Curi Leuvú). Persistence test NSE at leads 1 / 3 / 7: 12004 0.642 / −0.262 / −0.531; 12010 0.848 / 0.402 / 0.053; 12012 0.782 / 0.447 / 0.072. The low 12004 persistence is real, not a data error: 2023-06-24 → 06-25 the flow jumps 2 508 → 11 009 m³/s, and squared-error metrics on the test period are dominated by that event. Decision (Opus): the F2.5 report adds, as sensitivity, test metrics without hydrological year 2023 and on log flow (both declared now, before seeing LSTM results). Calibrated x1 ≈ 1700–1750 mm for all three and CTG ≈ 1 for 12004 and 12010: near the upper edge of plausible, noted, not changed.
- L7 (2026-11-12) T3 result (builder): `io/camels_cl.py`, `stages/flood/lstm.py`, `stages/flood/streamflow_eval.py`, CLI `flow lstm-train` and `flow streamflow-eval`, torch in group `ml` (CPU index; lock +136/−1, only additions). Tests: default env 343 passed, 4 skipped; `--group ml` 45 passed; ruff clean. Choices: NSE* loss on the normalized target, one normalization pooled over CAMELS and Neuquén train rows, sim scores the last 30 steps of 365-day windows, forecast windows t−364..t+7 with flow and mask channels; train/val windows never contain a test date. CAMELS-CL: 516 gauges, 380 with ≥ 10 years used for pretraining. Smoke (1 seed, 1 epoch): ≈ 20 s per epoch of 20 000 windows, peak RSS 3.0 GB; full training estimated at ≈ 14 min per seed. Added after L6: `excl_2023` and `nse_log` per cell. Found: in `data/flow/stations.json` the SNIH area of 12012 Los Maitenes (2131 km²) equals that of 12013 Chos Malal; possibly a copy in F2.1 metadata, sin verificar. 12012 metrics in mm depend on that area; the report must flag it. CAMELS cache kept in `data/raw/camels-cl/camels_cl.parquet` (227 MB). Independent verifier for the dependency launched (Risk 5).
- L8 (2026-11-12) T4 run plan, fixed before any LSTM result (Opus). Default hyperparameters of `flow lstm-train` (hidden 64, 365-day windows, 10 pretrain + fine-tune epochs with early stopping on validation, 20 000 windows per epoch); nothing chosen on test. Runs, sequential (≈ 3 GB RAM each): `sim-default` (sim, default split, pretrain, 5 seeds) and `fc-default` (forecast, default split, pretrain, 5 seeds) are the main results; sensitivity S4/S8: `sim-nopretrain` (no pretraining, 3 seeds) and `sim-alt` (alternate split, test 1980–1991, pretrain, 3 seeds). 3 seeds for sensitivity to fit the CPU budget. Each followed by `flow streamflow-eval`. Run by Opus as one background script (not opencode: plain sequential commands).
- L9 (2026-11-12) Independent verifier (Risk 5), all PASS: lock only adds (torch 2.15.0+cpu and 7 PyPI deps; no existing version or source changed); every workflow's `uv sync --locked` installs no torch (`import torch` fails); torch tests skip cleanly without `ml`; `--group ml` installs only the +cpu wheel (no nvidia/triton); no Dockerfile or deploy path installs it; the PyTorch index is explicit and used only by torch. Not verified: real CI run, macOS wheel. Note: plain `uv sync` removes torch; use `uv sync --group ml`.

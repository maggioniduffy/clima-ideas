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
| T0 Caravan feasibility + phase-1 cube download | S5, S6 | explorer + Opus (`gh run download`) | in progress | |
| T1a `era5 fetch --variables` + workflow run for t2m | S5, S3 | builder (code), Opus dispatches | pending | |
| T1 basin forcing (`io/forcing.py`) | S5, S3 | builder, parallel with T2 | pending | |
| T2 GR4J+CemaNeige, persistence, NSE/KGE | S7 | builder, parallel with T1 | pending | |
| T3 LSTM (torch) | S1, S6–S10 | builder; verifier (Risk 5) | pending | |
| T4 runs + `reports/02/F2.5.md` | S1, S3, S4, S8 | opencode runs, Opus reviews | pending | |
| T5 F2.6 flood card | S2, S3, S9 | builder (backend+web unit) | pending | |
| T6 close + PR | — | Opus | pending | |

## Log

- L1 (2026-11-12) User: "Continue with phase 2.5 and 2.6". On the plan: "Can't ypu fetch it?" (the phase-1 ERA5 cube) — yes: 46 artifacts of run 42437929137 still available (≈ 100 MB each, expire 2027-02-06). Plan approved.
- L2 (2026-11-12) T0 explorer report. Caravan v1.6 (Zenodo 15529786, CC BY 4.0) includes CAMELS-CL (`camelscl`, 314 basins), but it ships only as the full `Caravan-nc.tar.gz` (24.8 GB) with no per-subset download. Zenodo answers 403 to `curl` from this machine, and a browser user agent was not used (the classifier denied it as bot-check circumvention). Decision (Opus), per S6: use the fallback, CAMELS-CL from PANGAEA (DOI 10.1594/PANGAEA.894885, CC-BY-4.0, Alvarez-Garreton et al. 2018), about 0.2 GB. Its forcing is CR2MET (P, Tmin/Tmax/Tmean) with Hargreaves PET, which does not match the Neuquén ERA5 forcing, and the report must say so. Caravan stays an option if the user downloads the archive in a browser. Files go to `data/raw/camels-cl/zip/`. PANGAEA does not state units for P and T: check them on the data (mm/d, °C expected).

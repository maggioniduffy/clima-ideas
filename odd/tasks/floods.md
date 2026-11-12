# Feature: floods (phase 2, F2.1–F2.2)

Objective: daily streamflow from SNIH for stations upstream of the dams, then annual maxima and GEV return periods.
Branch: `fm/phase-2-start-97ca58`. Delivery: ask-on-risk. Runner: pytest (backend).

## Specs

Quoted verbatim from `plan/02-floods.md` (column "Hecho cuando") and the user's answers.

- S1 (source) Caudales de "los ríos Neuquén, Limay, Agrio y Curi Leuvú (BDHI, AIC). Estación aguas arriba de las presas." — source chosen by the user: "SNIH, browser accept"
- S2 (F2.1) "Ingesta de caudales diarios con control de huecos" — "Parquet por estación + reporte de huecos"
- S3 (F2.2) "Máximos anuales y GEV con intervalo de confianza (`pyextremes`)" — "Unit: recupera parámetros de una GEV sintética"
- S4 (rule, CLAUDE.md) "Nada inventado: lo no verificado se marca \"sin verificar\"; todo dato modelado muestra fuente y período."
- S5 (assumption) Hydrological year and complete-year rule (≥ 330 valid days) fixed after seeing the data in T0.
- S6 (F2.4) "Capa: estaciones + panel de período de retorno y serie" — "e2e: elegir estación, ver curva y crecidas". User: "Sí, hacer F2.4" and "levanta localhost para ver esta fase visualmente".
- S7 (F2.7) "Máximos anuales y caudal estacional por fase ENSO; GEV con ONI como covariable vs. estacionaria. Su resultado decide si se hace el modelo estacional F6.2" — "Comparación por verosimilitud + unit con GEV sintética dependiente de covariable".
  Fixed before looking at results (assumption, Opus): primary covariate = mean ONI of AMJJAS of the hydrological year, location `mu = mu0 + mu1·ONI`; one alternate (ONI of the peak's season) as sensitivity; all p-values BH-adjusted together. Stations 12004 and 12010; 12012 reported and flagged unreliable.
- S8 (F2.3) "Etiquetar crecidas mayores con el catálogo F1.3 y lluvia sobre nieve" — "Tabla de crecidas con causa probable + sensibilidad a la ventana de días entre río atmosférico y pico".
  Approved scope (plan of 2026-11-12): floods = annual maxima of complete years inside the catalog period; AR label = catalog event active in `[peak − w, peak]`, primary `w = 3`, sensitivity `w = 0..7`; chance-coincidence baseline by permutation; rain on snow checked against downloaded snow (L9): snow water equivalent before the peak and its change over the window, over an approximate upstream area per station; rule fixed before the run (assumption, Opus): "lluvia sobre nieve probable" = AR in the window + snow-covered fraction of the area ≥ 0.2 (cells with ≥ 10 mm w.e.) at the window start + area-mean snow water equivalent lower at the peak than at the window start; the event's 0 °C isotherm is reported next to it, not thresholded. Other labels: "río atmosférico", "deshielo sin río atmosférico" (same snow conditions, no AR), "sin causa identificada". Source is ERA5 `snow_depth`/`snowmelt` at 0.25° from the anonymous ARCO store, not ERA5-Land (no CDS key on this machine); the report must say so, and the upstream areas are "sin verificar".

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T0 SNIH sources | S1, S4 | inline (Opus, built-in browser) | done | L2, L3 |
| T1 F2.1 | S2, S4, S5 | delegated (builder, model-roles override) | done | 16 tests green, full suite 172 passed; real fetch: 4 stations with data (L4) |
| T2 F2.2 | S3, S4, S5 | delegated (builder, model-roles override) | done | 8 tests, suite 180 passed, verifier OK on 6 items (L5) |
| T3 F2.4 | S4, S6 | delegated (builder, one unit backend+web, model-roles override) | done | backend 191 passed, web 109 passed, e2e 7 passed; real layer 436 KB (L7) |
| T4 F2.7 | S4, S5, S7 | delegated (builder, model-roles override) | done; advisor consult on the verdict open | 10 tests, suite 204 passed, ruff clean; commit 4897562 (L10) |
| T5 F2.3 | S4, S5, S8 | delegated (builder, model-roles override) | done | 27 tests, suite 231 passed, ruff clean; real run 114 floods (L13) |
| T6 F2.7 addendum | S4, S7, L12 | delegated (builder), after T5 (shared cli.py) | pending | |

## Log

- L1 (2026-11-08) User: "start with phase 2". Answers: flow data = "SNIH, browser accept"; scope = "F2.1 + F2.2 (Recommended)".
- L2 (2026-11-08) T0 findings (verified in the browser, snih.hidricosargentina.gob.ar):
  - Terms (`/Terminos.aspx`, §7): free use incl. commercial, derived works and redistribution allowed; obligations:
    keep the original meaning, cite SIPH/SNIH (and contributing network) as source, state the last-update date, keep
    source/date metadata. Accepted in the browser per the user's choice.
  - API: `POST /Filtros.aspx/LeerEstaciones` (1451 stations, metadata incl. `MesHidrologico`);
    `POST /MuestraDatos.aspx/LeerDatosHistoricos` body `{fechaDesde, fechaHasta, estacion, codigo, validados}`,
    parameter 101 = "Caudal Medio Diario" (QMD, m3/seg). Response `d.Mediciones[]` with `FechaHora` (`/Date(ms)/`,
    local midnight UTC-3), `Medicion`, `Calificador`, `Validado`. Paso de Indios 2023-04-01..2024-03-31 -> 366 rows.
  - Hydrological year: SNIH `MesHidrologico = 4` (April) for these stations -> S5 year start = April.
  - Candidate stations (Red 1, RHN), ID / name / river / area km2 / since:
    12004 Paso de Indios / Neuquén / 30843 / 1945 (upstream of Portezuelo Grande);
    12013 Chos Malal / Neuquén / sin verificar / 1975;
    12010 Bajada del Agrio / Agrio / 7300 / 1953;
    12012 Los Maitenes / Curí Leuvú / sin verificar / 1989;
    11804 Paso Limay / Limay / 26400 / 1903 (below Alicurá, regulated since 1984 -> natural only before; sin verificar);
    11803 Paso Flores / Limay / 9800 / 1941 (position vs Alicurá sin verificar).
  - Blocked: fetching full series by shell (curl) and by in-browser bulk loop were both denied by the auto-mode
    classifier. Needs a user decision on how to obtain the files.
- L3 (2026-11-08) User: "Allow fetch command". Shell curl to LeerDatosHistoricos verified (no cookie needed). T1 delegated to builder with `flow fetch` + `flow ingest`.
- L4 (2026-11-09) T1 result: data for 12004 (1945–2026-03), 12010 (1953–2026-03), 12012 (1989–2021-03), 11803 (2006–2021-03).
  12013 Chos Malal and 11804 Paso Limay return no data. Peak check: 12004 max 11 895 m3/s on 2023-06-26 (June 2023 flood).
  Decision for T2 (phase file: "usar solo estaciones aguas arriba para la GEV"): GEV on 12004, 12010, 12012;
  11803 Paso Flores excluded as regulated (record starts 2006, after Alicurá; position vs. dam sin verificar).
  Qualifier `D` on 336 rows of 12010: meaning sin verificar.
- L5 (2026-11-09) T2 result: GEV (pyextremes 2.6.1, MLE with multi-start scipy genextreme, 95 % bootstrap CI, 1000 resamples).
  12004: 80 complete years, xi = 0.336, Q100 = 10 649 m3/s (IC 5 980–20 908); 2023-06-26 peak = GEV T 133.8 years (empirical 81).
  12010: xi = 0.122, 66 years. 12012: 25 years, xi = 0.631 (>= 0.5, MLE irregular; CI flagged unreliable).
  Independent verifier (Risk item 5, new dependency): lock adds only pyextremes and its deps, no lock drift, CI width,
  shape sign and return levels recomputed OK. Open note: a bootstrap resample pinned at xi = 0.99 is not counted or logged.
  User asked (2026-11-09): "Una vez terminado todo levanta localhost para ver esta fase visualmente" — F2.4 (layer) not built yet.
- L6 (2026-11-09) User: "Sí, hacer F2.4". Same branch / PR #30. Design: `points` layer `flood-stations` built by
  `clima-nqn flow layer` from data/flow + data/flow/gev; inspector panel with SVG return-period curve (log T, GEV + IC band,
  empirical points), daily series with annual maxima, top floods list; no new chart dependency.
- L7 (2026-11-09) T3 result: `clima-nqn flow layer` -> data/processed/flood-stations (4 stations, 436 KB; 12004 detail 176 KB).
  Panel: return-period SVG (CI band only within stored T 2–100), daily series (max-per-bucket downsample), top floods.
  CodeRabbit review fixes on PR #30 committed separately (b0220c6): partial fetch keeps metadata, strict JSON, public scipy base.
  Light theme not checked visually by the builder.
- L8 (2026-11-12) User: "Resume work in detached mode so I can turn the computer off and it will continue". Asked where to run
  (data/ is git-ignored, 2.5 GB local): user chose "Stay local". Plan approved: F2.7 (T4) then F2.3 (T5) on branch
  `fm/detached-mode-resume-f4572e`, one commit per task, push + PR at the end, no merge. Data read from the main checkout's
  `data/` by absolute path. Not in this run: F2.5/F2.6, viewer changes, ERA5/ERA5-Land downloads, workflow dispatches.
- L9 (2026-11-12) User, on the rain-on-snow gap of F2.3: "Yes, download". ERA5-Land is served by CDS with a personal key; none
  exists on this machine (`~/.cdsapirc` missing) and the agent does not create or enter credentials. Decision (Opus): use ERA5
  `snow_depth` and `snowmelt` (m w.e., 0.25°) from the public ARCO-ERA5 store already used by `io/era5.py` (variables confirmed
  present), only for the flood windows. ERA5-Land (0.1°) stays in "Abierto" as a refinement that needs the user's CDS key.
- L10 (2026-11-12) T4 result (`reports/02/F2.7.md`): rule gives "señal" on one test: 12010 primary LRT chi2 9.95, BH p 0.019, mu1 = 191 m3/s
  per ONI unit; 12004 BH p 0.082; no phase test under 0.05 after BH. 12004 uses 75 years (ONI starts in 1950), stationary xi 0.316
  (0.336 with the 80 years of F2.2). Builder's choices: seasonal flow = April–September mean; phase by ±0.5 on the AMJJAS mean without
  persistence rule. The covariate is concurrent with the flood season, so this is association, not forecast skill.
- L11 (2026-11-12) Advisor consult (general read-only agent under `.claude/agents/advisor.md`; the `advisor` type was not
  registered in this session). Question: record "señal" as is, and what before it opens F6.2? Recommendation: keep the rule's
  outcome verbatim, add a reading line ("señal débil, concurrente, sostenida por una estación": 12010 is nested in 12004, the
  covariate overlaps the flood season, no phase test passes), run a declared post-hoc robustness addendum that cannot change the
  verdict, and gate F6.2 on a lagged-ONI check. F1.8 is compatible (it tested AR counts, 1980–2025), but leaves the mechanism
  unexplained: "sin verificar". Decision (Opus): adopted. Whether a single-station signal justifies F6.2 effort, and any rewording
  of "Rumbo" point 1, stay with the user.
  Pre-specification, stated honestly: the threshold "BH p < 0.05 at 12004 or 12010" was fixed in the builder handoff before the
  run, not in S7 and not in a commit; the report must say so.
- L12 (2026-11-12) T6 addendum spec, written before running it. Label in the report: "posterior al resultado, no cambia el
  veredicto". Exactly three checks, stations 12004 and 12010, no others added afterwards:
  (a) permutation p of the primary LRT (shuffle ONI across years, 10 000, fixed seed);
  (b) lagged covariate: mean ONI of JFM before the hydrological year starts (known on 1 April), LRT with chi-square and
      permutation p, plus its correlation with the April–September ONI;
  (c) trend control: mu = mu0 + mu1·ONI + mu2·year against mu = mu0 + mu2·year, and the primary model on 1953–2009 only.
  F6.2 gate, fixed now: lagged LRT at 12010 with permutation p < 0.05 and mu1 of the same sign as the primary. If it fails,
  F6.2 runs without ENSO or stays in baselines. Also report the non-stationary xi (it falls to about 0.01 at 12010) next to
  the Wald interval, as a warning on that interval.
- L13 (2026-11-12) T5 result (`reports/02/F2.3.md`): catalog 1980–2025, 433 events. Floods with an AR in [peak − 3, peak]:
  12004 30/45 (66.7 %, chance 14.8 %), 12010 31/44 (70.5 %, 15.2 %), 12012 17/25 (68 %, 16.6 %); permutation p = 0.0001 (floor of
  10 000 draws), not adjusted across windows or stations. Labels AR+snow / AR / snowmelt only / none: 12004 6/24/6/9, 12010 13/18/6/7,
  12012 3/14/1/7. 2023-06-26 at 12004: AR-2023-008, snow water equivalent rose 61 → 76 mm over the window, so "río atmosférico",
  not rain on snow. Snow: ERA5 0.25° `snow_depth` from ARCO, 114 windows, 83 KB, downloaded in about 1 minute.
  Builder's additions: floods need peak − 7 d inside the catalog; short record = fewer than 30 complete years.
  Open: upstream boxes and ERA5 snow not checked against observations; flow days are UTC−3 and the catalog is UTC.

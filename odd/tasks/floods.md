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

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T0 SNIH sources | S1, S4 | inline (Opus, built-in browser) | done | L2, L3 |
| T1 F2.1 | S2, S4, S5 | delegated (builder, model-roles override) | done | 16 tests green, full suite 172 passed; real fetch: 4 stations with data (L4) |
| T2 F2.2 | S3, S4, S5 | delegated (builder, model-roles override) | pending | |

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

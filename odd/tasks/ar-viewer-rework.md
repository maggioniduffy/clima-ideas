# AR viewer rework

Objective: make atmospheric rivers (AR) findable in the viewer and link them to caudales.
Branch: `fm/atmospheric-rivers-viz-aceb45`. Delivery strategy: `ask-on-risk` (forecast > 400 lines; chain strategy pending).
Test runners: `pytest` (backend/), `vitest` and Playwright (web/).

## Specs

- **S1** "divide them by years with toggles". Correction: "year toggle and inside them month toggle. A grid is
  too much visible load". Each year is a toggle; no year × month grid.
- **S2** "by month". Month toggles live inside each year.
- **S3** "highlight peak ones". Ranked, not categorised: sort by peak IVT (`ivt_max`), total rain
  (`tp_sum_mm`) or duration (`duration_h`), plus a "top N" switch; peak events drawn larger on the timeline.
  (Ranking instead of categories is an assumption, approved with the plan.)
- **S4** "mark the most concentrated part or cells of the river in map". Per-event footprint (maximum |IVT|
  per cell), core outlined with the highest existing isoline level reached (250/500/750/1000), peak cell
  marked from `ivt_max_lat` / `ivt_max_lon`. With no event picked (user's choice): "Count of rivers per cell"
  — for the years and months toggled on, each cell shows how many events reached IVT ≥ 250 there.
  The legend states n events, period and source (ERA5). The viewer says the IVT core is where moisture
  travels, not where most rain falls.
- **S5** "direct UI relationship between this rivers precipitations and caudales". Top floods that coincide
  with an AR get a tag that selects the event; the event view shows daily caudal at the stations around the
  event with the AR window shaded, freezing level (`deg0l_max`) next to it, regulated stations labelled.
  Wording "coincide con", never "causó". New per event × station table: flow the day before, peak flow in
  [start, end + 10 days] (window is an assumption, a named parameter), lag in days. Sort by largest response.
- **S6** "they may be useful for forecast". Plan documents only: proposed tasks in `plan/05-hindcast.md` and
  `plan/06-forecast.md`, marked "sin verificar". No forecast code, nothing forecast-related in the viewer.

General rules (CLAUDE.md): code, file names and commits in English; UI copy in Spanish in `web/src/i18n/es.ts`;
every modelled datum shows source and period; no alert levels, highlighted thresholds or action advice.

## Tasks

- [x] T1 — S1, S2, S3 — year → month toggles and ranked peaks (web only) — route: delegated (builder) — commit: 147c33c (vitest 214 passed, tsc and eslint clean; Playwright scenario written, not yet run)
- [x] T2 — S4 — footprints in the AR layer, count map, footprint, core and peak cell — route: delegated (builder) — commit: 8fec2af (backend pytest 371 passed, vitest 230 passed, tsc and eslint clean; Playwright scenario written, not run; real layer not regenerated)
- [x] T3 — S5 — AR response table, AR ids on top floods, flood → AR tag, caudal chart in the event view — route: delegated (builder, Sonnet) — commits: e8a2071 backend (`clima-nqn ar response`, `responses.json`, `ar_events` on top floods; focused pytest 45 passed, ruff clean), 1c44aae fixtures (station 1002 flood moved to 2000-07-25 inside AR-2000-002; response ratio 4.14, lag 4 d); 19bd6b0 web (caudal chart per station in the event view, "Coincide con" tags on top floods, sort by largest caudal response; vitest 250, tsc and eslint clean); 7bcc9b9 fix + e2e (AR layer drew the count map after being switched off, a T2 bug found by Playwright; favicon 404)
- [x] T4 — S6 — plan documents (V5–V8 in phase 1, proposed tasks in phases 5 and 6, `plan.md` status) — route: inline — commits: 83e891d (proposals), this commit (V5–V8 ticked, `plan.md` status)

Route evidence: user's "Model roles" rule (Opus orchestrates, Sonnet implements). Tasks run one after another:
T2 and T3 build on T1's filter state in `Shell.tsx`.

## Log

- **L1** (2026-11-13, user, verbatim): "Atmospherics rivers seem a little lost in the app, is there work
  related coming up? I feel that they can be more useful otherway 1. divide them by years with toggles 2. by
  month 3. highlight peak ones and from here I need your opinion 4. mark the most concentrated part or cells
  of the river in map 5. direct UI relationship between this rivers precipitations and caudales any use or
  integration you may consider" — "they may be useful for forecast (the app plan in remote main now allows it)"
- **L2** (2026-11-13, user, verbatim): "No, my idea was: year toggle and inside them month toggle. A grid is
  too much visible load"
- **L3** (2026-11-13): user chose scope "Full viewer rework" and default map "Count of rivers per cell".
  Branch fast-forwarded to `origin/main` (0cfc4e4) at the user's request before starting.
- **L4** (2026-11-13): session moved to the cloud. Playwright 1.64.1 expects a browser build that is not installed
  there; e2e runs with a scratchpad config pointing at the preinstalled Chromium (not committed). Pre-existing
  `ruff format` failure in `backend/src/clima_nqn/stages/ar/geo/__init__.py` (trailing blank line), left alone.
- **L5** (2026-11-13): full suites once. Backend pytest passed (exit 0); web vitest 250 passed, tsc and eslint clean;
  Playwright 17/17 on fixtures (T1 and T2 scenarios run for the first time; their layer-id expectations updated to the
  count map, core outline and peak marker). Browser check on fixtures: flood tag opens AR-2000-002, caudal chart with
  shaded window, peak and regulated label, no console errors.
- **Risk**: everything is verified on fixtures only; real layer data not regenerated (stays local: `clima-nqn ar layer`,
  `ar response`, `flow causes`, `flow layer`). `responses.json` size on the real catalog is unmeasured (estimate a few
  hundred KB). The 10-day response window and ranking by peak/previous-day ratio are assumptions; a low base flow
  inflates the ratio. No PR opened (user decision, branch is over 400 changed lines).

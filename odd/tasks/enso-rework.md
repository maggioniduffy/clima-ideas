# Feature: ENSO rework (F1.9 + readable ENSO panel + Rumbo line)

Objective: count extreme-rain days by ENSO phase (F1.9), replace the hard-to-read ENSO table panel with a verdict
and a one-dot-per-year chart, and record in the Rumbo that ENSO is context for extremes. Branch:
`fm/enso-rework-a76b33`. Delivery: ask-on-risk. Runners: pytest, vitest, Playwright.

## Specs

- S1 (F1.9, verbatim from the task) "count of extreme rain days (≥ p99, the threshold of F1.5) per season (DJF, MAM,
  JJA, SON) by ENSO phase and by ONI, 1980–2025, over the same polygon as F1.5. Fix the rule, threshold and polygon
  in the task spec BEFORE running anything; sensitivity with p95 and with the rectangle (Rumbo rule: main figure
  carries a sensitivity check). Report counts as "5 de 7 inviernos", never "de cada 10"; permutation test like
  F1.8; report `reports/01/F1.9.md`. First verify that the daily polygon rain series and the p99 threshold of F1.5
  are stored and reusable, and count years per phase."
  Pre-fixed rule (2026-11-12, before any run): see `plan/01-atmospheric-rivers.md`, F1.9 and "Regla de F1.9".
- S2 (panel, verbatim) "Rewrite the ENSO viewer panel (`web/src/app/EnsoPanel.tsx`, layer `ar-events`, `enso.json`
  from `clima-nqn ar layer --enso-report`): title "¿Cambia ENSO los ríos atmosféricos en Neuquén?"; plain-language
  verdict, e.g. "No se detecta diferencia entre años Niño y Niña (16 comparaciones, 1980–2025, entre 7 y 16 años
  por fase). Con tan pocos años, no detectar no prueba que no exista."; a chart with one dot per year grouped by
  phase instead of mean ± sd; source and period footer; the current table behind "ver detalle". Add the F1.9 result
  there when available. Readable font sizes (≥ 12 px ticks, 13 px meta), both themes, docs/design.md tokens,
  vitest + Playwright e2e."
- S3 (plan, verbatim) "`plan.md` Rumbo point 1: add "ENSO se informa como contexto de extremos, no como
  predictor". F3.6 adopts the F1.9 count format. F5.7 and F6.2 unchanged."

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T1 F1.9 module, CLI, layer file, tests | S1 | builder (parallel with T2) | done | d82326e, 265cbe0; pytest 285 passed, ruff clean |
| T2 ENSO panel rewrite + F1.9 block, tests | S2 | builder (parallel with T1) | done | e7efd45; vitest 185, tsc, eslint, Playwright 10/10; checked in browser with real data, light and dark |
| T3 run F1.9 on real data, report | S1 | inline (background run) | done | 265cbe0, `reports/01/F1.9.md` |
| T4 plan.md Rumbo, F3.6, phase 1 Avance | S3 | inline | done | 48abfbb + this commit |

## Log

- L1 (2026-11-12, from the parent session, user chose "Adopt all"): new F1.9 (extreme-rain days by ENSO phase),
  readable panel, Rumbo line; text of S1–S3 above is the request.
- L2 (2026-11-12) Verified: the daily polygon series is not stored; F1.4/F1.8 recompute it with
  `extremes.daily_precip` from the 46 ERA5 stores. The p99 (29.2 mm/day) is F1.4's (the request says F1.5) and is
  only in `reports/01/F1.4.md`; F1.9 recomputes it the same way and checks it. Years per phase (F1.8, ONI of the
  season): DJF 15/14/16, MAM 9/29/8, JJA 7/32/7, SON 14/18/14 (Niño/Neutro/Niña).
- L3 (2026-11-12) Plan approved by the user ("Try again" after approval). Units T1/T2 to Sonnet builders in
  parallel, disjoint edit surfaces; the F1.9 JSON shape is fixed in both handoffs.
- L4 (2026-11-13) User: "resume workin but load controlled max 4gb ram" → every heavy command runs under
  `systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0`; vitest 2 forks, Playwright 1 worker. T1 done
  (d82326e; pytest 285 passed, ruff clean; RED not captured, the first builder run was cut by the usage limit).
- L5 (2026-11-13) T3 real run (MemoryMax=2G): p99 polígono 29,2 mm/día (= F1.4), p95 13,0, p99 rectángulo 35,5;
  169/841/169 días extremos. Principal: 0 de 4 estaciones con p BH < 0,05 (Niño − Niña). SON: 6 de 14 primaveras
  Niño y 1 de 14 Niña con ≥ 1 día extremo, p 0,047 sin ajustar, p BH 0,19; ρ con ONI 0,38, p BH 0,043 solo en la
  principal (0,055 p95, 0,060 rectángulo): no robusto. JJA: 7 de 7 inviernos en ambas fases. Rule unchanged; added a
  "Lectura" next to the pre-fixed "robusto" (DJF is "no" only because the sign flips around 0 with no variant
  sustaining a difference) and the panel's sensitivity line reads all three variants.
- L6 (2026-11-13) Report wording: the SON bullet first said "robusto" after the ONI result; the pre-fixed rule only
  covers Niño − Niña, so the bullet now reads the pair and the ONI separately (ONI: "no robusto"). Panel checked
  in the browser pane with the real F1.9.json (46 dots per season, 12 px ticks, light and dark); 375 px not checked
  by hand (Playwright covers the panel at the default size only).

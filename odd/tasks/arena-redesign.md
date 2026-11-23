# Arena redesign of the web viewer + OSM basemap

Objective: restyle and re-lay-out `web/` to the "B · Arena" direction of the user's Design canvas, light and dark, and
add a real basemap (OpenStreetMap data) under the existing relief and reference layers, with a camera that never
leaves the covered area and always fills the map card.
Branch `fm/serene-curie-iu4uk1`. Delivery: one commit per task. Runner (in `web/`): `pnpm run test`, `pnpm run typecheck`,
`pnpm run lint`, `pnpm run e2e`. Replaces the look of `odd/tasks/match-mockup-design.md`; its behavior specs (handles,
narrow screens, stability) still hold unless changed below.

## Specs

Design source: https://claude.ai/artifact/D1rzvKD5vcN8ddDPvZstjN, artboards `Arena.dc.html` (light),
`Arena-Oscuro.dc.html` (dark), `Arena-Crecidas.dc.html` (a layer's detail state) and `Arena-Movil.dc.html` (390 wide).
Chart data, `[fecha]`, `[Q]` and the hero numbers in the artboards are placeholders: the app shows real values only.

- **S1 Tokens.** `tokens.css` and `tokens.ts` in parity (`tokens.test.ts`). Accent is the same in both themes.

  | Token | Light | Dark | Use |
  |---|---|---|---|
  | `--bg` | `#E4E2DC` | `#101114` | Page behind the frame |
  | `--frame-0/1/2` | `#F3F2EE` `#F1EEE4` `#F6E9B5` | `#1B1C20` `#1D1D1F` `#2E2814` | Frame gradient, 160deg, stops 0/55/100 % |
  | `--surface` | `#FBFAF7` | `#26272C` | Cards |
  | `--raised` | `#EFECE4` | `#2A2B30` | Neutral buttons, segmented-control track, selected row |
  | `--border` | `#D8D4C8` | `#3C3D43` | Thin strokes in charts and lists |
  | `--text` | `#1C1C1C` | `#F1EFE8` | Text |
  | `--text-muted` | `#5E5E5E` | `#A9A9A4` | Captions |
  | `--ctrl` | `#1C1C1C` | `#F1EFE8` | Active pill, primary button |
  | `--on-ctrl` | `#F3F2EE` | `#1B1C20` | Text on `--ctrl` |
  | `--inverse` / `--on-inverse` | `#1C1C1C` / `#F3F2EE` | `#F1EFE8` / `#1B1C20` | The one inverted card (perspectiva / modelo) |
  | `--accent` | `#F5CF4B` | `#F5CF4B` | Selection, event, playhead, highlighted bar; always with `--casing` or dark text |
  | `--casing` | `#1C1C1C` | `#101114` | Outline of accent marks |
  | `--chart-surface` | `#FFFFFF` | `#1B1C20` | Chart wells |

  `--water`, IVT, count, rain, debris and relief ramps unchanged. Contrast WCAG AA, checked in `tokens.test.ts`.
- **S2 Type.** Outfit (Google Fonts, 300/400/500/600) for all UI text: body 15px/1.4, card titles 22px/400, page `h1`
  44px/400 (30px at ≤ 800px), big numbers 64–72px/300 with tabular numerals and a 13px muted caption under each.
  IBM Plex Mono stays only for numbers inside charts, tables and the timeline (`.num`). `index.html` loads both.
- **S3 Surfaces.** Page `--bg` with 24px padding; one frame (radius 36px, 24/28px padding, frame gradient) holds
  everything. Cards: `--surface`, radius 28px, 20px padding, no borders, no texture (drop `.tx` dots and shine).
  Pills and segmented controls are radius 999px.
- **S4 Header.** Logo pill (1px `--text` outline, "Clima Ideas"), layer pills, theme button 44px round. Each layer pill
  is a `<label>` wrapping the existing visually-hidden checkbox (`layer-toggle-<id>` test ids kept): active = `--ctrl`
  fill. Several layers can be on at once, as today. The layers `aside` is removed on desktop; at ≤ 800px the pills
  scroll horizontally in one row (no drawer). The ENSO button moves to the events card header.
- **S5 Hero row.** `h1` = title of the selected layer; right side up to 3 big numbers that the selected layer's panel
  already computes (e.g. events shown, stations, catchments), each with its caption and the layer's source and period
  on one muted line. No hardcoded study results. Nothing to show → only the `h1`.
- **S6 Body.** Grid of cards: map card (spans 2 columns, min-height 420px), then the existing cards (inspector, detail,
  event list) restyled; the forecast/perspective card uses `--inverse`. At ≤ 800px everything stacks in order header,
  h1, numbers, map, cards. Drag handles (S10 of the old task) keep working between map and card column and above the
  timeline.
- **S7 Timeline.** A pill (`--surface`, radius 999px): label, 6px track on `--raised` with `--accent` progress,
  time in `.num`, round 44px play button on `--ctrl` with the accent glyph. Prev/next stay as 44px round `--raised`.
  `Timeline.test.tsx` inline `left` percentages and mark colors stay.
- **S8 Charts.** Bars and dots in `--text`, highlight in `--accent` with `--casing`, wells on `--chart-surface`.
  Mono numerals only inside charts.
- **S9 Basemap.** A raster basemap from OpenStreetMap data drawn by deck.gl (`TileLayer` + `BitmapLayer`, new dep
  `@deck.gl/geo-layers` at the same 9.x as the rest) as the bottom layer: CARTO `light_all` in light,
  `dark_all` in dark (`https://{a-d}.basemaps.cartocdn.com/{style}/{z}/{x}/{y}@2x.png`). Attribution always visible in
  the map card: "© OpenStreetMap contributors © CARTO". CARTO's terms are "sin verificar" for this use: the T4 report
  records the URL read. Reference layers and data layers stay on top.
- **S10 Background control.** Segmented control in the map card, bottom-right: "Relieve", "Mapa", "Ambos" (default
  "Ambos"). Relieve = today's relief only; Mapa = basemap only; Ambos = basemap with the relief at reduced opacity
  so roads, towns and labels read through (start at 0.55, tune by screenshot). Persists in `localStorage`
  `map-background`; invalid value → default. Test ids `map-bg-relief`, `map-bg-basemap`, `map-bg-both`.
- **S11 Camera limits.** Covered area = the ERA5 box (34–43 °S, 74–66 °O, see `docs/architecture.md`, "Área del
  visor"). A pure, unit-tested `clampView(view, size)`:
  `minZoom` is the zoom at which the box *covers* the card (not fits), recomputed on resize; the center is clamped so
  that at pitch 0 no box edge enters the card; `maxZoom` 12. Applied to every view change (drag, wheel, focus fly-to).
  The deck canvas fills the card at every size (no letterbox, no gap at the rounded corners) and the card's
  background under the canvas is the basemap color, never the page.
- **S12 Design doc.** `docs/design.md` (Spanish) rewritten to this design: reference artboards, token tables, type,
  surfaces, controls, layout, basemap and camera rules. The rule "sin etiquetas ni descripciones secundarias" becomes:
  one short caption per big number and the "Experimental" tag are allowed; no other badges. The forecast rules of
  `CLAUDE.md` (no levels, colors or thresholds; official links) are restated.
- **S13 Stability.** Existing test ids, roles and aria labels kept unless the element is removed; e2e that relied on
  the layers `aside` move to the pills.

## Tasks

- [x] T1 Tokens, fonts, base styles, design doc — S1, S2, S3, S12
- [ ] T2 Frame, header pills, hero row, layout — S3, S4, S5, S6, S13
- [ ] T3 Cards, inverse card, timeline, charts — S6, S7, S8
- [x] T4 Basemap, background control, camera limits — S9, S10, S11
- [ ] T5 Verify: unit, typecheck, lint, e2e; screenshots light and dark at 1440×900 and 390 wide against the artboards

Order: T1 → T2 → T3 (share `shell.css`), T4 can run after T1 (touches `MapCanvas.tsx` and map layers only).
e2e never reaches the tile server: tile requests are routed to a fixture tile.

## Log

- L1 (2026-11-23) User picked direction B ("Go with B") from three on the canvas; dark, station and mobile artboards added.
- L2 (2026-11-23) User, verbatim: "1. Replace everything you need and update the design docs with this model 2. Ok
  3. Let's add a real map from openstreet or maplibre going alongside the relief and basemap we have 4. The map
  shouldn't zoom out more than the covered area and it must fill its container"
- L3 (2026-11-23) Basemap drawn inside deck.gl (raster tiles) instead of a MapLibre canvas: keeps the single
  deck.gl camera, the pitched 3D relief and every existing layer and test unchanged.
- L4 (2026-11-23) T1 764fe70 + 714b0ef (layer color fixtures). T4 a34a3d3: unit 347, lint, typecheck, e2e 33 pass;
  CARTO terms "sin verificar" (proxy blocked carto.com, `reports/web/T4-basemap.md`); relief opacity 0.55 not tuned
  yet; initial zoom is now the cover zoom (~6.4 at 1440×900).

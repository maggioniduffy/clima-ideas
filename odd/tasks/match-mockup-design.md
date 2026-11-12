# Match the web viewer to the "Mockup con datos de ejemplo" design

Objective: restyle and re-lay-out `web/` to match the Mockup artboards of the user's Design canvas (light, blue accent; dark, yellow accent).
Branch `fm/match-mockup-design`. Delivery: `ask-on-risk`, one commit per task. Runner: `pnpm run test` (vitest), `pnpm run typecheck`, `pnpm run lint`, `pnpm run e2e` (Playwright), all in `web/`.

## Specs

Design source: https://claude.ai/artifact/LPUfQ1KS8iZA9rkipwoi3Y, artboards under "Mockup con datos de ejemplo" (`project/Mockup.dc.html`). The wireframe artboards are not the target.

- **S1 Tokens.** `web/src/theme/tokens.css` and `tokens.ts` carry these values, in parity (`tokens.test.ts`):

  | Token | Light | Dark |
  |---|---|---|
  | `--bg` | `#F1EEE6` | `#16212A` |
  | `--surface` | `#F9F7F2` | `#1F2D37` |
  | `--raised` | `#EFECE4` | `#2A3A46` |
  | `--border` | `#DDD8CD` | `#3E505B` |
  | `--text` | `#2A343B` | `#ECE7DC` |
  | `--text-muted` | `#5F6468` | `#A3AEB4` |
  | `--ctrl` (new) | `#3E505B` | `#4D6372` |
  | `--on-ctrl` (new) | `#F5F2EA` | `#ECE7DC` |
  | `--accent` (per theme) | `#8EB8E5` | `#FDDA0D` |
  | `--water` (new) | `#3A6E8F` | `#7FA9C6` |
  | `--casing` (new) | `#2A343B` | `#16212A` |
  | `--relief-0..3` | `#A7AEAF` `#77848A` `#4A5A64` `#2A343B` | `#4E5F6A` `#7D8D96` `#B3BEC4` `#ECE7DC` |

  `--secondary #A4AF69`, `--main`, spacing, radii and the IVT ramps are unchanged.
- **S2 Type.** Body in IBM Plex Sans 14px / 1.4. IBM Plex Mono with tabular numerals only for numbers, dates and units (a `.num` utility class). Card titles 14px/600; page title and inspector title 16px/600.
- **S3 Surfaces.** No borders between regions. Page background `--bg`, 8px padding and 8px gaps; every panel is a `--surface` card with 8px radius and 16px padding. In light, cards carry a dotted texture (`radial-gradient(rgba(42,52,59,0.09) 0.9px, transparent 1.3px)` at `5px 5px`) plus a diagonal highlight (`linear-gradient(135deg, rgba(255,255,255,0.45) 0%, transparent 55%)`); dark has neither.
- **S4 Controls.** 44px targets, 8px radius, no border. Neutral buttons on `--raised`; primary (play) on `--ctrl` with `--on-ctrl` text. Checkboxes 18px, `accent-color: var(--ctrl)`, rows 40px. Selected list row: `--raised` background and an 8px `--accent` dot. Focus ring: 2px `--accent`, 2px offset. Accent marks on map and charts get a `--casing` outline.
- **S5 Layout.** Header (min 56px, `--surface`, textured): logo mark, "Clima Ideas", page `h1`, theme toggle 44px. Body: layers `aside` 240px by default; main column with the map card (flex 1, min-height 400px), a card row under it (inspector `1 1 300px`, detail charts `1.6 1 420px`, event list `1 1 300px`), and the timeline strip. Same layout and same region boxes in both themes.
- **S6 Only what works.** No section nav, ENSO-phase filter or Período buttons. Every control shown does something today.
- **S7 Mapping of existing features.** Inspector is the first card of the row with label-left / mono-value-right rows (min-height 28px); source and period rows stay. The detail card hosts `FloodStationPanel` charts when a station is selected and the `EnsoPanel` table when opened (no longer a map overlay); with nothing to show it is not rendered. The AR event list leaves the layer panel and becomes the third card: 48px rows (dot, name, mono value and date), count in the title. The ENSO button stays in the layer panel as a neutral 44px button.
- **S8 Timeline.** 44px prev / play / next buttons with the mockup icons, play on `--ctrl`; track restyled (2px baseline, accent ticks, 5px accent playhead); replay time in mono. Inline `left` percentages and mark colors asserted by `Timeline.test.tsx` are unchanged.
- **S9 Map chrome and colors.** Map in a rounded card. Legend bottom-left without border. A clock box top-right shows the replay timestamp while a replay is active. deck.gl colors come from `tokens.ts`: relief ramp, rivers `--water`, selection `--accent` with `--casing`.
- **S10 Drag handles.** User, verbatim: "Keep them, and make them able to hide completely what they drag". Handles: layers (width), card row (height), timeline (height), placed in the 8px gaps. Dragging below the panel's minimum snaps it to 0: the panel is hidden (`hidden`, out of the tab order) and the map takes the space; the handle stays at the edge so it can be dragged back. Keyboard: arrows resize as today, Home collapses, End maximizes, Enter or double click restores the default. `aria-valuemin` is 0 and `aria-valuenow` is 0 when collapsed. Sizes and collapsed state persist in `localStorage` `panel-sizes`; invalid or missing keys fall back to defaults.
- **S11 Narrow screens (≤ 800px).** Layers stays a drawer. The inspector drawer and its toggle are removed: the cards stack under the map and the page scrolls. No handles.
- **S12 Design doc.** User, verbatim: "Update it to this design". `docs/design.md` (Spanish) describes this design, no longer "provisorio": target artboards, token tables, type, surface and control rules, layout, handle rules; IVT and flood sections kept and adjusted.
- **S13 Stability.** Existing test ids, roles and aria labels are kept unless the element itself is removed.

## Tasks

- [x] T1 Tokens, base styles, design doc — S1, S2, S3 (utilities), S4 (focus ring), S12 — route: delegated (builder, user model-roles rule) — commit: ac5bb33
- [x] T2 Shell layout and collapsible handles — S5, S10, S11, S13 — route: delegated — commit:
- [x] T3 Cards and controls — S3, S4, S6, S7, S8, S9 (chrome), S13 — route: delegated — commit:
- [x] T4 Map colors — S9 (deck.gl) — route: delegated — commit:
- [ ] T5 Verify: e2e and browser comparison against the artboards, light and dark, 1440×900 and phone width — route: inline

## Log

- L1 (2026-11-12) User request, verbatim: "match the design to this https://claude.ai/artifact/LPUfQ1KS8iZA9rkipwoi3Y#play-f1eb2b821ccc !!! and remember it - new branch"
- L2 (2026-11-12) User, on which artboards: "The ones that says "Mockup con datos de ejemplo""
- L3 (2026-11-12) User chose "Full mockup layout" and "Only what works".
- L4 (2026-11-12) User, on the plan's drag handles: "Keep them, and make them able to hide completely what they drag". On docs/design.md: "Update it to this design".
- L5 (2026-11-12) Forecast is above 400 changed lines; tasks are sequential because they share `shell.css`.
- L6 (2026-11-12) T2 done: unit 148 pass, shell e2e 4 pass. Open for T3: `e2e/ar-events.spec.ts:154` (inspector must not overflow its card in the row), card-row label still local in `Shell.tsx` (move to `i18n/es.ts`).

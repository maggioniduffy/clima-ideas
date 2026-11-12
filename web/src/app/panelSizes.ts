/** Pure sizing logic for the resizable shell panels: limits, clamping, keyboard steps and persistence. */

export type PanelId = "layers" | "cards" | "timeline";
/** Panel sizes in px; 0 means the panel is collapsed (hidden). */
export type PanelSizes = Record<PanelId, number>;
export interface Viewport {
  width: number;
  height: number;
}

/** `layers` is a width, `cards` (the card row under the map) and `timeline` are heights. */
export const PANEL_LIMITS: Record<PanelId, { min: number; max: number; def: number }> = {
  layers: { min: 160, max: 480, def: 240 },
  cards: { min: 160, max: 520, def: 260 },
  timeline: { min: 80, max: 480, def: 136 },
};
export const DEFAULT_SIZES: PanelSizes = {
  layers: PANEL_LIMITS.layers.def,
  cards: PANEL_LIMITS.cards.def,
  timeline: PANEL_LIMITS.timeline.def,
};
/** The map card never gets smaller than this (below it the page scrolls). */
export const MIN_MAP_W = 320;
export const MIN_MAP_H = 400;
export const TOPBAR_H = 56;
/** Page padding and the gap that holds each drag handle. */
export const BODY_PAD = 8;
export const HANDLE = 8;
export const KEY_STEP = 16;
export const STORAGE_KEY = "panel-sizes";

const PANELS = Object.keys(PANEL_LIMITS) as PanelId[];

/** Allowed range for a panel given the other panels' sizes and the window; min wins when space runs out. */
export function limitsFor(panel: PanelId, sizes: PanelSizes, vp: Viewport): { min: number; max: number } {
  const { min, max } = PANEL_LIMITS[panel];
  const column = vp.height - TOPBAR_H - 2 * BODY_PAD - 2 * HANDLE - MIN_MAP_H;
  const room =
    panel === "layers"
      ? vp.width - 2 * BODY_PAD - HANDLE - MIN_MAP_W
      : panel === "cards"
        ? column - sizes.timeline
        : column - sizes.cards;
  return { min, max: Math.max(min, Math.min(max, Math.floor(room))) };
}

/** 0 (collapsed) stays 0; anything else is clamped to the panel's range. */
export function clampSize(panel: PanelId, value: number, sizes: PanelSizes, vp: Viewport): number {
  const { min, max } = limitsFor(panel, sizes, vp);
  if (!Number.isFinite(value)) return PANEL_LIMITS[panel].def;
  if (value <= 0) return 0;
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** Re-clamp every panel against the window (cards first, then the timeline against the clamped cards). */
export function clampAll(sizes: PanelSizes, vp: Viewport): PanelSizes {
  const layers = clampSize("layers", sizes.layers, sizes, vp);
  const cards = clampSize("cards", sizes.cards, sizes, vp);
  const timeline = clampSize("timeline", sizes.timeline, { ...sizes, cards }, vp);
  return { layers, cards, timeline };
}

/**
 * Value after a key press, or null when the key does nothing. `dir` is +1 when moving the handle toward
 * the end of the axis (right/down) grows the panel and -1 when it shrinks it. Home collapses (0), End
 * maximizes, Enter restores `def`; arrows move 16 px, stop at `min`, and bring a collapsed panel back at `min`.
 */
export function stepSize(
  key: string,
  orientation: "vertical" | "horizontal",
  dir: 1 | -1,
  value: number,
  min: number,
  max: number,
  def: number,
): number | null {
  if (key === "Home") return 0;
  if (key === "End") return max;
  if (key === "Enter") return def;
  const grow = orientation === "vertical" ? "ArrowRight" : "ArrowDown";
  const shrink = orientation === "vertical" ? "ArrowLeft" : "ArrowUp";
  if (key !== grow && key !== shrink) return null;
  const delta = (key === grow ? KEY_STEP : -KEY_STEP) * dir;
  if (value === 0) return delta > 0 ? min : 0;
  return Math.min(max, Math.max(min, value + delta));
}

/**
 * Stored sizes, falling back per panel to the default when missing or invalid (0 = collapsed is valid).
 * The old shape (with an inspector width) is ignored as a whole.
 */
export function loadSizes(): PanelSizes {
  const out = { ...DEFAULT_SIZES };
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Record<string, unknown> | null;
    if (raw && typeof raw === "object" && !("inspector" in raw)) {
      for (const p of PANELS) {
        const v = raw[p];
        if (typeof v !== "number" || !Number.isFinite(v)) continue;
        if (v === 0 || (v >= PANEL_LIMITS[p].min && v <= PANEL_LIMITS[p].max)) out[p] = v;
      }
    }
  } catch {
    /* storage unavailable or corrupt: defaults */
  }
  return out;
}

export function saveSizes(sizes: PanelSizes): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sizes));
  } catch {
    /* storage unavailable: sizes still apply for this session */
  }
}

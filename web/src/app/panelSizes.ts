/** Pure sizing logic for the resizable shell panels: limits, clamping, keyboard steps and persistence. */

export type PanelId = "panels" | "timeline";
/** Panel sizes in px; 0 means the panel is collapsed (hidden). */
export type PanelSizes = Record<PanelId, number>;
export interface Viewport {
  width: number;
  height: number;
}

/** `panels` is the width of the right column (layers, inspector, detail, events); `timeline` is the height of the bottom strip. */
export const PANEL_LIMITS: Record<PanelId, { min: number; max: number; def: number }> = {
  panels: { min: 320, max: 640, def: 440 },
  timeline: { min: 80, max: 480, def: 136 },
};
export const DEFAULT_SIZES: PanelSizes = {
  panels: PANEL_LIMITS.panels.def,
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

/** Allowed range for a panel given the window; min wins when space runs out. The map keeps MIN_MAP_W x MIN_MAP_H. */
export function limitsFor(panel: PanelId, _sizes: PanelSizes, vp: Viewport): { min: number; max: number } {
  const { min, max } = PANEL_LIMITS[panel];
  const room =
    panel === "panels"
      ? vp.width - 2 * BODY_PAD - HANDLE - MIN_MAP_W
      : vp.height - TOPBAR_H - 2 * BODY_PAD - HANDLE - MIN_MAP_H;
  return { min, max: Math.max(min, Math.min(max, Math.floor(room))) };
}

/** 0 (collapsed) stays 0; anything else is clamped to the panel's range. */
export function clampSize(panel: PanelId, value: number, sizes: PanelSizes, vp: Viewport): number {
  const { min, max } = limitsFor(panel, sizes, vp);
  if (!Number.isFinite(value)) return PANEL_LIMITS[panel].def;
  if (value <= 0) return 0;
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** Re-clamp every panel against the window. */
export function clampAll(sizes: PanelSizes, vp: Viewport): PanelSizes {
  return {
    panels: clampSize("panels", sizes.panels, sizes, vp),
    timeline: clampSize("timeline", sizes.timeline, sizes, vp),
  };
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
 * Older shapes (inspector width, layers / cards) are ignored as a whole.
 */
export function loadSizes(): PanelSizes {
  const out = { ...DEFAULT_SIZES };
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Record<string, unknown> | null;
    if (raw && typeof raw === "object" && !("inspector" in raw) && !("layers" in raw)) {
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

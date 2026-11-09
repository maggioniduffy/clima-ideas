/** Pure sizing logic for the resizable shell panels: limits, clamping, keyboard steps and persistence. */

export type PanelId = "layers" | "inspector" | "timeline";
export type PanelSizes = Record<PanelId, number>;
export interface Viewport {
  width: number;
  height: number;
}

export const PANEL_LIMITS: Record<PanelId, { min: number; max: number; def: number }> = {
  layers: { min: 160, max: 480, def: 200 },
  inspector: { min: 220, max: 720, def: 260 },
  timeline: { min: 80, max: 480, def: 136 },
};
export const DEFAULT_SIZES: PanelSizes = {
  layers: PANEL_LIMITS.layers.def,
  inspector: PANEL_LIMITS.inspector.def,
  timeline: PANEL_LIMITS.timeline.def,
};
/** The map never gets smaller than this. */
export const MIN_MAP_W = 320;
export const MIN_MAP_H = 200;
export const TOPBAR_H = 48;
export const KEY_STEP = 16;
export const STORAGE_KEY = "panel-sizes";

const PANELS = Object.keys(PANEL_LIMITS) as PanelId[];

/** Allowed range for a panel given the other panels' sizes and the window; min wins when space runs out. */
export function limitsFor(panel: PanelId, sizes: PanelSizes, vp: Viewport): { min: number; max: number } {
  const { min, max } = PANEL_LIMITS[panel];
  const room =
    panel === "layers"
      ? vp.width - sizes.inspector - MIN_MAP_W
      : panel === "inspector"
        ? vp.width - sizes.layers - MIN_MAP_W
        : vp.height - TOPBAR_H - MIN_MAP_H;
  return { min, max: Math.max(min, Math.min(max, Math.floor(room))) };
}

export function clampSize(panel: PanelId, value: number, sizes: PanelSizes, vp: Viewport): number {
  const { min, max } = limitsFor(panel, sizes, vp);
  if (!Number.isFinite(value)) return PANEL_LIMITS[panel].def;
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** Re-clamp every panel against the window (layers first, then the inspector against the clamped layers). */
export function clampAll(sizes: PanelSizes, vp: Viewport): PanelSizes {
  const layers = clampSize("layers", sizes.layers, sizes, vp);
  const inspector = clampSize("inspector", sizes.inspector, { ...sizes, layers }, vp);
  const timeline = clampSize("timeline", sizes.timeline, sizes, vp);
  return { layers, inspector, timeline };
}

/**
 * Value after a key press, or null when the key does nothing. `dir` is +1 when moving the handle toward
 * the end of the axis (right/down) grows the panel and -1 when it shrinks it.
 */
export function stepSize(
  key: string,
  orientation: "vertical" | "horizontal",
  dir: 1 | -1,
  value: number,
  min: number,
  max: number,
): number | null {
  if (key === "Home") return min;
  if (key === "End") return max;
  const grow = orientation === "vertical" ? "ArrowRight" : "ArrowDown";
  const shrink = orientation === "vertical" ? "ArrowLeft" : "ArrowUp";
  if (key !== grow && key !== shrink) return null;
  const delta = (key === grow ? KEY_STEP : -KEY_STEP) * dir;
  return Math.min(max, Math.max(min, value + delta));
}

/** Stored sizes, falling back per panel to the default when missing or invalid. */
export function loadSizes(): PanelSizes {
  const out = { ...DEFAULT_SIZES };
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Record<string, unknown> | null;
    if (raw && typeof raw === "object") {
      for (const p of PANELS) {
        const v = raw[p];
        if (typeof v === "number" && Number.isFinite(v) && v >= PANEL_LIMITS[p].min && v <= PANEL_LIMITS[p].max) out[p] = v;
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

import { es } from "../i18n/es";

/** "none" only exists without a basemap: relief off, nothing else to draw. */
export type MapBackgroundMode = "relief" | "basemap" | "both" | "none";
export const DEFAULT_BACKGROUND: MapBackgroundMode = "relief";
export const BACKGROUND_KEY = "map-background";
/** Relief opacity over the basemap in "both": roads, towns and labels read through (tune by screenshot). */
export const RELIEF_OPACITY_BOTH = 0.55;

export const parseBackground = (v: unknown): MapBackgroundMode =>
  v === "relief" || v === "basemap" || v === "both" || v === "none" ? v : DEFAULT_BACKGROUND;

/** The mode that applies: without a basemap only relief on / off exist; with one, "none" does not. */
export function effectiveBackground(stored: MapBackgroundMode, hasBasemap: boolean): MapBackgroundMode {
  if (hasBasemap) return stored === "none" ? DEFAULT_BACKGROUND : stored;
  return stored === "none" ? "none" : "relief";
}

/** Whether the relief layer is drawn in this mode. */
export const reliefVisible = (m: MapBackgroundMode): boolean => m === "relief" || m === "both";

export function readBackground(): MapBackgroundMode {
  try {
    return parseBackground(localStorage.getItem(BACKGROUND_KEY));
  } catch {
    return DEFAULT_BACKGROUND;
  }
}

export function writeBackground(mode: MapBackgroundMode): void {
  try {
    localStorage.setItem(BACKGROUND_KEY, mode);
  } catch {
    // storage blocked: the choice only lasts for the session
  }
}

const WITH_BASEMAP: { mode: MapBackgroundMode; id: string; label: string }[] = [
  { mode: "relief", id: "map-bg-relief", label: es.map.bgRelief },
  { mode: "basemap", id: "map-bg-basemap", label: es.map.bgBasemap },
  { mode: "both", id: "map-bg-both", label: es.map.bgBoth },
];
const RELIEF_ONLY: { mode: MapBackgroundMode; id: string; label: string }[] = [
  { mode: "relief", id: "map-bg-relief", label: es.map.bgRelief },
  { mode: "none", id: "map-bg-none", label: es.map.bgNone },
];

/** Segmented control (glass, bottom-right of the map area): relief, basemap or both; without a basemap, relief on / off. */
export function MapBackground({
  value,
  onChange,
  hasBasemap = true,
}: {
  value: MapBackgroundMode;
  onChange: (m: MapBackgroundMode) => void;
  hasBasemap?: boolean;
}) {
  return (
    <div className="map-bg glass" role="group" aria-label={es.map.bgLabel} data-testid="map-bg">
      {(hasBasemap ? WITH_BASEMAP : RELIEF_ONLY).map((o) => (
        <button
          key={o.mode}
          type="button"
          className="map-bg-btn"
          data-testid={o.id}
          aria-pressed={value === o.mode}
          onClick={() => onChange(o.mode)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

import { es } from "../i18n/es";

export type MapBackgroundMode = "relief" | "basemap" | "both";
export const DEFAULT_BACKGROUND: MapBackgroundMode = "both";
export const BACKGROUND_KEY = "map-background";
/** Relief opacity over the basemap in "both": roads, towns and labels read through (tune by screenshot). */
export const RELIEF_OPACITY_BOTH = 0.55;

export const parseBackground = (v: unknown): MapBackgroundMode =>
  v === "relief" || v === "basemap" || v === "both" ? v : DEFAULT_BACKGROUND;

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

const OPTIONS: { mode: MapBackgroundMode; id: string; label: string }[] = [
  { mode: "relief", id: "map-bg-relief", label: es.map.bgRelief },
  { mode: "basemap", id: "map-bg-basemap", label: es.map.bgBasemap },
  { mode: "both", id: "map-bg-both", label: es.map.bgBoth },
];

/** Segmented control (bottom-right of the map card): relief only, basemap only, or both. */
export function MapBackground({ value, onChange }: { value: MapBackgroundMode; onChange: (m: MapBackgroundMode) => void }) {
  return (
    <div className="map-bg" role="group" aria-label={es.map.bgLabel} data-testid="map-bg">
      {OPTIONS.map((o) => (
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

import { ScatterplotLayer } from "@deck.gl/layers";
import type { FloodStationFeature } from "../api/client";
import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import { FLOOD_LAYER_ID } from "./useFloodStation";

/** Dot radius range in pixels. */
export const STATION_RADIUS_MIN_PX = 6;
export const STATION_RADIUS_MAX_PX = 18;
/** Alpha of a regulated station's fill: hollow, but still pickable. */
const HOLLOW_ALPHA = 40;

const hex = (h: string, a = 255): [number, number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
  a,
];

/** Radius in px, proportional to sqrt(value / max) inside the fixed range (area follows the flow). */
export function stationRadius(value: number, max: number): number {
  const f = max > 0 && value > 0 ? Math.sqrt(Math.min(value, max) / max) : 0;
  return STATION_RADIUS_MIN_PX + f * (STATION_RADIUS_MAX_PX - STATION_RADIUS_MIN_PX);
}

export function buildFloodStationsLayer(
  data: FloodStationFeature[],
  selectedId: string | null,
  theme: Theme,
  onPick: (feature: FloodStationFeature) => void,
) {
  const max = Math.max(0, ...data.map((d) => d.value));
  const main = hex(tokens.brand.main);
  const accent = hex(tokens.brand.accent);
  const outline = hex(theme === "dark" ? tokens.dark.text : tokens.brand.main);
  return new ScatterplotLayer<FloodStationFeature>({
    id: `points-${FLOOD_LAYER_ID}`,
    data,
    pickable: true,
    getPosition: (d) => [d.lon, d.lat],
    radiusUnits: "pixels",
    getRadius: (d) => stationRadius(d.value, max),
    getFillColor: (d) => {
      const c = d.id === selectedId ? accent : main;
      return d.regulated ? [c[0], c[1], c[2], HOLLOW_ALPHA] : c;
    },
    stroked: true,
    getLineColor: (d) => (d.id === selectedId ? accent : outline),
    getLineWidth: (d) => (d.regulated || d.id === selectedId ? 2 : 1),
    lineWidthUnits: "pixels",
    updateTriggers: { getFillColor: [selectedId], getLineColor: [selectedId, theme], getLineWidth: [selectedId] },
    onClick: ({ object }) => {
      if (object) onPick(object);
    },
  });
}

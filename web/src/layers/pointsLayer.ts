import { ScatterplotLayer } from "@deck.gl/layers";
import type { PointFeature } from "../api/client";
import { tokens } from "../theme/tokens";
import type { Theme } from "../theme/themeStore";

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];

export function buildPointsLayer(
  layerId: string,
  data: PointFeature[],
  selectedId: string | null,
  theme: Theme,
  onPick: (feature: PointFeature) => void,
) {
  const { accent, casing, ctrl } = tokens[theme];
  const accentRgb = hex(accent);
  const casingRgb = hex(casing);
  const ctrlRgb = hex(ctrl);
  return new ScatterplotLayer<PointFeature>({
    id: `points-${layerId}`,
    data,
    pickable: true,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 8000,
    radiusMinPixels: 6,
    getFillColor: (d) => (d.id === selectedId ? accentRgb : ctrlRgb),
    getLineColor: (d) => (d.id === selectedId ? casingRgb : ctrlRgb),
    getLineWidth: (d) => (d.id === selectedId ? 2 : 1),
    lineWidthUnits: "pixels",
    stroked: true,
    updateTriggers: { getFillColor: [selectedId, theme], getLineColor: [selectedId, theme], getLineWidth: [selectedId] },
    onClick: ({ object }) => {
      if (object) onPick(object);
    },
  });
}

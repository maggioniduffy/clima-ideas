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
  const accent = hex(tokens[theme].accent);
  return new ScatterplotLayer<PointFeature>({
    id: `points-${layerId}`,
    data,
    pickable: true,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 8000,
    radiusMinPixels: 6,
    getFillColor: (d) => (d.id === selectedId ? accent : hex(tokens.brand.main)),
    getLineColor: accent,
    stroked: true,
    lineWidthMinPixels: 1,
    updateTriggers: { getFillColor: [selectedId, theme], getLineColor: [theme] },
    onClick: ({ object }) => {
      if (object) onPick(object);
    },
  });
}

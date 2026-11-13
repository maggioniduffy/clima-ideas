import { PolygonLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { FrameGrid } from "../api/client";
import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import { countColor, frameValue, ivtColor, type Cell } from "./arEvents";

export interface CellRef {
  row: number;
  col: number;
}

interface Props {
  layerId: string;
  eventId: string;
  grid: FrameGrid;
  cells: Cell[];
  frames: Float32Array;
  frame: number;
  theme: Theme;
  picked: CellRef | null;
  /** False draws no fill (the IVT is shown by the relief drape or by contours); cells stay pickable for the readings. */
  showFill?: boolean;
  onHover: (cell: CellRef | null) => void;
  onPick: (cell: CellRef) => void;
}

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];

/** Hourly |IVT| as one rectangle per ERA5 grid cell (≈1.2 k polygons), colored unless `showFill` is false; always pickable. */
export function buildIvtRasterLayer(p: Props) {
  const outline = hex(tokens[p.theme].accent);
  const isPicked = (c: Cell) => p.picked?.row === c.row && p.picked.col === c.col;
  return new PolygonLayer<Cell>({
    id: `ivt-${p.layerId}`,
    data: p.cells,
    pickable: true,
    // flat at z = 0: skip the depth test so the 3D relief below never hides it
    parameters: { depthCompare: "always" },
    getPolygon: (c) => c.polygon,
    getFillColor: (c) =>
      p.showFill === false
        ? [0, 0, 0, 0]
        : ivtColor(frameValue(p.frames, p.grid, p.frame, c.row, c.col), p.theme, true),
    getLineColor: (c) => (isPicked(c) ? [...outline, 255] : [0, 0, 0, 0]),
    stroked: true,
    lineWidthMinPixels: 2,
    updateTriggers: {
      getFillColor: [p.eventId, p.frame, p.theme, p.showFill],
      getLineColor: [p.picked?.row, p.picked?.col, p.theme],
    },
    onHover: ({ object }) => p.onHover(object ? { row: object.row, col: object.col } : null),
    onClick: ({ object }) => {
      if (object) p.onPick({ row: object.row, col: object.col });
    },
  });
}

interface CountProps {
  layerId: string;
  grid: FrameGrid;
  cells: Cell[];
  /** Events per cell, `[ny * nx]` in cell order. */
  counts: Uint16Array;
  max: number;
  theme: Theme;
}

/** Count map: one rectangle per cell reached by at least one event, sequential ramp over [0, max]; not pickable. */
export function buildCountLayer(p: CountProps) {
  const at = (c: Cell) => p.counts[c.row * p.grid.nx + c.col]!;
  return new PolygonLayer<Cell>({
    id: `ar-count-${p.layerId}`,
    data: p.cells.filter((c) => at(c) > 0),
    pickable: false,
    parameters: { depthCompare: "always" },
    getPolygon: (c) => c.polygon,
    getFillColor: (c) => countColor(at(c), p.max, p.theme),
    stroked: false,
    updateTriggers: { getFillColor: [p.counts, p.max, p.theme] },
  });
}

interface PeakProps {
  layerId: string;
  lon: number;
  lat: number;
  theme: Theme;
}

interface PeakDatum {
  position: [number, number];
}

/** Marker at the cell where the event reached its |IVT| maximum (ring in the theme's text color over the accent). */
export function buildPeakLayer(p: PeakProps) {
  const t = tokens[p.theme];
  return new ScatterplotLayer<PeakDatum>({
    id: `ar-peak-${p.layerId}`,
    data: [{ position: [p.lon, p.lat] }],
    pickable: false,
    parameters: { depthCompare: "always" },
    getPosition: (d) => d.position,
    radiusUnits: "pixels",
    getRadius: 7,
    stroked: true,
    lineWidthUnits: "pixels",
    getLineWidth: 2.5,
    getFillColor: [...hex(t.accent), 255],
    getLineColor: [...hex(t.casing), 255],
    updateTriggers: { getFillColor: [p.theme], getLineColor: [p.theme] },
  });
}

import { PolygonLayer } from "@deck.gl/layers";
import type { FrameGrid } from "../api/client";
import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import { frameValue, ivtColor, type Cell } from "./arEvents";

export interface CellRef {
  row: number;
  col: number;
}

/** IVT raster opacity while relief is drawn below it, so terrain reads through. */
export const IVT_OVER_RELIEF_OPACITY = 0.5;

interface Props {
  layerId: string;
  eventId: string;
  grid: FrameGrid;
  cells: Cell[];
  frames: Float32Array;
  frame: number;
  theme: Theme;
  picked: CellRef | null;
  /** Layer opacity (1 = as colored); lowered when terrain is drawn below so it reads through. */
  opacity?: number;
  onHover: (cell: CellRef | null) => void;
  onPick: (cell: CellRef) => void;
}

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];

/** Hourly |IVT| as one colored rectangle per ERA5 grid cell (≈1.2 k polygons), pickable. */
export function buildIvtRasterLayer(p: Props) {
  const outline = hex(tokens[p.theme].text);
  const isPicked = (c: Cell) => p.picked?.row === c.row && p.picked.col === c.col;
  return new PolygonLayer<Cell>({
    id: `ivt-${p.layerId}`,
    data: p.cells,
    pickable: true,
    opacity: p.opacity ?? 1,
    // flat at z = 0: skip the depth test so the 3D relief below never hides it
    parameters: { depthCompare: "always" },
    getPolygon: (c) => c.polygon,
    getFillColor: (c) => ivtColor(frameValue(p.frames, p.grid, p.frame, c.row, c.col), p.theme, true),
    getLineColor: (c) => (isPicked(c) ? [...outline, 255] : [0, 0, 0, 0]),
    stroked: true,
    lineWidthMinPixels: 2,
    updateTriggers: {
      getFillColor: [p.eventId, p.frame, p.theme],
      getLineColor: [p.picked?.row, p.picked?.col, p.theme],
    },
    onHover: ({ object }) => p.onHover(object ? { row: object.row, col: object.col } : null),
    onClick: ({ object }) => {
      if (object) p.onPick({ row: object.row, col: object.col });
    },
  });
}

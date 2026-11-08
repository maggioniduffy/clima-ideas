import { PolygonLayer } from "@deck.gl/layers";
import type { FrameGrid } from "../api/client";
import { tokens } from "../theme/tokens";
import { frameValue, ivtColor, type Cell } from "./arEvents";

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
  picked: CellRef | null;
  onHover: (cell: CellRef | null) => void;
  onPick: (cell: CellRef) => void;
}

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];
const OUTLINE = hex(tokens.brand.main);

/** Hourly |IVT| as one colored rectangle per ERA5 grid cell (≈1.2 k polygons), pickable. */
export function buildIvtRasterLayer(p: Props) {
  const isPicked = (c: Cell) => p.picked?.row === c.row && p.picked.col === c.col;
  return new PolygonLayer<Cell>({
    id: `ivt-${p.layerId}`,
    data: p.cells,
    pickable: true,
    getPolygon: (c) => c.polygon,
    getFillColor: (c) => ivtColor(frameValue(p.frames, p.grid, p.frame, c.row, c.col), true),
    getLineColor: (c) => (isPicked(c) ? [...OUTLINE, 255] : [0, 0, 0, 0]),
    stroked: true,
    lineWidthMinPixels: 2,
    updateTriggers: {
      getFillColor: [p.eventId, p.frame],
      getLineColor: [p.picked?.row, p.picked?.col],
    },
    onHover: ({ object }) => p.onHover(object ? { row: object.row, col: object.col } : null),
    onClick: ({ object }) => {
      if (object) p.onPick({ row: object.row, col: object.col });
    },
  });
}

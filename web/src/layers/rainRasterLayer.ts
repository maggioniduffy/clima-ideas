import { PolygonLayer } from "@deck.gl/layers";
import type { FrameGrid } from "../api/client";
import type { Theme } from "../theme/themeStore";
import { frameValue, type Cell } from "./arEvents";
import { rainColor } from "./convectionIdf";

interface Props {
  layerId: string;
  grid: FrameGrid;
  cells: Cell[];
  /** Float32 `[n_frames, ny, nx]` rate in mm/h. */
  frames: Float32Array;
  frame: number;
  theme: Theme;
}

/** Half-hourly IMERG rain rate as one rectangle per grid cell, neutral blue ramp (transparent when dry). Not pickable. */
export function buildRainRasterLayer(p: Props) {
  return new PolygonLayer<Cell>({
    id: `rain-${p.layerId}`,
    data: p.cells,
    pickable: false,
    // flat at z = 0: skip the depth test so the 3D relief below never hides it
    parameters: { depthCompare: "always" },
    getPolygon: (c) => c.polygon,
    getFillColor: (c) => rainColor(frameValue(p.frames, p.grid, p.frame, c.row, c.col), p.theme),
    stroked: false,
    updateTriggers: { getFillColor: [p.frame, p.theme] },
  });
}

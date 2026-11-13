import { PathLayer } from "@deck.gl/layers";
import type { FrameGrid } from "../api/client";
import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import { ivtColor } from "./arEvents";

/** Contour levels (kg m-1 s-1) and their line widths (px): stronger river, thicker line. */
export const IVT_CONTOUR_LEVELS = [250, 500, 750, 1000] as const;
export const IVT_CONTOUR_WIDTHS = [1.5, 2, 2.5, 3] as const;
/** Extra width (px) of the halo drawn under each line for legibility over any background. */
const HALO_EXTRA_PX = 2;

type Pt = [number, number];
/** Marching-squares segments per corner mask (SW=1, SE=2, NE=4, NW=8: corner above the level); see `contourPaths`. */
const CASES = ["", "LB", "BR", "LR", "RT", "", "BT", "LT", "LT", "BT", "", "RT", "LR", "BR", "LB"];

/**
 * Contour paths of frame `frame` at `level` by marching squares (row 0 = south). A crossing point is identified by the
 * grid edge it sits on (horizontal edge 2*(r*nx+c), vertical 2*(r*nx+c)+1), so segments stitch exactly into
 * polylines; closed rings repeat their first point. NaN counts as below every level.
 */
export function contourPaths(frames: Float32Array, grid: FrameGrid, frame: number, level: number): Pt[][] {
  const { nx, ny } = grid;
  const dlon = nx > 1 ? (grid.lon_max - grid.lon_min) / (nx - 1) : 0;
  const dlat = ny > 1 ? (grid.lat_max - grid.lat_min) / (ny - 1) : 0;
  const base = frame * nx * ny;
  const v = (r: number, c: number) => {
    const x = frames[base + r * nx + c]!;
    return Number.isNaN(x) ? -Infinity : x;
  };
  const point = new Map<number, Pt>();
  const edge = (r: number, c: number, vertical: boolean): number => {
    const id = 2 * (r * nx + c) + (vertical ? 1 : 0);
    if (!point.has(id)) {
      const [a, b] = vertical ? [v(r, c), v(r + 1, c)] : [v(r, c), v(r, c + 1)];
      const t = Number.isFinite(a) && Number.isFinite(b) ? (level - a) / (b - a) : 0.5; // a hole: cut mid-edge
      point.set(id, [grid.lon_min + (c + (vertical ? 0 : t)) * dlon, grid.lat_min + (r + (vertical ? t : 0)) * dlat]);
    }
    return id;
  };
  const adj = new Map<number, number[]>();
  const link = (p: number, q: number) => {
    adj.set(p, [...(adj.get(p) ?? []), q]);
    adj.set(q, [...(adj.get(q) ?? []), p]);
  };
  for (let r = 0; r < ny - 1; r++)
    for (let c = 0; c < nx - 1; c++) {
      const [a, b, cc, d] = [v(r, c), v(r, c + 1), v(r + 1, c + 1), v(r + 1, c)];
      const mask = (a > level ? 1 : 0) | (b > level ? 2 : 0) | (cc > level ? 4 : 0) | (d > level ? 8 : 0);
      if (mask === 0 || mask === 15) continue;
      const centerHigh = (a + b + cc + d) / 4 > level;
      // edges by letter: Bottom (south), Top, Left (west), Right; saddles (5, 10) split by the cell center
      const pairs =
        mask === 5 ? (centerHigh ? "BR LT" : "LB RT") : mask === 10 ? (centerHigh ? "LB RT" : "BR LT") : CASES[mask]!;
      for (const pair of pairs.split(" ")) {
        const [p, q] = [...pair].map((e) =>
          e === "B"
            ? edge(r, c, false)
            : e === "T"
              ? edge(r + 1, c, false)
              : e === "L"
                ? edge(r, c, true)
                : edge(r, c + 1, true),
        );
        link(p!, q!);
      }
    }

  // stitch: start from open ends (degree 1) first, then walk the remaining closed rings
  const seen = new Set<string>();
  const key = (p: number, q: number) => (p < q ? `${p}-${q}` : `${q}-${p}`);
  const walk = (start: number): Pt[] => {
    const path = [start];
    let cur = start;
    for (;;) {
      const next = adj.get(cur)!.find((n) => !seen.has(key(cur, n)));
      if (next == null) break;
      seen.add(key(cur, next));
      path.push(next);
      cur = next;
    }
    return path.map((id) => point.get(id)!);
  };
  const paths: Pt[][] = [];
  for (const [id, n] of adj) if (n.length === 1) paths.push(walk(id));
  for (const id of adj.keys()) if (adj.get(id)!.some((n) => !seen.has(key(id, n)))) paths.push(walk(id));
  return paths;
}

interface ContourProps {
  layerId: string;
  eventId: string;
  grid: FrameGrid;
  frames: Float32Array;
  frame: number;
  theme: Theme;
  /** Only these levels (default: all of IVT_CONTOUR_LEVELS). */
  levels?: readonly number[];
  /** Appended to the layer ids so a second set of contours (e.g. the event core) can coexist. */
  idSuffix?: string;
}

interface ContourDatum {
  level: number;
  width: number;
  path: Pt[];
}

/** Halo + colored contour lines at IVT_CONTOUR_LEVELS for the current frame; flat at z = 0, drawn over the relief. */
export function buildIvtContourLayers(p: ContourProps) {
  const data: ContourDatum[] = IVT_CONTOUR_LEVELS.flatMap((level, i) =>
    p.levels && !p.levels.includes(level)
      ? []
      : contourPaths(p.frames, p.grid, p.frame, level).map((path) => ({
          level,
          width: IVT_CONTOUR_WIDTHS[i]!,
          path,
        })),
  );
  const hex = tokens[p.theme].bg;
  const halo = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const shared = {
    data,
    pickable: false,
    getPath: (d: ContourDatum) => d.path,
    widthUnits: "pixels" as const,
    capRounded: true,
    jointRounded: true,
    // flat at z = 0: skip the depth test so the 3D relief below never hides it
    parameters: { depthCompare: "always" as const },
    updateTriggers: {
      getPath: [p.eventId, p.frame],
      getColor: [p.theme],
      getWidth: [p.theme],
    },
  };
  return [
    new PathLayer<ContourDatum>({
      ...shared,
      id: `ivt-contours-halo-${p.layerId}${p.idSuffix ?? ""}`,
      getColor: [halo[0]!, halo[1]!, halo[2]!, 200],
      getWidth: (d) => d.width + HALO_EXTRA_PX,
    }),
    new PathLayer<ContourDatum>({
      ...shared,
      id: `ivt-contours-${p.layerId}${p.idSuffix ?? ""}`,
      getColor: (d) => ivtColor(d.level, p.theme),
      getWidth: (d) => d.width,
    }),
  ];
}

import { PointCloudLayer } from "@deck.gl/layers";
import type { FrameGrid } from "../api/client";
import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import { IVT_ALPHA_MAX, IVT_SCALE_MAX, ivtColor } from "./arEvents";

/** Binary layout of relief.bin: little-endian Float32 [lon, lat, elev_m] per point. */
const STRIDE = 3;
/** Vertical exaggeration applied to elevation (m) so relief reads at province scale. */
export const RELIEF_EXAGGERATION = 3;
/** Fallback grid step (degrees): keep in sync with `DEFAULT_STEP` in backend io/dem.py; the viewer prefers relief.meta.json `step`. */
export const RELIEF_STEP = 0.008;
/** Elevation (m) of each `tokens.reliefRamp` stop (slate ramp): lowland, mid, high, peaks. */
export const RELIEF_STOPS_M = [0, 800, 1800, 3000] as const;
/** Hillshade: sun from the NW (azimuth clockwise from north) at 45 degrees; slopes exaggerated for shading only. */
export const SUN_AZIMUTH_DEG = 315;
export const SUN_ALTITUDE_DEG = 45;
export const SHADE_EXAGGERATION = 3.5;
const SHADE_MIN = 0.25;
const SHADE_MAX = 1.5;

export interface ReliefData {
  length: number;
  /** Interleaved lon, lat, z (m × exaggeration). */
  positions: Float32Array;
  /** Elevation in meters per point. */
  elevation: Float32Array;
  /** Hillshade multiplier per point (1 = flat terrain), computed on the full grid before clipping. */
  shade: Float32Array;
  /** Cached RGBA colors per theme. */
  colorCache: Partial<Record<Theme, Uint8Array>>;
}

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];

/** Slate tint for an elevation in meters: piecewise-linear over RELIEF_STOPS_M, theme-specific tokens. */
export function reliefColor(elevM: number, theme: Theme): [number, number, number] {
  const stops = tokens.reliefRamp[theme].map(hex);
  const last = RELIEF_STOPS_M.length - 1;
  if (!(elevM > RELIEF_STOPS_M[0])) return stops[0]!;
  if (elevM >= RELIEF_STOPS_M[last]!) return stops[last]!;
  let i = 0;
  while (elevM >= RELIEF_STOPS_M[i + 1]!) i++;
  const f = (elevM - RELIEF_STOPS_M[i]!) / (RELIEF_STOPS_M[i + 1]! - RELIEF_STOPS_M[i]!);
  return [0, 1, 2].map((c) => Math.round(stops[i]![c]! + (stops[i + 1]![c]! - stops[i]![c]!) * f)) as [
    number,
    number,
    number,
  ];
}

/** Lambertian shade (0..1+) of a surface with elevation gradients dzdx (east) and dzdy (north), both unitless. */
export function hillshade(dzdx: number, dzdy: number): number {
  const az = (SUN_AZIMUTH_DEG * Math.PI) / 180;
  const alt = (SUN_ALTITUDE_DEG * Math.PI) / 180;
  const lx = Math.sin(az) * Math.cos(alt);
  const ly = Math.cos(az) * Math.cos(alt);
  const lz = Math.sin(alt);
  const k = SHADE_EXAGGERATION;
  const nx = -dzdx * k;
  const ny = -dzdy * k;
  const dot = (nx * lx + ny * ly + lz) / Math.hypot(nx, ny, 1);
  return Math.min(SHADE_MAX, Math.max(SHADE_MIN, dot / lz));
}

/** RGBA per point: hypsometric tint multiplied by the hillshade. */
export function reliefColors(relief: ReliefData, theme: Theme): Uint8Array {
  const cached = relief.colorCache[theme];
  if (cached) return cached;
  const colors = new Uint8Array(relief.length * 4);
  // 1 m quantization: the tint only changes slowly, so cache it per whole meter
  const tint = new Map<number, [number, number, number]>();
  for (let i = 0; i < relief.length; i++) {
    const m = Math.round(relief.elevation[i]!);
    let c = tint.get(m);
    if (!c) tint.set(m, (c = reliefColor(m, theme)));
    const s = relief.shade[i]!;
    colors[i * 4] = Math.min(255, Math.round(c[0] * s));
    colors[i * 4 + 1] = Math.min(255, Math.round(c[1] * s));
    colors[i * 4 + 2] = Math.min(255, Math.round(c[2] * s));
    colors[i * 4 + 3] = 255;
  }
  relief.colorCache[theme] = colors;
  return colors;
}

/**
 * Parse relief.bin. Points sit on a regular lon/lat grid (not in a single row order: tiles are concatenated), so the
 * grid is rebuilt by index to compute the hillshade from neighbouring elevations. Every point is kept (the layer
 * already spans the whole ERA5 rectangle; no clipping).
 */
export function parseRelief(buffer: ArrayBuffer, step = RELIEF_STEP): ReliefData {
  if (buffer.byteLength % (STRIDE * 4) !== 0) throw new Error("relief.bin: size is not a multiple of the stride");
  const src = new Float32Array(buffer);
  const n = src.length / STRIDE;

  let lon0 = Infinity;
  let lon1 = -Infinity;
  let lat0 = Infinity;
  let lat1 = -Infinity;
  for (let i = 0; i < n; i++) {
    const lon = src[i * STRIDE]!;
    const lat = src[i * STRIDE + 1]!;
    if (lon < lon0) lon0 = lon;
    if (lon > lon1) lon1 = lon;
    if (lat < lat0) lat0 = lat;
    if (lat > lat1) lat1 = lat;
  }
  const nx = n ? Math.round((lon1 - lon0) / step) + 1 : 0;
  const ny = n ? Math.round((lat1 - lat0) / step) + 1 : 0;
  const grid = new Float32Array(nx * ny).fill(NaN);
  const cell = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    const ix = Math.round((src[i * STRIDE]! - lon0) / step);
    const iy = Math.round((src[i * STRIDE + 1]! - lat0) / step);
    cell[i] = iy * nx + ix;
    grid[cell[i]!] = src[i * STRIDE + 2]!;
  }

  const count = n;

  const positions = new Float32Array(count * STRIDE);
  const elevation = new Float32Array(count);
  const shade = new Float32Array(count);
  const mPerDegLat = 110_574;
  const mPerDegLon = 111_320;
  let o = 0;
  for (let i = 0; i < n; i++) {
    const lat = src[i * STRIDE + 1]!;
    const elev = src[i * STRIDE + 2]!;
    const ix = cell[i]! % nx;
    const iy = (cell[i]! - ix) / nx;
    // neighbour elevation, falling back to the point itself at edges or holes
    const at = (x: number, y: number) => {
      const v = x < 0 || y < 0 || x >= nx || y >= ny ? NaN : grid[y * nx + x]!;
      return Number.isNaN(v) ? elev : v;
    };
    const dxm = step * mPerDegLon * Math.cos((lat * Math.PI) / 180);
    const dym = step * mPerDegLat;
    const dzdx = (at(ix + 1, iy) - at(ix - 1, iy)) / (2 * dxm);
    const dzdy = (at(ix, iy + 1) - at(ix, iy - 1)) / (2 * dym);
    positions[o * STRIDE] = src[i * STRIDE]!;
    positions[o * STRIDE + 1] = lat;
    positions[o * STRIDE + 2] = elev * RELIEF_EXAGGERATION;
    elevation[o] = elev;
    shade[o] = hillshade(dzdx, dzdy);
    o++;
  }
  return { length: count, positions, elevation, shade, colorCache: {} };
}

// --- IVT drape: relief colored by the IVT field (view "drape") ------------------------------------------------------

/** Neutral relief base (0..1 per channel) where there is no river, per theme; multiplied by the shade gray. Dark is a
 * mid slate so terrain without a river does not glow against the dark UI. */
export const DRAPE_NEUTRAL: Record<Theme, readonly [number, number, number]> = {
  light: [0.95, 0.95, 0.93],
  dark: [0.55, 0.6, 0.63],
};
/** Shade gray: hillshade (0.25..1.5, 1 = flat) mapped to a 0..1 brightness, so terrain stays visible under the river. */
const drapeGray = (shade: number) => Math.min(1, Math.max(0, 0.35 + 0.75 * shade));

/** Per-theme lookup over whole IVT units 0..IVT_SCALE_MAX: ramp rgb and blend weight k (ivtAlpha normalized to 0..1). */
const lutCache: Partial<
  Record<Theme, { rgb: Uint8Array; k: Float32Array; neutral: readonly [number, number, number] }>
> = {};
function drapeLut(theme: Theme) {
  let lut = lutCache[theme];
  if (!lut) {
    const rgb = new Uint8Array((IVT_SCALE_MAX + 1) * 3);
    const k = new Float32Array(IVT_SCALE_MAX + 1);
    for (let v = 0; v <= IVT_SCALE_MAX; v++) {
      const [r, g, b, a] = ivtColor(v, theme, true);
      rgb.set([r, g, b], v * 3);
      k[v] = a / 255 / IVT_ALPHA_MAX;
    }
    lut = lutCache[theme] = { rgb, k, neutral: DRAPE_NEUTRAL[theme] };
  }
  return lut;
}

/** Drape color of one relief point: mix(neutral, ramp color) by the IVT blend weight, times the shade gray. */
export function drapeColor(ivt: number | null | undefined, shade: number, theme: Theme): [number, number, number] {
  const out = new Uint8Array(4);
  paintDrape(out, 0, ivt == null || Number.isNaN(ivt) ? 0 : ivt, shade, drapeLut(theme));
  return [out[0]!, out[1]!, out[2]!];
}

function paintDrape(out: Uint8Array, o: number, ivt: number, shade: number, lut: ReturnType<typeof drapeLut>) {
  const q = Math.min(IVT_SCALE_MAX, Math.max(0, Math.round(ivt)));
  const k = lut.k[q]!;
  const g = drapeGray(shade) * 255;
  for (let c = 0; c < 3; c++)
    out[o + c] = Math.round((lut.neutral[c]! * (1 - k) + (lut.rgb[q * 3 + c]! / 255) * k) * g);
  out[o + 3] = 255;
}

/** Bilinear lookup precomputed once per relief + grid: the top-left node of each point's cell and its weights. */
export interface DrapeSampler {
  node: Int32Array;
  wx: Float32Array;
  wy: Float32Array;
  nx: number;
  ny: number;
}

/** Locate each relief point in the IVT grid (row 0 = south); points outside clamp to the nearest edge node. */
export function buildDrapeSampler(relief: ReliefData, grid: FrameGrid): DrapeSampler {
  const { nx, ny } = grid;
  const dlon = nx > 1 ? (grid.lon_max - grid.lon_min) / (nx - 1) : 0;
  const dlat = ny > 1 ? (grid.lat_max - grid.lat_min) / (ny - 1) : 0;
  const node = new Int32Array(relief.length);
  const wx = new Float32Array(relief.length);
  const wy = new Float32Array(relief.length);
  for (let i = 0; i < relief.length; i++) {
    const fx = dlon ? (relief.positions[i * STRIDE]! - grid.lon_min) / dlon : 0;
    const fy = dlat ? (relief.positions[i * STRIDE + 1]! - grid.lat_min) / dlat : 0;
    const cx = Math.min(Math.max(fx, 0), nx - 1);
    const cy = Math.min(Math.max(fy, 0), ny - 1);
    const x0 = Math.min(Math.floor(cx), Math.max(nx - 2, 0));
    const y0 = Math.min(Math.floor(cy), Math.max(ny - 2, 0));
    node[i] = y0 * nx + x0;
    wx[i] = cx - x0;
    wy[i] = cy - y0;
  }
  return { node, wx, wy, nx, ny };
}

const finite = (v: number | undefined) => (v == null || Number.isNaN(v) ? 0 : v);

/** IVT of frame `frame` at relief point `i` (bilinear; NaN nodes count as 0). */
export function sampleIvt(s: DrapeSampler, frames: Float32Array, frame: number, i: number): number {
  const base = frame * s.nx * s.ny;
  const n = base + s.node[i]!;
  const x1 = s.nx > 1 ? 1 : 0;
  const y1 = s.ny > 1 ? s.nx : 0;
  const a = finite(frames[n]);
  const b = finite(frames[n + x1]);
  const c = finite(frames[n + y1]);
  const d = finite(frames[n + y1 + x1]);
  const wx = s.wx[i]!;
  return (a * (1 - wx) + b * wx) * (1 - s.wy[i]!) + (c * (1 - wx) + d * wx) * s.wy[i]!;
}

/** RGBA per relief point for one frame: per frame only a weighted sum of 4 nodes and a LUT lookup (no allocations). */
export function drapeColors(
  relief: ReliefData,
  sampler: DrapeSampler,
  frames: Float32Array,
  frame: number,
  theme: Theme,
): Uint8Array {
  const lut = drapeLut(theme);
  const out = new Uint8Array(relief.length * 4);
  for (let i = 0; i < relief.length; i++)
    paintDrape(out, i * 4, sampleIvt(sampler, frames, frame, i), relief.shade[i]!, lut);
  return out;
}

/** Relief point cloud; `colors` (RGBA per point, e.g. the IVT drape) replaces the slate colors. */
export function buildReliefLayer(layerId: string, relief: ReliefData, theme: Theme = "light", colors?: Uint8Array) {
  return new PointCloudLayer({
    id: `relief-${layerId}`,
    data: {
      length: relief.length,
      attributes: {
        getPosition: { value: relief.positions, size: 3 },
        getColor: {
          value: colors ?? reliefColors(relief, theme),
          size: 4,
          normalized: true,
        },
      },
    },
    pickable: false,
    pointSize: 2,
    sizeUnits: "pixels",
  });
}

import { PointCloudLayer } from "@deck.gl/layers";
import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import type { LonLat } from "./referenceLayers";

/** Binary layout of relief.bin: little-endian Float32 [lon, lat, elev_m] per point. */
const STRIDE = 3;
/** Vertical exaggeration applied to elevation (m) so relief reads at province scale. */
export const RELIEF_EXAGGERATION = 3;
/** Grid step (degrees) of relief.bin when it cannot be inferred (relief.meta.json `step`). */
export const RELIEF_STEP = 0.005;
/** Elevation (m) of each `tokens.reliefRamp` stop (slate ramp): lowland, mid, high, peaks. */
export const RELIEF_STOPS_M = [0, 800, 1800, 3000] as const;
/** Hillshade: sun from the NW (azimuth clockwise from north) at 45 degrees; slopes exaggerated for shading only. */
export const SUN_AZIMUTH_DEG = 315;
export const SUN_ALTITUDE_DEG = 45;
export const SHADE_EXAGGERATION = 2.5;
const SHADE_MIN = 0.4;
const SHADE_MAX = 1.3;

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

/** Ray-casting point-in-polygon on an open or closed ring of [lon, lat]. */
export function pointInRing(lon: number, lat: number, ring: readonly LonLat[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
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
 * grid is rebuilt by index to compute the hillshade from neighbouring elevations; only then are points outside
 * `province` (when given; the province + 10 km ring, see provinceClip.ts) dropped.
 */
export function parseRelief(buffer: ArrayBuffer, province: readonly LonLat[] | null = null, step = RELIEF_STEP): ReliefData {
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

  const bbox = province && [
    Math.min(...province.map((p) => p[0])),
    Math.min(...province.map((p) => p[1])),
    Math.max(...province.map((p) => p[0])),
    Math.max(...province.map((p) => p[1])),
  ];
  const keep = new Uint8Array(n);
  let count = 0;
  for (let i = 0; i < n; i++) {
    const lon = src[i * STRIDE]!;
    const lat = src[i * STRIDE + 1]!;
    const ok =
      !province ||
      (lon >= bbox![0]! && lon <= bbox![2]! && lat >= bbox![1]! && lat <= bbox![3]! && pointInRing(lon, lat, province));
    keep[i] = ok ? 1 : 0;
    count += keep[i]!;
  }

  const positions = new Float32Array(count * STRIDE);
  const elevation = new Float32Array(count);
  const shade = new Float32Array(count);
  const mPerDegLat = 110_574;
  const mPerDegLon = 111_320;
  let o = 0;
  for (let i = 0; i < n; i++) {
    if (!keep[i]) continue;
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

export function buildReliefLayer(layerId: string, relief: ReliefData, theme: Theme = "light") {
  return new PointCloudLayer({
    id: `relief-${layerId}`,
    data: {
      length: relief.length,
      attributes: {
        getPosition: { value: relief.positions, size: 3 },
        getColor: { value: reliefColors(relief, theme), size: 4, normalized: true },
      },
    },
    pickable: false,
    pointSize: 2,
    sizeUnits: "pixels",
  });
}

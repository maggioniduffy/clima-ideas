import type { ArEvent, FrameGrid } from "../api/client";
import { tokens } from "../theme/tokens";

/** |IVT| (kg m-1 s-1) at which the color ramp saturates; fixed so events compare across replays. */
export const IVT_SCALE_MAX = 800;
const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];
const LOW = hex(tokens.brand.secondary);
const HIGH = hex(tokens.brand.accent);

export type Rgba = [number, number, number, number];

/** Ramp secondary -> accent over [0, IVT_SCALE_MAX]; null/NaN is transparent. Opaque unless `fade`. */
export function ivtColor(value: number | null | undefined, fade = false): Rgba {
  if (value == null || Number.isNaN(value)) return [0, 0, 0, 0];
  const t = Math.min(1, Math.max(0, value / IVT_SCALE_MAX));
  const [r, g, b] = [0, 1, 2].map((i) => Math.round(LOW[i]! + (HIGH[i]! - LOW[i]!) * t));
  return [r!, g!, b!, fade ? Math.round(255 * (0.25 + 0.7 * t)) : 255];
}

export const rgbCss = ([r, g, b]: Rgba) => `rgb(${r}, ${g}, ${b})`;

/** Decode a frames `.bin` (little-endian Float32 [n, ny, nx]); throws when the size does not match. */
export function parseFrames(buffer: ArrayBuffer, grid: FrameGrid, nFrames: number): Float32Array {
  const expected = nFrames * grid.ny * grid.nx * 4;
  if (buffer.byteLength !== expected) throw new Error(`frames: expected ${expected} bytes, got ${buffer.byteLength}`);
  return new Float32Array(buffer);
}

/** IVT of frame `k` at grid cell (row, col); null for NaN or out-of-range indices. */
export function frameValue(frames: Float32Array, grid: FrameGrid, k: number, row: number, col: number): number | null {
  if (row < 0 || row >= grid.ny || col < 0 || col >= grid.nx || k < 0) return null;
  const v = frames[(k * grid.ny + row) * grid.nx + col];
  return v == null || Number.isNaN(v) ? null : v;
}

export interface Cell {
  row: number;
  col: number;
  lon: number;
  lat: number;
  /** Closed-ring-free rectangle around the cell center, [lon, lat] per vertex. */
  polygon: [number, number][];
}

/** One rectangle per grid point, half a step to each side (pitch 0 for degenerate axes). */
export function gridCells(grid: FrameGrid): Cell[] {
  const dlat = grid.ny > 1 ? (grid.lat_max - grid.lat_min) / (grid.ny - 1) : 0;
  const dlon = grid.nx > 1 ? (grid.lon_max - grid.lon_min) / (grid.nx - 1) : 0;
  const cells: Cell[] = [];
  for (let row = 0; row < grid.ny; row++) {
    for (let col = 0; col < grid.nx; col++) {
      const lat = grid.lat_min + row * dlat;
      const lon = grid.lon_min + col * dlon;
      const [w, e, s, n] = [lon - dlon / 2, lon + dlon / 2, lat - dlat / 2, lat + dlat / 2];
      cells.push({
        row,
        col,
        lon,
        lat,
        polygon: [
          [w, s],
          [e, s],
          [e, n],
          [w, n],
        ],
      });
    }
  }
  return cells;
}

export const parseTime = (iso: string) => Date.parse(iso);

/** Valid time (ms since epoch) of frame `k`. */
export const frameTime = (startIso: string, k: number, stepHours = 1) => parseTime(startIso) + k * stepHours * HOUR_MS;

/** "YYYY-MM-DD/YYYY-MM-DD" (manifest period) -> [start ms, end ms), end day inclusive. */
export function periodDomain(period: string): [number, number] | null {
  const m = /^(\d{4}-\d{2}-\d{2})\/(\d{4}-\d{2}-\d{2})$/.exec(period);
  if (!m) return null;
  const lo = Date.parse(`${m[1]}T00:00:00Z`);
  const hi = Date.parse(`${m[2]}T00:00:00Z`) + DAY_MS;
  return Number.isNaN(lo) || Number.isNaN(hi) || hi <= lo ? null : [lo, hi];
}

export interface EventSpan {
  id: string;
  /** Fractions of the domain, clamped to [0, 1]. */
  left: number;
  width: number;
  color: string;
}

/** Position and IVT-max color of every event on a timeline with the given domain. */
export function eventSpans(events: ArEvent[], domain: [number, number]): EventSpan[] {
  const [lo, hi] = domain;
  const span = hi - lo;
  return events.map((e) => {
    const a = Math.min(1, Math.max(0, (parseTime(e.start) - lo) / span));
    const b = Math.min(1, Math.max(0, (parseTime(e.end) - lo) / span));
    return { id: e.event_id, left: a, width: Math.max(0, b - a), color: rgbCss(ivtColor(e.ivt_max)) };
  });
}

/** Fraction of [lo, hi] where `ms` falls, clamped. */
export const fractionOf = (ms: number, [lo, hi]: [number, number]) => Math.min(1, Math.max(0, (ms - lo) / (hi - lo)));

/** [start, end) of an event in ms. */
export const eventDomain = (e: ArEvent): [number, number] => [parseTime(e.start), parseTime(e.end)];

/** "2000-03-10 06:00 UTC" */
export const formatUtc = (ms: number) => `${new Date(ms).toISOString().slice(0, 16).replace("T", " ")} UTC`;

import type { FootprintsIndex } from "../api/client";
import { IVT_CONTOUR_LEVELS } from "./ivtContours";

/** |IVT| (kg m-1 s-1) from which a cell counts as reached by an AR: the project's IVT baseline. */
export const AR_IVT_THRESHOLD = 250;

export interface Footprints {
  /** Float32 `[n_events, ny, nx]`, row 0 = south, column 0 = west (same grid as the frames). */
  data: Float32Array;
  /** Event ids in storage order. */
  order: string[];
  ny: number;
  nx: number;
}

/** Decode `frames/footprints.bin`; throws when the byte size does not match the index shape. */
export function parseFootprints(buffer: ArrayBuffer, meta: Pick<FootprintsIndex, "events" | "shape">): Footprints {
  const [n, ny, nx] = meta.shape;
  const expected = n * ny * nx * 4;
  if (n !== meta.events.length || buffer.byteLength !== expected)
    throw new Error(`footprints: expected ${expected} bytes for ${meta.events.length} events, got ${buffer.byteLength}`);
  return { data: new Float32Array(buffer), order: meta.events, ny, nx };
}

/** Max |IVT| per cell of one event (a view into the data, `[ny * nx]`); null for an unknown id. */
export function footprintOf(fp: Footprints, eventId: string): Float32Array | null {
  const i = fp.order.indexOf(eventId);
  const size = fp.ny * fp.nx;
  return i < 0 ? null : fp.data.subarray(i * size, (i + 1) * size);
}

/** Per cell: how many of `eventIds` reached `threshold` (>=). NaN never counts; ids without a footprint are skipped. */
export function countReaching(fp: Footprints, eventIds: readonly string[], threshold = AR_IVT_THRESHOLD): Uint16Array {
  const counts = new Uint16Array(fp.ny * fp.nx);
  for (const id of eventIds) {
    const f = footprintOf(fp, id);
    if (f) for (let k = 0; k < counts.length; k++) if (f[k]! >= threshold) counts[k]!++;
  }
  return counts;
}

/** Highest of the isoline levels (250/500/750/1000) that the footprint reaches; null below the lowest. */
export function coreLevel(footprint: Float32Array): number | null {
  let max = -Infinity;
  for (const v of footprint) if (v > max) max = v;
  const reached = IVT_CONTOUR_LEVELS.filter((l) => max >= l);
  return reached.length ? reached[reached.length - 1]! : null;
}

import { PointCloudLayer } from "@deck.gl/layers";
import { tokens } from "../theme/tokens";

/** Binary layout of relief.bin: little-endian Float32 [lon, lat, elev_m] per point. */
const STRIDE = 3;
/** Vertical exaggeration applied to elevation (m) so relief reads at province scale. */
export const RELIEF_EXAGGERATION = 3;

export interface ReliefData {
  length: number;
  /** Interleaved lon, lat, z (m × exaggeration). */
  positions: Float32Array;
  /** RGBA, 4 bytes per point. */
  colors: Uint8Array;
}

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];

const LOW = hex(tokens.brand.secondary);
const HIGH = hex(tokens.brand.accent);

/** Ramp from lowlands (secondary) to peaks (accent); t in [0, 1]. Works on both themes. */
export function reliefColor(t: number): [number, number, number] {
  const k = Math.min(1, Math.max(0, t));
  return [0, 1, 2].map((i) => Math.round(LOW[i]! + (HIGH[i]! - LOW[i]!) * k)) as [number, number, number];
}

export function parseRelief(buffer: ArrayBuffer): ReliefData {
  if (buffer.byteLength % (STRIDE * 4) !== 0) throw new Error("relief.bin: size is not a multiple of the stride");
  const src = new Float32Array(buffer);
  const length = src.length / STRIDE;
  const positions = new Float32Array(src.length);
  const colors = new Uint8Array(length * 4);
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < length; i++) {
    const e = src[i * STRIDE + 2]!;
    if (e < lo) lo = e;
    if (e > hi) hi = e;
  }
  const span = hi - lo || 1;
  for (let i = 0; i < length; i++) {
    const elev = src[i * STRIDE + 2]!;
    positions[i * STRIDE] = src[i * STRIDE]!;
    positions[i * STRIDE + 1] = src[i * STRIDE + 1]!;
    positions[i * STRIDE + 2] = elev * RELIEF_EXAGGERATION;
    const [r, g, b] = reliefColor((elev - lo) / span);
    colors[i * 4] = r;
    colors[i * 4 + 1] = g;
    colors[i * 4 + 2] = b;
    colors[i * 4 + 3] = 255;
  }
  return { length, positions, colors };
}

export function buildReliefLayer(layerId: string, relief: ReliefData) {
  return new PointCloudLayer({
    id: `relief-${layerId}`,
    data: {
      length: relief.length,
      attributes: {
        getPosition: { value: relief.positions, size: 3 },
        getColor: { value: relief.colors, size: 4, normalized: true },
      },
    },
    pickable: false,
    pointSize: 2,
    sizeUnits: "pixels",
  });
}

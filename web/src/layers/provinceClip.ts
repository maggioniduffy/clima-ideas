import { useEffect, useState } from "react";
import type { Cell } from "./arEvents";
import { parseRing, type LonLat } from "./referenceLayers";

/**
 * Province outline + 10 km band: the IVT raster and the relief are shown only inside it. Derived from the Natural Earth
 * outline by scripts/buffer_province.py (see public/geo/README.md).
 */
export const CLIP_URL = "/geo/neuquen-province-buffer-10km.geojson";

let cached: Promise<LonLat[] | null> | null = null;

/** Buffered outer ring; null when it cannot be fetched (layers then show unclipped). Fetched once per page load. */
export function fetchClipRing(): Promise<LonLat[] | null> {
  cached ??= fetch(CLIP_URL)
    .then((r) => (r.ok ? r.json() : null))
    .then(parseRing)
    .catch(() => null);
  return cached;
}

/** undefined while loading, null if unavailable, else the ring. */
export function useClipRing(enabled: boolean): LonLat[] | null | undefined {
  const [ring, setRing] = useState<LonLat[] | null | undefined>(undefined);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void fetchClipRing().then((r) => !cancelled && setRing(r));
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return ring;
}

type Pt = [number, number];

function clipEdge(ring: Pt[], inside: (p: Pt) => boolean, cut: (a: Pt, b: Pt) => Pt): Pt[] {
  const out: Pt[] = [];
  ring.forEach((cur, i) => {
    const prev = ring[(i + ring.length - 1) % ring.length]!;
    if (inside(cur)) {
      if (!inside(prev)) out.push(cut(prev, cur));
      out.push(cur);
    } else if (inside(prev)) out.push(cut(prev, cur));
  });
  return out;
}

/**
 * `ring` ∩ axis-aligned rectangle [w, e] x [s, n] (Sutherland-Hodgman; exact for a convex clip window, also with a
 * non-convex subject: separate parts would be joined by zero-width bridges along the window edge, invisible when filled).
 * Empty when nothing remains.
 */
export function clipRingToRect(ring: readonly LonLat[], w: number, e: number, s: number, n: number): Pt[] {
  let pts: Pt[] = ring.map((p) => [p[0], p[1]]);
  if (pts.length > 1 && pts[0]![0] === pts.at(-1)![0] && pts[0]![1] === pts.at(-1)![1]) pts = pts.slice(0, -1);
  const atX = (x: number) => (a: Pt, b: Pt): Pt => [x, a[1] + ((x - a[0]) * (b[1] - a[1])) / (b[0] - a[0])];
  const atY = (y: number) => (a: Pt, b: Pt): Pt => [a[0] + ((y - a[1]) * (b[0] - a[0])) / (b[1] - a[1]), y];
  const steps: [(p: Pt) => boolean, (a: Pt, b: Pt) => Pt][] = [
    [(p) => p[0] >= w, atX(w)],
    [(p) => p[0] <= e, atX(e)],
    [(p) => p[1] >= s, atY(s)],
    [(p) => p[1] <= n, atY(n)],
  ];
  for (const [inside, cut] of steps) {
    if (!pts.length) break;
    pts = clipEdge(pts, inside, cut);
  }
  return pts.length >= 3 ? pts : [];
}

/**
 * Cells clipped to the ring: each rectangle is intersected with it (clean edge, not just dropped by its center); cells
 * entirely outside are removed. Row/col are kept, so picking and readings still index the full grid.
 */
export function clipCells(cells: readonly Cell[], ring: readonly LonLat[]): Cell[] {
  const out: Cell[] = [];
  for (const c of cells) {
    const xs = c.polygon.map((p) => p[0]);
    const ys = c.polygon.map((p) => p[1]);
    const polygon = clipRingToRect(ring, Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys));
    if (polygon.length) out.push({ ...c, polygon });
  }
  return out;
}

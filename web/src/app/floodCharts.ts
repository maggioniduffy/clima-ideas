/** Pure chart math for the flood panel: scales, ticks, downsampling and SVG path building. */

export interface Pt {
  x: number;
  y: number;
}

/** Return periods (years) labelled on the log axis. */
export const RETURN_TICKS = [2, 5, 10, 25, 50, 100, 200] as const;
/** Most points the daily series draws; each bucket keeps its maximum so peaks survive. */
export const MAX_SERIES_POINTS = 2000;

const DAY_MS = 86_400_000;

export const linearScale =
  (d0: number, d1: number, r0: number, r1: number) =>
  (v: number): number =>
    d1 === d0 ? r0 : r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);

export const logScale = (d0: number, d1: number, r0: number, r1: number) => {
  const lin = linearScale(Math.log(d0), Math.log(d1), r0, r1);
  return (v: number): number => lin(Math.log(v));
};

/** Smallest "nice" value (1, 2, 2.5, 5 times a power of ten) that is >= v; 1 for v <= 0. */
export function niceMax(v: number): number {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v * (1 - 1e-9)) return m * p;
  return 10 * p;
}

/** `n + 1` evenly spaced ticks from 0 to `max`. */
export const linearTicks = (max: number, n: number): number[] => Array.from({ length: n + 1 }, (_, i) => (max * i) / n);

/** Whole days from ISO date `a` to ISO date `b` (UTC). */
export const dayOffset = (a: string, b: string): number => Math.round((Date.parse(b) - Date.parse(a)) / DAY_MS);

export const isoAddDays = (iso: string, days: number): string =>
  new Date(Date.parse(iso) + days * DAY_MS).toISOString().slice(0, 10);

/** dd/mm/aaaa from an ISO `YYYY-MM-DD` date. */
export const formatDateEs = (iso: string): string => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;

export interface Bucket {
  /** Index in the original array of the bucket's maximum (or first element when the bucket is all gaps). */
  index: number;
  /** Maximum of the bucket; null when every value in it is a gap. */
  value: number | null;
}

/** At most `maxPoints` buckets of consecutive samples; each keeps its maximum (and where it is). */
export function downsampleMax(values: readonly (number | null)[], maxPoints = MAX_SERIES_POINTS): Bucket[] {
  const n = values.length;
  const size = Math.max(1, Math.ceil(n / maxPoints));
  const out: Bucket[] = [];
  for (let start = 0; start < n; start += size) {
    let best = -1;
    for (let i = start; i < Math.min(n, start + size); i++) {
      const v = values[i];
      if (v != null && (best < 0 || v > (values[best] as number))) best = i;
    }
    out.push(best < 0 ? { index: start, value: null } : { index: best, value: values[best] as number });
  }
  return out;
}

const fix = (n: number) => (Math.round(n * 10) / 10).toString();

/** SVG path through the points; a null starts a new subpath (a break in the line). */
export function linePath(points: readonly (Pt | null)[]): string {
  let d = "";
  let pen = false;
  for (const p of points) {
    if (!p) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${fix(p.x)} ${fix(p.y)}`;
    pen = true;
  }
  return d;
}

/** Closed polygon between an upper and a lower edge (both left to right). */
export function bandPath(upper: readonly Pt[], lower: readonly Pt[]): string {
  if (upper.length === 0 || lower.length === 0) return "";
  const pts = [...upper, ...[...lower].reverse()];
  return `${pts.map((p, i) => `${i === 0 ? "M" : "L"}${fix(p.x)} ${fix(p.y)}`).join("")}Z`;
}

/** Year labels for a daily series: up to `n` evenly spaced calendar years inside [start, end]. */
export function yearTicks(start: string, end: string, n = 4): { year: number; iso: string }[] {
  const y0 = Number(start.slice(0, 4));
  const y1 = Number(end.slice(0, 4));
  const first = y0 + (start > `${y0}-01-01` ? 1 : 0);
  if (first > y1) return [];
  const step = Math.max(1, Math.ceil((y1 - first) / n / 5) * 5);
  const out: { year: number; iso: string }[] = [];
  for (let y = Math.ceil(first / step) * step; y <= y1; y += step) {
    const iso = `${y}-01-01`;
    if (iso >= start && iso <= end) out.push({ year: y, iso });
  }
  return out;
}

/** Pure chart math for the flood panel: scales, ticks, downsampling and SVG path building. */
import type { FloodEvent, FloodEventIssue } from "../layers/useFloodStation";

export interface Pt {
  x: number;
  y: number;
}

/** Return periods (years) labelled on the log axis. */
export const RETURN_TICKS = [2, 5, 10, 25, 50, 100, 200] as const;
/** Most points the daily series draws; each bucket keeps its maximum so peaks survive. */
export const MAX_SERIES_POINTS = 2000;

const DAY_MS = 86_400_000;

/** Plot-area margins in CSS px (the charts draw in a viewBox of the measured width, so text never scales). */
export const CHART_MARGIN = { l: 48, r: 18, t: 24, b: 30 } as const;
/** Width of one glyph of the 12 px mono tick font, for fitting labels. */
export const TICK_CHAR_PX = 7.3;

/** Anchor of a tick label at `x` so the whole label stays inside [0, width]: centred unless it would clip. */
export function tickAnchor(x: number, width: number, label: string): "start" | "middle" | "end" {
  const half = (label.length * TICK_CHAR_PX) / 2;
  if (x - half < 1) return "start";
  if (x + half > width - 1) return "end";
  return "middle";
}

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

export interface ForecastPoint {
  /** Days from the start of the observed series. */
  day: number;
  median: number | null;
  lo: number | null;
  hi: number | null;
}

/** Forecast of one issue day as points on the event's day axis: lead k falls k days after the issue day. */
export function forecastPoints(obsStart: string, issue: FloodEventIssue): ForecastPoint[] {
  const base = dayOffset(obsStart, issue.issue_date);
  return issue.median.map((m, k) => ({
    day: base + k + 1,
    median: m,
    lo: issue.lo[k] ?? null,
    hi: issue.hi[k] ?? null,
  }));
}

/** Persistence forecast: the flow observed on the issue day, held for every lead (empty when it is a gap). */
export function persistencePoints(obsStart: string, issue: FloodEventIssue): Pt[] {
  if (issue.persistence == null) return [];
  const base = dayOffset(obsStart, issue.issue_date);
  return [{ x: base, y: issue.persistence }, ...issue.median.map((_, k) => ({ x: base + k + 1, y: issue.persistence! }))];
}

/** Largest flow the event's chart can show (observed, every issue's band), so the y axis stays put between issue days. */
export function eventYMax(event: FloodEvent): number {
  const vals = [
    ...event.obs.q,
    ...event.issues.flatMap((i) => [...i.hi, ...i.median, i.persistence]),
  ].filter((v): v is number => v != null);
  return niceMax(Math.max(0, ...vals));
}

/** "Emitido N días antes del pico" label of an issue day. */
export function issueLabel(daysBeforePeak: number): string {
  if (daysBeforePeak <= 0) return "Emitido el día del pico";
  return `Emitido ${daysBeforePeak} ${daysBeforePeak === 1 ? "día" : "días"} antes del pico`;
}

/** Band polygon of the forecast: only leads where both edges exist, joined in order. */
export function forecastBandPath(points: readonly ForecastPoint[], x: (d: number) => number, y: (v: number) => number): string {
  const ok = points.filter((p) => p.lo != null && p.hi != null);
  if (ok.length < 2) return "";
  return bandPath(
    ok.map((p): Pt => ({ x: x(p.day), y: y(p.hi!) })),
    ok.map((p): Pt => ({ x: x(p.day), y: y(p.lo!) })),
  );
}

/** dd/mm from an ISO `YYYY-MM-DD` date (short tick label). */
export const formatDayMonth = (iso: string): string => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

export interface ResponseChartInput {
  /** Daily flow series of the station: `start` ISO date, one value per day. */
  daily: { start: string; q: readonly (number | null)[] };
  /** First and last day (UTC ISO dates) of the AR event. */
  eventStart: string;
  eventEnd: string;
  /** Days after the last event day that the response window covers. */
  windowDaysAfter: number;
  /** Height of the chart in px (the width is the measured one). */
  width: number;
  height: number;
}

export interface ResponseChartGeometry {
  yMax: number;
  yTicks: number[];
  /** Path of the daily flow; gaps break the line. */
  path: string;
  /** Shaded AR window: from the left edge of the first event day to the right edge of the last one (px). */
  shade: { x0: number; x1: number };
  /** x of the end of the response window (end of its last day), clipped to the plot area. */
  windowEndX: number;
  /** Date labels along the x axis. */
  xTicks: { x: number; label: string }[];
  /** Pixel position of day `i` of the series. */
  x: (i: number) => number;
  y: (v: number) => number;
}

/**
 * Geometry of a station's caudal chart around an event: days on x (each day owns one band, points sit at its centre),
 * flow from 0 on y, the AR window shaded and the end of the response window marked. Pure: the component only draws.
 */
export function responseChartGeometry(inp: ResponseChartInput): ResponseChartGeometry {
  const { daily, eventStart, eventEnd, windowDaysAfter, width, height } = inp;
  const n = Math.max(daily.q.length, 1);
  const left = CHART_MARGIN.l;
  const right = width - CHART_MARGIN.r;
  const top = CHART_MARGIN.t;
  const bottom = height - CHART_MARGIN.b;
  const x = linearScale(-0.5, n - 0.5, left, right);
  const yMax = niceMax(Math.max(0, ...daily.q.map((v) => v ?? 0)));
  const y = linearScale(0, yMax, bottom, top);
  const first = dayOffset(daily.start, eventStart.slice(0, 10));
  const last = dayOffset(daily.start, eventEnd.slice(0, 10));
  const clip = (px: number) => Math.min(right, Math.max(left, px));
  const tickIdx = daily.q.length === 0 ? [] : n <= 2 ? [...Array(n).keys()] : [0, Math.floor((n - 1) / 2), n - 1];
  return {
    yMax,
    yTicks: linearTicks(yMax, 2),
    path: linePath(daily.q.map((v, i) => (v == null ? null : { x: x(i), y: y(v) }))),
    shade: { x0: clip(x(first - 0.5)), x1: clip(x(last + 0.5)) },
    windowEndX: clip(x(last + windowDaysAfter + 0.5)),
    xTicks: tickIdx.map((i) => ({ x: x(i), label: formatDayMonth(isoAddDays(daily.start, i)) })),
    x,
    y,
  };
}

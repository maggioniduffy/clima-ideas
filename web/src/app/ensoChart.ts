/** Pure geometry of the ENSO strip plot: one dot per season-year, grouped in three phase columns. */
import { linearScale, linearTicks, niceMax } from "./floodCharts";

export const STRIP_PHASES = ["nino", "neutral", "nina"] as const;
export type StripPhase = (typeof STRIP_PHASES)[number];

export interface StripInput {
  year: number;
  phase: string | null;
  value: number | null;
}

export interface StripSize {
  width: number;
  height: number;
  margin: { top: number; right: number; bottom: number; left: number };
}

export interface StripDot {
  year: number;
  phase: StripPhase;
  value: number;
  x: number;
  y: number;
}

export interface StripColumn {
  phase: StripPhase;
  cx: number;
  halfWidth: number;
}

export interface StripMean {
  phase: StripPhase;
  value: number;
  y: number;
  x1: number;
  x2: number;
}

export interface StripLayout {
  dots: StripDot[];
  columns: StripColumn[];
  means: StripMean[];
  ticks: { value: number; y: number }[];
}

const isPhase = (p: string | null): p is StripPhase => !!p && (STRIP_PHASES as readonly string[]).includes(p);

/** Deterministic pseudo-random offset in [-1, 1] from the year, so dots do not move between renders. */
export function jitter(year: number): number {
  const x = Math.sin(year * 12.9898) * 43758.5453;
  return (x - Math.floor(x)) * 2 - 1;
}

/** Mean of the non-null values of each phase; null for a phase without values. */
export function phaseMeans(data: StripInput[]): Record<StripPhase, number | null> {
  const out = {} as Record<StripPhase, number | null>;
  for (const p of STRIP_PHASES) {
    const v = data.filter((d) => d.phase === p && d.value != null).map((d) => d.value as number);
    out[p] = v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  }
  return out;
}

/** Positions of the dots, phase columns, mean ticks and y ticks (0 to a nice max) inside the plot area. */
export function buildStrip(data: StripInput[], size: StripSize, tickCount = 4): StripLayout {
  const { width, height, margin } = size;
  const plotW = width - margin.left - margin.right;
  const colW = plotW / STRIP_PHASES.length;
  const halfWidth = colW * 0.36;
  const kept = data.filter((d): d is StripInput & { phase: StripPhase; value: number } => isPhase(d.phase) && d.value != null);
  const max = niceMax(Math.max(0, ...kept.map((d) => d.value)));
  const y = linearScale(0, max, height - margin.bottom, margin.top);
  const columns = STRIP_PHASES.map((phase, i) => ({ phase, cx: margin.left + colW * (i + 0.5), halfWidth }));
  const cx = (p: StripPhase) => columns.find((c) => c.phase === p)!.cx;
  const dots = kept.map((d) => ({
    year: d.year,
    phase: d.phase,
    value: d.value,
    x: cx(d.phase) + jitter(d.year) * halfWidth,
    y: y(d.value),
  }));
  const means: StripMean[] = [];
  for (const [phase, value] of Object.entries(phaseMeans(kept)) as [StripPhase, number | null][])
    if (value != null) means.push({ phase, value, y: y(value), x1: cx(phase) - halfWidth, x2: cx(phase) + halfWidth });
  return { dots, columns, means, ticks: linearTicks(max, tickCount).map((value) => ({ value, y: y(value) })) };
}

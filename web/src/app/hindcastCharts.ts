/** Pure chart math of the hindcast panel (forecast against observed, skill curve). Scales come from floodCharts. */
import type { HindcastEvent, SkillPoint } from "../layers/hindcast";
import { bandPath, linePath, linearScale, type Pt } from "./floodCharts";

export interface Ticks {
  lo: number;
  hi: number;
  ticks: number[];
}

/** Ticks at 1, 2, 2.5 or 5 times a power of ten covering [min, max] (about `target` intervals). */
export function niceTicks(min: number, max: number, target = 5): Ticks {
  const span = max > min ? max - min : Math.abs(max) || 1;
  const raw = span / target;
  const p = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * p >= raw * (1 - 1e-9)) ?? 10) * p;
  const lo = Math.floor(min / step + 1e-9) * step;
  const hi = Math.max(Math.ceil(max / step - 1e-9) * step, lo + step);
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step * 1e-6; v += step) ticks.push(Number(v.toPrecision(10)));
  return { lo: Number(lo.toPrecision(10)), hi: Number(hi.toPrecision(10)), ticks };
}

const finite = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);

/** Y axis of the forecast chart: from 0 up to the largest of the ensemble maximum, mean and observed value. */
export function forecastDomain(ev: HindcastEvent): Ticks {
  const vals = [ev.obs_mm, ...ev.mean, ...ev.max].filter(finite);
  return niceTicks(0, Math.max(...vals, 1));
}

/** Y axis of the skill chart: from the lowest interval end (or 0) up to 1, the best possible CRPSS. */
export function skillDomain(points: readonly SkillPoint[]): Ticks {
  const lows = points.flatMap((p) => [p.value, p.lo]).filter(finite);
  return niceTicks(Math.min(0, ...lows), 1, 4);
}

export interface Scales {
  x: (lead: number) => number;
  y: (v: number) => number;
}

export const makeScales = (leads: readonly number[], dom: Ticks, w: number, h: number, m: { l: number; r: number; t: number; b: number }): Scales => ({
  x: linearScale(leads[0]!, leads[leads.length - 1]!, m.l, w - m.r),
  y: linearScale(dom.lo, dom.hi, h - m.b, m.t),
});

/** One point per lead; `null` where the value is missing, so `linePath` leaves a gap. */
export const seriesPoints = (leads: readonly number[], values: readonly (number | null | undefined)[], s: Scales): (Pt | null)[] =>
  leads.map((lead, i) => {
    const v = values[i];
    return finite(v) ? { x: s.x(lead), y: s.y(v) } : null;
  });

/** Band between `lo` and `hi` over the leads where both exist. */
export function bandBetween(leads: readonly number[], lo: readonly (number | null | undefined)[], hi: readonly (number | null | undefined)[], s: Scales): string {
  const idx = leads.map((_, i) => i).filter((i) => finite(lo[i]) && finite(hi[i]));
  return bandPath(
    idx.map((i) => ({ x: s.x(leads[i]!), y: s.y(hi[i]!) })),
    idx.map((i) => ({ x: s.x(leads[i]!), y: s.y(lo[i]!) })),
  );
}

export { linePath };

/** Skill values aligned to `leads` (null where the lead has no record). */
export const skillByLead = (points: readonly SkillPoint[], leads: readonly number[], key: "value" | "lo" | "hi"): (number | null)[] =>
  leads.map((l) => points.find((p) => p.lead === l)?.[key] ?? null);

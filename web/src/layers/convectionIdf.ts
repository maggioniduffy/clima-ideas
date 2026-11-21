import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import type { Rgba } from "./arEvents";

/** Layer id published by `python -m clima_nqn.layers.convection_idf` (backend `layers/convection_idf.py`). */
export const CONVECTION_LAYER_ID = "convection-idf";

/** One IDF value: duration `d` (h), return period `t` (years); CI 90 % bootstrap; `extrapolated` = T > 2 x years. */
export interface IdfRow {
  d: number;
  t: number;
  depth_mm: number | null;
  intensity_mm_h: number | null;
  depth_lo: number | null;
  depth_hi: number | null;
  intensity_lo: number | null;
  intensity_hi: number | null;
  extrapolated: boolean;
}

export interface IdfScenario {
  id: string;
  label: string;
  /** Annual maxima were divided by this factor before fitting; null for the main curve. */
  factor: number | null;
  note: string;
  gev: IdfRow[];
  /** Baseline; only in the main scenario. */
  gumbel?: IdfRow[];
}

/** `idf.json`. */
export interface IdfData {
  label: string;
  source: string;
  doi: string;
  license: string;
  /** Hydrological years used, e.g. "2000/01–2024/25 (años julio–junio)". */
  period: string;
  n_years: number;
  fit: string;
  ci_level: number;
  n_boot: number;
  extrapolation_above_t: number;
  cell: { lat: number; lon: number };
  target: { name: string; lat: number; lon: number };
  durations_h: number[];
  return_periods: number[];
  scenarios: IdfScenario[];
}

/** `replay.json`. */
export interface ReplayData {
  event: { id: string; name: string; start: string; end: string; step_minutes: number; n_frames: number };
  source: string;
  doi: string;
  units: string;
  cell: { lat: number; lon: number; row: number; col: number };
  compare: {
    start: string;
    end: string;
    window: string;
    imerg_mm: number;
    station: {
      name: string;
      id: string;
      lat: number;
      lon: number;
      value_mm: number;
      source: string;
      note: string;
    };
  };
  /** IMERG cumulative (mm) at the cell: `mm[k]` at `start + k * step_minutes`, 0 at k = 0. */
  cumulative: { start: string; step_minutes: number; mm: number[] };
}

export type IdfMetric = "intensity" | "depth";

export const metricValue = (r: IdfRow, m: IdfMetric) => (m === "intensity" ? r.intensity_mm_h : r.depth_mm);
export const metricLo = (r: IdfRow, m: IdfMetric) => (m === "intensity" ? r.intensity_lo : r.depth_lo);
export const metricHi = (r: IdfRow, m: IdfMetric) => (m === "intensity" ? r.intensity_hi : r.depth_hi);

/** Rows of one return period, shortest duration first. */
export const curveFor = (rows: readonly IdfRow[], t: number): IdfRow[] =>
  rows.filter((r) => r.t === t).sort((a, b) => a.d - b.d);

/**
 * Rain-rate thresholds (mm/h) of the five color stops (`tokens.rainRamp`): piecewise linear between them so light rain
 * stays readable; the legend spaces them evenly and the last one saturates ("≥20").
 */
export const RAIN_STOPS_MMH = [0, 1, 3, 8, 20] as const;
/** Below this rate (mm/h) a cell is fully transparent; alpha reaches RAIN_ALPHA_MAX at RAIN_ALPHA_FULL. */
export const RAIN_ALPHA_LOW = 0.1;
export const RAIN_ALPHA_FULL = 0.5;
export const RAIN_ALPHA_MAX = 0.9;

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];

/** Alpha 0..RAIN_ALPHA_MAX of a rain rate: 0 up to RAIN_ALPHA_LOW, smoothstep up to RAIN_ALPHA_MAX at RAIN_ALPHA_FULL. */
export function rainAlpha(v: number): number {
  const t = Math.min(1, Math.max(0, (v - RAIN_ALPHA_LOW) / (RAIN_ALPHA_FULL - RAIN_ALPHA_LOW)));
  return RAIN_ALPHA_MAX * t * t * (3 - 2 * t);
}

/** Neutral sequential blue ramp over `RAIN_STOPS_MMH`; null/NaN or a dry cell is transparent. */
export function rainColor(value: number | null | undefined, theme: Theme): Rgba {
  if (value == null || Number.isNaN(value) || value < RAIN_ALPHA_LOW) return [0, 0, 0, 0];
  const colors = tokens.rainRamp[theme].map(hex);
  const v = Math.min(value, RAIN_STOPS_MMH[RAIN_STOPS_MMH.length - 1]!);
  let i = RAIN_STOPS_MMH.findIndex((s, k) => v >= s && v <= RAIN_STOPS_MMH[k + 1]!);
  if (i < 0) i = RAIN_STOPS_MMH.length - 2;
  const f = (v - RAIN_STOPS_MMH[i]!) / (RAIN_STOPS_MMH[i + 1]! - RAIN_STOPS_MMH[i]!);
  const [r, g, b] = [0, 1, 2].map((c) => Math.round(colors[i]![c]! + (colors[i + 1]![c]! - colors[i]![c]!) * f));
  return [r!, g!, b!, Math.round(255 * rainAlpha(value))];
}

/** Legend ticks of the rain ramp: evenly spaced, the last reads "≥20". */
export const rainLegendTicks = () =>
  RAIN_STOPS_MMH.map((v, i) => ({
    value: v,
    fraction: i / (RAIN_STOPS_MMH.length - 1),
    label: i === RAIN_STOPS_MMH.length - 1 ? `≥${v}` : String(v),
  }));

/** Cumulative IMERG (mm) at the replay time `ms`; null before the comparison window starts or past the series. */
export function cumulativeAt(c: ReplayData["cumulative"], ms: number): number | null {
  const k = (ms - Date.parse(c.start)) / (c.step_minutes * 60_000);
  if (k < 0 || k > c.mm.length - 1) return null;
  const k0 = Math.floor(k);
  const a = c.mm[k0]!;
  const b = c.mm[Math.min(k0 + 1, c.mm.length - 1)]!;
  return a + (b - a) * (k - k0);
}

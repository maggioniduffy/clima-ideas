/** Layer ids published by `clima-nqn hindcast verification-layer` and `hindcast analogs-layer` (backend `layers/`). */
export const HINDCAST_LAYER_ID = "hindcast-verification";
export const ANALOGS_LAYER_ID = "hindcast-analogs";

/** One F1.3 event of a model: ERA5 box mean of the valid day and the ensemble mean/min/max by lead (mm/day, `null` = not published). */
export interface HindcastEvent {
  event_id: string;
  /** Valid day (UTC) of the event, `YYYY-MM-DD`. */
  date: string;
  obs_mm: number;
  mean: (number | null)[];
  min: (number | null)[];
  max: (number | null)[];
}

export interface HindcastModelCases {
  label: string;
  source: string;
  license: string;
  period: string;
  n_members: number;
  events: HindcastEvent[];
}

/** `cases.json`. */
export interface HindcastCases {
  id: string;
  title: string;
  source: string;
  license: string;
  period: string;
  obs_source: string;
  units: string;
  leads: number[];
  models: Record<string, HindcastModelCases>;
}

export interface SkillPoint {
  lead: number;
  value: number | null;
  lo: number | null;
  hi: number | null;
}

export interface ModelSkill {
  leads: number[];
  crpss: SkillPoint[];
  bias: SkillPoint[];
  n: { lead: number; n: number }[];
}

export interface AifsIfsRow {
  /** "1".."10" or a range such as "8–10". */
  lead: string;
  n: number;
  mae_ifs: number;
  mae_aifs: number;
  diff: number;
  lo: number | null;
  hi: number | null;
  bias_ifs: number;
  bias_aifs: number;
  p_sign: number | null;
  verdict: string;
}

export interface Interval {
  value: number | null;
  lo: number | null;
  hi: number | null;
}

export interface PodFar {
  pod: number | null;
  far: number | null;
  hits: number;
  false_alarms: number;
  n_risk_days: number;
}

export interface GateRow {
  lead: number;
  n_events: number;
  n_events_pooled: number;
  base_rate: number;
  bss_log_clim: Interval;
  bss_log_markov: Interval;
  status: string;
  prob_cap: number | null;
  pod_far: Record<string, PodFar>;
}

export interface GateTable {
  quantile: number;
  thresholds_mm: Record<string, number>;
  n_events_pooled_test: number;
  n_events_test: Record<string, number>;
  fc_source: string;
  fc_period: string;
  regions: Record<string, GateRow[]>;
}

/** `skill.json`. */
export interface HindcastSkill {
  id: string;
  obs_source: string;
  models: Record<string, ModelSkill>;
  aifs_vs_ifs: { unit: string; first: string; last: string; n_event: number; rows: AifsIfsRow[] };
  gate: GateTable;
}

export interface AnalogRain {
  imerg: number | null;
  era5: number | null;
}

export interface AnalogDay {
  rank?: number;
  date: string;
  distance: number | null;
  ar_event_id: string | null;
  ivt_max: number | null;
  rain: Record<string, AnalogRain>;
}

export interface AnalogSummary {
  n_days?: number;
  ar_fraction: number | null;
  ivt_max_mean?: number | null;
  rain?: Record<string, AnalogRain>;
}

export interface AnalogEvent {
  event_id: string;
  date: string;
  ivt_max: number | null;
  analogs: AnalogDay[];
  analog_summary?: AnalogSummary;
  baseline?: AnalogSummary;
}

/** `analogs.json` of the `hindcast-analogs` layer (only the fields the panel reads). */
export interface AnalogsData {
  regions?: string[];
  k?: number;
  period?: string;
  events: AnalogEvent[];
}

export const GATE_STATUS_PASS = "pasa hindcast (espera la temporada prospectiva)";

const nf = (min: number, max: number) => new Intl.NumberFormat("es-AR", { minimumFractionDigits: min, maximumFractionDigits: max });
const f1 = nf(1, 1);
const f2 = nf(2, 2);
const f0 = nf(0, 0);

/** Decimal-comma formats; `null`/NaN read "s/d" (sin dato). */
export const NO_DATA = "s/d";
export const fmt1 = (v: number | null | undefined): string => (v == null || !Number.isFinite(v) ? NO_DATA : f1.format(v));
export const fmt2 = (v: number | null | undefined): string => (v == null || !Number.isFinite(v) ? NO_DATA : f2.format(v));
export const fmt0 = (v: number | null | undefined): string => (v == null || !Number.isFinite(v) ? NO_DATA : f0.format(v));
export const fmtSigned1 = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? NO_DATA : `${v > 0 ? "+" : ""}${f1.format(v)}`;
export const fmtPct = (v: number | null | undefined): string => (v == null || !Number.isFinite(v) ? NO_DATA : `${f0.format(v * 100)} %`);

/** "0,65 (0,54 a 0,74)": a value with its 95 % interval. */
export const fmtInterval2 = (i: Interval | SkillPoint | null | undefined): string =>
  !i || i.value == null ? NO_DATA : `${fmt2(i.value)} (${fmt2(i.lo)} a ${fmt2(i.hi)})`;

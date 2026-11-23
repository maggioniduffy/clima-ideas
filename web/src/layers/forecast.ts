/** Layer id published by the backend `forecast-outlook` layer (F6.6). */
export const FORECAST_LAYER_ID = "forecast-outlook";

export type OutlookEstado = "Experimental" | "Perspectiva de riesgo";

export interface OutlookHistory {
  n: number | null;
  n_events: number | null;
  n_events_pooled: number | null;
  skill: number | null;
  ci: [number | null, number | null] | null;
  pod: number | null;
  far: number | null;
  insufficient: boolean;
}

export interface OutlookHindcast {
  bss_clim: number | null;
  ci: [number | null, number | null] | null;
  verdict: string | null;
  n_events_pooled: number | null;
}

export interface OutlookLead {
  lead: number;
  valid_date: string;
  p: number | null;
  p_low: number | null;
  p_high: number | null;
  interval_level: number;
  clim_p: number | null;
  clim_low: number | null;
  clim_high: number | null;
  prob_cap: number | null;
  above_cap: boolean;
  p_shown: number | null;
  estado: string;
  hindcast: OutlookHindcast | null;
  history: OutlookHistory | null;
}

export interface OutlookRegion {
  id: string;
  label: string;
  threshold_mm: number | null;
  leads: OutlookLead[];
}

/** `forecast-outlook/outlook.json`. */
export interface Outlook {
  variable: string;
  variable_label: string;
  issue_date: string;
  issued_at: string;
  gefs_init_date: string;
  model: { name: string; version: string; training_period: string; baseline: string };
  inputs: { name: string; latency_hours: number }[];
  cap_rule: string;
  notices: { official: string; audience: string; states: Record<string, string> };
  official_links: { label: string; url: string }[];
  regions: OutlookRegion[];
  history_note: string;
  /** Absent in older layers. */
  seasonal?: Seasonal;
  highflow?: Highflow;
}

export type Pair = [number | null, number | null];

export interface SeasonalModel {
  name: string;
  label: string;
  emitted: boolean;
  reason?: string;
  p_terciles?: { inferior: number | null; medio: number | null; superior: number | null };
  p_superior_interval?: Pair | null;
  interval_level?: number;
  model_version?: string;
  training_period?: string;
}

export interface SeasonalLead {
  lead_months: number;
  /** `YYYY-MM`. */
  target_month: string;
  edges: { lower_up_to: number | null; upper_from: number | null; unit: string } | null;
  models: SeasonalModel[];
  skill: { metric: string; rpss_vs_clim: number | null; ci95: Pair | null; beats_climatology: boolean; source?: string } | null;
}

export interface SeasonalTarget {
  id: string;
  label: string;
  unit: string;
  region?: string;
  note: string | null;
  leads: SeasonalLead[];
}

/** `outlook.seasonal` (F6.2): either `{available:false, note}` or the newest emission. */
export interface Seasonal {
  available: boolean;
  note?: string;
  estado?: string;
  variable_label?: string;
  issue_date?: string;
  source?: string;
  period?: string;
  model_version?: string;
  notices?: string[];
  targets?: SeasonalTarget[];
}

export interface F67Lead {
  n_floods: number | null;
  rises: number | null;
  rises_frac: number | null;
  rises_ci95: Pair | null;
  coverage: number | null;
  coverage_ci95: Pair | null;
  coverage_nominal: number;
  bss_clim: number | null;
  bss_clim_ci95: Pair | null;
  verdict: string;
}

export interface F67Variant {
  threshold_rule: string;
  models: Record<string, Record<string, F67Lead>>;
}

export interface F67 {
  available: boolean;
  source?: string;
  period?: string | null;
  independent_years?: { n: number; required: number; years: number[] };
  n_floods?: number;
  variants?: Record<string, F67Variant>;
  report_note?: string | null;
}

export interface Bss {
  n: number | null;
  n_exceed: number | null;
  bss: number | null;
  ci95: Pair;
  ci_excludes_0: boolean | null;
  status: string | null;
}

export interface BssVs {
  vs_climatology: { pooled: Bss | null; stations: Record<string, Bss | null> };
  vs_persistence: { pooled: Bss | null; stations: Record<string, Bss | null> };
}

export interface F69Threshold {
  threshold_rule: string;
  threshold_m3s: Record<string, number | null>;
  era5: BssVs;
  gefs_by_lead: Record<string, BssVs & { n_events: number | null }>;
}

export interface F69 {
  available: boolean;
  source?: string;
  period?: string | null;
  gefs_period?: string | null;
  n_events?: number | null;
  stations?: Record<string, { name: string | null; period: string | null }>;
  thresholds?: Record<string, F69Threshold>;
}

/** `outlook.highflow` (F6.7 / F6.9): retrospective evidence only. */
export interface Highflow {
  estado?: string;
  note?: string;
  f67?: F67;
  f69?: F69;
}

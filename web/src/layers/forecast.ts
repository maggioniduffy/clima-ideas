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
}

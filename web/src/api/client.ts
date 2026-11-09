export type LayerKind = "events" | "points" | "raster-frames" | "series" | "polygons";

/** Mirrors backend `LayerManifest` (clima_nqn.layers.manifest). */
export interface LayerManifest {
  id: string;
  title: string;
  kind: LayerKind;
  source: string;
  period: string;
  license: string;
  updated_at: string;
  files: string[];
}

export interface PointFeature {
  id: string;
  lon: number;
  lat: number;
  value: number;
}

/** Row of `flood-stations/stations.json` (clima-nqn flow layer): `value` is the 100-year flow, or the max observed. */
export interface FloodStationFeature extends PointFeature {
  name?: string;
  river?: string;
  area_km2?: number | null;
  has_gev?: boolean;
  regulated?: boolean;
}

export interface FloodReturnPoint {
  t: number;
  q: number;
  lo: number | null;
  hi: number | null;
}

export interface FloodMaximum {
  hydro_year: number;
  date: string;
  q: number;
  t_empirical: number | null;
  t_gev: number | null;
}

/** `flood-stations/stations/<id>.json`. `gev`, `return_levels` and `curve` are absent without a GEV fit. */
export interface FloodStationDetail {
  id: string;
  name: string;
  river: string;
  lon: number;
  lat: number;
  area_km2: number | null;
  has_gev: boolean;
  regulated: boolean;
  source: string;
  period: string;
  fetched: string;
  daily: { start: string; q: (number | null)[] };
  annual_maxima: FloodMaximum[];
  top_floods: FloodMaximum[];
  gev?: { loc: number; scale: number; shape_xi: number; n_years: number; ks_p: number; irregular: boolean };
  return_levels?: FloodReturnPoint[];
  curve?: FloodReturnPoint[];
}

const BASE = "/api";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return (await res.json()) as T;
}

export const fetchLayers = () => getJson<LayerManifest[]>(`${BASE}/layers`);

export const fetchLayer = (id: string) =>
  getJson<LayerManifest>(`${BASE}/layers/${encodeURIComponent(id)}`);

export const fetchLayerData = <T = PointFeature[]>(id: string, file?: string) =>
  getJson<T>(
    `${BASE}/layers/${encodeURIComponent(id)}/data` +
      (file ? `?file=${encodeURIComponent(file)}` : ""),
  );

export async function fetchLayerBinary(id: string, file: string): Promise<ArrayBuffer> {
  const url = `${BASE}/layers/${encodeURIComponent(id)}/data?file=${encodeURIComponent(file)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.arrayBuffer();
}

export interface ArEvent {
  event_id: string;
  start: string;
  end: string;
  duration_h: number;
  n_steps: number;
  prob_max: number;
  area_frac_max: number;
  ivt_max: number | null;
  ivt_max_time: string | null;
  ivt_max_lat: number | null;
  ivt_max_lon: number | null;
  deg0l_max: number | null;
  deg0l_mean: number | null;
  tp_sum_mm: number | null;
  enso_phase: string | null;
}

/** Regional grid of the hourly frames: row 0 = south (lat_min), column 0 = west (lon_min). */
export interface FrameGrid {
  ny: number;
  nx: number;
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
}

/** `frames/index.json` published by `clima-nqn ar layer`. */
export interface FramesIndex {
  units: string;
  step_hours: number;
  grid: FrameGrid;
  events: Record<string, { start: string; n_frames: number; vmin: number; vmax: number }>;
}

export async function fetchFrames(layerId: string, t: string): Promise<ArrayBuffer> {
  const url = `${BASE}/layers/${encodeURIComponent(layerId)}/frames/${encodeURIComponent(t)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.arrayBuffer();
}

export type EnsoPhase = "nino" | "neutral" | "nina";
export type EnsoMetric = "n_events" | "ar_days" | "ivt_mean" | "ar_share";

export interface EnsoGroup {
  n: number;
  mean: number | null;
  sd: number | null;
}

/** One season x metric test of `F1.8.json` (backend `stages/ar/enso.py:compute_results`); NaN arrives as null. */
export interface EnsoRow {
  season: string;
  metric: EnsoMetric;
  phase_years: Record<EnsoPhase, number>;
  groups: Record<EnsoPhase, EnsoGroup>;
  diff_nino_nina: number | null;
  p: number | null;
  p_bh: number | null;
  p_3group: number | null;
  p_3group_bh: number | null;
  f_3group: number | null;
  sustained: boolean;
  sustained_bh: boolean;
}

/** `enso.json` published with the `ar-events` layer: the F1.8 report numbers. `ar_share` is a fraction (0-1). */
export interface EnsoStats {
  meta: {
    period?: string;
    season_years_period?: string;
    n_events?: number;
    n_season_years?: number;
    bard_threshold?: number | null;
    polygon?: [number, number][] | null;
    source?: string;
  };
  results: { rows: EnsoRow[]; n_perm: number; seed: number; alpha: number };
}

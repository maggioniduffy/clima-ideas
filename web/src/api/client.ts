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

/** Static mode: base URL of the published layers (R2), or "" to use the local API. */
const dataBase = () => import.meta.env.VITE_DATA_URL || "";

/** `${base}/seg/seg...`: each segment is encoded, `/` inside a segment (nested file names) is kept. */
export const staticUrl = (base: string, ...segments: string[]) =>
  [base.replace(/\/+$/, ""), ...segments.map((s) => s.split("/").map(encodeURIComponent).join("/"))].join("/");

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return (await res.json()) as T;
}

async function getBuffer(url: string): Promise<ArrayBuffer> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.arrayBuffer();
}

let layerIndex: Promise<LayerManifest[]> | null = null;
/** Test hook: forget the cached `layers.json`. */
export const resetLayerIndexCache = () => {
  layerIndex = null;
};

export const fetchLayers = () => {
  const data = dataBase();
  if (!data) return getJson<LayerManifest[]>(`${BASE}/layers`);
  layerIndex ??= getJson<LayerManifest[]>(staticUrl(data, "layers.json")).catch((e) => {
    layerIndex = null;
    throw e;
  });
  return layerIndex;
};

export const fetchLayer = (id: string) => {
  const data = dataBase();
  return getJson<LayerManifest>(
    data ? staticUrl(data, id, "manifest.json") : `${BASE}/layers/${encodeURIComponent(id)}`,
  );
};

/** Static mode: the file the API serves by default, `files[0]` of the manifest. */
async function defaultFile(data: string, id: string): Promise<string> {
  const indexed = (await fetchLayers()).find((l) => l.id === id);
  const manifest = indexed ?? (await getJson<LayerManifest>(staticUrl(data, id, "manifest.json")));
  return manifest.files[0];
}

export const fetchLayerData = async <T = PointFeature[]>(id: string, file?: string) => {
  const data = dataBase();
  if (!data) {
    return getJson<T>(
      `${BASE}/layers/${encodeURIComponent(id)}/data` + (file ? `?file=${encodeURIComponent(file)}` : ""),
    );
  }
  return getJson<T>(staticUrl(data, id, file ?? (await defaultFile(data, id))));
};

export async function fetchLayerBinary(id: string, file: string): Promise<ArrayBuffer> {
  const data = dataBase();
  return getBuffer(
    data
      ? staticUrl(data, id, file)
      : `${BASE}/layers/${encodeURIComponent(id)}/data?file=${encodeURIComponent(file)}`,
  );
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
  /** Per-event maximum |IVT| per cell (`frames/footprints.bin`); absent in layers published before footprints. */
  footprints?: FootprintsIndex;
}

/** `footprints` of `frames/index.json`: Float32 `[n_events, ny, nx]` on the frames grid, events in `events` order. */
export interface FootprintsIndex {
  file: string;
  events: string[];
  shape: [number, number, number];
}

export async function fetchFrames(layerId: string, t: string): Promise<ArrayBuffer> {
  const data = dataBase();
  return getBuffer(
    data
      ? staticUrl(data, layerId, "frames", `${t}.bin`)
      : `${BASE}/layers/${encodeURIComponent(layerId)}/frames/${encodeURIComponent(t)}`,
  );
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

/** One season-year of `enso.json`: the AR metrics of that season and its ONI phase; NaN arrives as null. */
export interface EnsoSeasonYear {
  season: string;
  year: number;
  n_events: number | null;
  ar_days: number | null;
  ivt_mean: number | null;
  ivt_max: number | null;
  ar_precip_mm: number | null;
  total_precip_mm: number | null;
  ar_share: number | null;
  oni_mean: number | null;
  phase: EnsoPhase | string | null;
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
  /** One entry per season-year (the dots of the chart). */
  season_years?: EnsoSeasonYear[];
}

export interface ExtremeGroup {
  n: number;
  years_with_extreme: number;
  total_days: number;
  mean_days: number | null;
}

/** One season of an F1.9 variant (backend F1.9 report); NaN arrives as null. */
export interface ExtremeRow {
  season: string;
  phase_years: Record<EnsoPhase, number>;
  groups: Record<EnsoPhase, ExtremeGroup>;
  diff_nino_nina: number | null;
  p: number | null;
  p_bh: number | null;
  p_3group: number | null;
  p_3group_bh: number | null;
  spearman_rho: number | null;
  p_oni: number | null;
  p_oni_bh: number | null;
  sustained_bh: boolean;
}

export interface ExtremeSeasonYear {
  season: string;
  year: number;
  oni_mean: number | null;
  phase: EnsoPhase | string | null;
  n_extreme_days: number | null;
  any_extreme: boolean | null;
}

export interface ExtremeVariant {
  label: string;
  quantile: number;
  region: "polygon" | "rectangle";
  threshold_mm: number;
  n_extreme_days_total: number;
  rows: ExtremeRow[];
  season_years: ExtremeSeasonYear[];
}

export type ExtremeVariantId = "main" | "p95" | "rectangle";

/** `enso-extremes.json` published with the `ar-events` layer: F1.9, extreme-rain days by ENSO phase. */
export interface EnsoExtremes {
  meta: {
    period?: string;
    season_years_period?: string;
    source?: string;
    n_perm?: number;
    seed?: number;
    alpha?: number;
  };
  variants: { main: ExtremeVariant } & Partial<Record<ExtremeVariantId, ExtremeVariant>>;
  /** Per season: does the main conclusion hold under p95 and the rectangle. */
  robust: Record<string, boolean>;
}

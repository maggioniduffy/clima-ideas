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

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

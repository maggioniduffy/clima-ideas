import type { Layer } from "@deck.gl/core";
import { GeoJsonLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import type { Rgba } from "./arEvents";

/** Layer id published by `clima-nqn debris layer` (backend `layers/debris_catchments.py`). */
export const DEBRIS_LAYER_ID = "debris-catchments";
/** Catchments shown in the ranked list. */
export const DEBRIS_TOP_N = 10;
export const DEBRIS_DEFAULT_T = 10;

/** Properties of one polygon of `catchments.geojson`. */
export interface CatchmentProps {
  id: number;
  /** Road or urban polygon the catchment drains onto (e.g. "RP5"). */
  target: string;
  area_km2: number;
  mean_slope_deg: number;
  relief_m: number;
  longest_flow_path_m: number;
  outlet_lon: number;
  outlet_lat: number;
  /** Polygon area / minimum rotated rectangle area (0..1); with `elongation` it flags D8 artifacts. */
  rectangularity?: number;
  elongation?: number;
  /** Probable D8 artifact on planar terrain (criterio propio, sin verificar): hidden and unranked by default. */
  planar_flow?: boolean;
  /** Id of the larger catchment of another target this one overlaps; it stays on the map but is not ranked. */
  overlaps_id?: number | null;
}

/** True for catchments that enter the ranking: neither a planar-flow artifact nor an overlap of another target's. */
export const isRanked = (p: CatchmentProps): boolean => !p.planar_flow && p.overlaps_id == null;

export interface CatchmentFeature {
  type: "Feature";
  id?: number;
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: unknown };
  properties: CatchmentProps;
}

export interface CatchmentCollection {
  type: "FeatureCollection";
  features: CatchmentFeature[];
}

/** [minLon, minLat, maxLon, maxLat] of a catchment polygon (Polygon or MultiPolygon); null when it has no finite point. */
export function catchmentBounds(f: Pick<CatchmentFeature, "geometry">): [number, number, number, number] | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const walk = (c: unknown): void => {
    if (!Array.isArray(c)) return;
    if (typeof c[0] === "number" && typeof c[1] === "number") {
      const [x, y] = c as number[];
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      minX = Math.min(minX, x!);
      maxX = Math.max(maxX, x!);
      minY = Math.min(minY, y!);
      maxY = Math.max(maxY, y!);
      return;
    }
    c.forEach(walk);
  };
  walk(f.geometry.coordinates);
  return Number.isFinite(minX) ? [minX, minY, maxX, maxY] : null;
}

export interface CnScenario {
  id: string;
  /** Hydrologic soil group. */
  hsg: string;
  cn: number;
  central: boolean;
}

/** `peaks.json`: values per catchment are ordered like `return_periods`. */
export interface DebrisPeaks {
  return_periods: number[];
  extrapolation_above_t: number;
  durations_h: number[];
  rain: {
    source: string;
    period: string;
    license: string;
    cell: string;
    bias_correction: string;
    note: string;
    /** depth_mm[T][duration_h] */
    depth_mm: Record<string, Record<string, number>>;
  };
  cn: { label: string; source: string; citation: string; note: string; scenarios: CnScenario[] };
  method: string;
  catchments_source: { sources: string[]; periods: string[] };
  n_catchments: number;
  n_ranked?: number;
  planar_flow?: { min_rectangularity: number; min_elongation: number; n_excluded: number; citation: string; note: string };
  overlap?: { min_fraction: number; n_excluded: number; citation: string; note: string };
  catchments: Record<string, { peak_m3s: Record<string, number[]>; critical_duration_h: Record<string, number[]> }>;
}

export const centralScenario = (p: DebrisPeaks): CnScenario => p.cn.scenarios.find((s) => s.central) ?? p.cn.scenarios[0]!;

/** Peak (m³/s) of a catchment for a CN scenario and a return period; null if absent. */
export function peakAt(p: DebrisPeaks, id: number, cnId: string, t: number): number | null {
  const k = p.return_periods.indexOf(t);
  const v = p.catchments[String(id)]?.peak_m3s[cnId]?.[k];
  return k < 0 || v == null ? null : v;
}

/** Range of the peak across all CN scenarios (and the value of the central one) at one return period. */
export function peakRange(p: DebrisPeaks, id: number, t: number): { lo: number; hi: number; central: number } | null {
  const vals = p.cn.scenarios.map((s) => peakAt(p, id, s.id, t));
  if (vals.some((v) => v == null)) return null;
  const nums = vals as number[];
  return { lo: Math.min(...nums), hi: Math.max(...nums), central: peakAt(p, id, centralScenario(p).id, t)! };
}

/** Critical duration (h) of the peak: the one that maximises it. */
export function criticalDuration(p: DebrisPeaks, id: number, cnId: string, t: number): number | null {
  const k = p.return_periods.indexOf(t);
  return k < 0 ? null : (p.catchments[String(id)]?.critical_duration_h[cnId]?.[k] ?? null);
}

/** Design rain depth (mm) of the IDF table at a return period and duration. */
export const rainDepth = (p: DebrisPeaks, t: number, d: number): number | null => p.rain.depth_mm[String(t)]?.[String(d)] ?? null;

export interface RankedCatchment {
  id: number;
  rank: number;
  peak: number;
  props: CatchmentProps;
}

/** Ranked catchments (see `isRanked`) by peak discharge, largest first (ties by id); `rank` starts at 1. */
export function rankCatchments(
  features: readonly CatchmentFeature[],
  p: DebrisPeaks,
  cnId: string,
  t: number,
  n = Infinity,
): RankedCatchment[] {
  return features
    .flatMap((f) => {
      if (!isRanked(f.properties)) return [];
      const peak = peakAt(p, f.properties.id, cnId, t);
      return peak == null ? [] : [{ id: f.properties.id, peak, props: f.properties }];
    })
    .sort((a, b) => b.peak - a.peak || a.id - b.id)
    .slice(0, n)
    .map((r, i) => ({ ...r, rank: i + 1 }));
}

/** Log-scale domain [min, max] (m³/s) of the positive values; null when there is none. */
export function colorDomain(values: readonly number[]): [number, number] | null {
  const pos = values.filter((v) => v > 0 && Number.isFinite(v));
  if (!pos.length) return null;
  return [Math.min(...pos), Math.max(...pos)];
}

/** Position 0..1 of `v` on the log scale of `domain` (0.5 when the domain is a single value; 0 for v <= 0). */
export function logFraction(v: number, domain: [number, number]): number {
  if (!(v > 0)) return 0;
  const [lo, hi] = domain;
  if (hi <= lo) return 0.5;
  return Math.min(1, Math.max(0, (Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))));
}

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];

/** Neutral sequential violet-grey ramp (`tokens.debrisRamp`), linear between the stops. */
export function debrisColor(fraction: number, theme: Theme, alpha = 215): Rgba {
  const colors = tokens.debrisRamp[theme].map(hex);
  const f = Math.min(1, Math.max(0, fraction)) * (colors.length - 1);
  const i = Math.min(Math.floor(f), colors.length - 2);
  const u = f - i;
  const [r, g, b] = [0, 1, 2].map((c) => Math.round(colors[i]![c]! + (colors[i + 1]![c]! - colors[i]![c]!) * u));
  return [r!, g!, b!, alpha];
}

const rgba = (h: string, a = 255): Rgba => [...hex(h), a] as Rgba;

/** Features drawn on the map: planar-flow ones only when `showPlanar` is on. */
export function visibleFeatures(features: readonly CatchmentFeature[], showPlanar: boolean): CatchmentFeature[] {
  return showPlanar ? [...features] : features.filter((f) => !f.properties.planar_flow);
}

export interface DebrisLayerArgs {
  /** Already filtered with `visibleFeatures`. */
  data: CatchmentCollection;
  peaks: DebrisPeaks;
  cnId: string;
  t: number;
  domain: [number, number] | null;
  selectedId: number | null;
  theme: Theme;
  onPick: (id: number) => void;
}

/**
 * Map layers: the catchment polygons and, because ~1 km² polygons are sub-pixel at the regional zoom, a dot per outlet
 * (pixel radius). Both are coloured by the peak of the chosen return period and CN scenario; the selected one gets an
 * accent outline.
 */
export function buildDebrisLayers({ data, peaks, cnId, t, domain, selectedId, theme, onPick }: DebrisLayerArgs): Layer[] {
  const tk = tokens[theme];
  const planar = new Set(data.features.filter((f) => f.properties.planar_flow).map((f) => f.properties.id));
  const muted = rgba(theme === "dark" ? tk.text : tk.ctrl, 45); // planar-flow artifacts: pale neutral, not on the scale
  const fill = (id: number): Rgba => {
    if (planar.has(id)) return muted;
    const v = peakAt(peaks, id, cnId, t) ?? 0;
    return debrisColor(domain ? logFraction(v, domain) : 0, theme);
  };
  const outline = rgba(theme === "dark" ? tk.text : tk.ctrl, 200);
  const accent = rgba(tk.accent);
  const casing = rgba(tk.casing);
  const triggers = { getFillColor: [cnId, t, domain, theme, planar.size], getLineColor: [selectedId, theme], getLineWidth: [selectedId] };
  return [
    new GeoJsonLayer<CatchmentProps>({
      id: `polygons-${DEBRIS_LAYER_ID}`,
      data: data as never,
      pickable: true,
      filled: true,
      stroked: true,
      getFillColor: (f) => fill((f as unknown as CatchmentFeature).properties.id),
      getLineColor: (f) => ((f as unknown as CatchmentFeature).properties.id === selectedId ? accent : outline),
      getLineWidth: (f) => ((f as unknown as CatchmentFeature).properties.id === selectedId ? 3 : 1),
      lineWidthUnits: "pixels",
      parameters: { depthCompare: "always" },
      updateTriggers: triggers,
      onClick: ({ object }) => {
        if (object) onPick((object as unknown as CatchmentFeature).properties.id);
      },
    }),
    new ScatterplotLayer<CatchmentFeature>({
      id: `outlets-${DEBRIS_LAYER_ID}`,
      data: data.features,
      pickable: true,
      getPosition: (f) => [f.properties.outlet_lon, f.properties.outlet_lat],
      radiusUnits: "pixels",
      getRadius: (f) => (f.properties.id === selectedId ? 7 : 4),
      radiusMinPixels: 3,
      getFillColor: (f) => fill(f.properties.id),
      stroked: true,
      getLineColor: (f) => (f.properties.id === selectedId ? casing : outline),
      getLineWidth: (f) => (f.properties.id === selectedId ? 2 : 1),
      lineWidthUnits: "pixels",
      parameters: { depthCompare: "always" },
      updateTriggers: { ...triggers, getRadius: [selectedId], getLineColor: [selectedId, theme] },
      onClick: ({ object }) => {
        if (object) onPick(object.properties.id);
      },
    }),
  ];
}

const nf = new Intl.NumberFormat("es-AR", { maximumSignificantDigits: 3 });
/** Discharge with three significant digits, es-AR decimal comma. */
export const fmtQ = (v: number): string => nf.format(v);
const n1 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });
const n2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 });
export const fmtKm2 = (v: number): string => n2.format(v);
export const fmtMetres = (v: number): string => n1.format(v);
export const fmtRatio = (v: number): string => n2.format(v);
export const fmtDeg = (v: number): string => n1.format(v);

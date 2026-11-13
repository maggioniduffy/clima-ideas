import { useEffect, useState } from "react";
import { fetchLayerData, type FloodStationDetail } from "../api/client";

export const FLOOD_LAYER_ID = "flood-stations";

export interface FloodStationState {
  status: "idle" | "loading" | "ready" | "error";
  detail: FloodStationDetail | null;
}

/** Detail of one station (`stations/<id>.json` of the layer), cached per station for the session. */
export function useFloodStation(layerId: string | null, stationId: string | null): FloodStationState {
  const key = layerId && stationId ? `${layerId}/${stationId}` : null;
  const [loaded, setLoaded] = useState<Record<string, FloodStationDetail>>({});
  const [failed, setFailed] = useState<Record<string, true>>({});

  useEffect(() => {
    if (!key || !layerId || !stationId || loaded[key] || failed[key]) return;
    let cancelled = false;
    fetchLayerData<FloodStationDetail>(layerId, `stations/${stationId}.json`)
      .then((d) => !cancelled && setLoaded((prev) => ({ ...prev, [key]: d })))
      .catch(() => !cancelled && setFailed((prev) => ({ ...prev, [key]: true })));
    return () => {
      cancelled = true;
    };
  }, [key, layerId, stationId, loaded, failed]);

  if (!key) return { status: "idle", detail: null };
  if (loaded[key]) return { status: "ready", detail: loaded[key] };
  return { status: failed[key] ? "error" : "loading", detail: null };
}

/** One issue day of an event hindcast: flows in m3/s for leads 1..n (`null` = gap). */
export interface FloodEventIssue {
  issue_date: string;
  days_before_peak: number;
  persistence: number | null;
  median: (number | null)[];
  lo: (number | null)[];
  hi: (number | null)[];
}

export interface FloodEvent {
  peak_date: string;
  peak_q: number;
  hydro_year: number;
  obs: { start: string; q: (number | null)[] };
  issues: FloodEventIssue[];
}

export interface FloodEventsMeta {
  run_name: string | null;
  mode: string;
  split: string;
  seeds: number[];
  test_years: [number, number];
  leads: number;
  forcing: string;
  caveat: string;
  pretrain: string | null;
  area_km2: number | null;
  area_note: string | null;
  source: string;
  period: string;
}

/** `flood-stations/events/<id>.json` (clima-nqn flow lstm-hindcast). */
export interface FloodEventsFile {
  station_id: string;
  meta: FloodEventsMeta;
  events: FloodEvent[];
}

export interface FloodEventsState {
  status: "idle" | "loading" | "ready" | "error";
  data: FloodEventsFile | null;
}

/** Hindcast events of one station (`events/<id>.json`), fetched only when `enabled` and cached per station. */
export function useFloodEvents(layerId: string | null, stationId: string | null, enabled: boolean): FloodEventsState {
  const key = enabled && layerId && stationId ? `${layerId}/${stationId}` : null;
  const [loaded, setLoaded] = useState<Record<string, FloodEventsFile>>({});
  const [failed, setFailed] = useState<Record<string, true>>({});

  useEffect(() => {
    if (!key || !layerId || !stationId || loaded[key] || failed[key]) return;
    let cancelled = false;
    fetchLayerData<FloodEventsFile>(layerId, `events/${stationId}.json`)
      .then((d) => !cancelled && setLoaded((prev) => ({ ...prev, [key]: d })))
      .catch(() => !cancelled && setFailed((prev) => ({ ...prev, [key]: true })));
    return () => {
      cancelled = true;
    };
  }, [key, layerId, stationId, loaded, failed]);

  if (!key) return { status: "idle", data: null };
  if (loaded[key]) return { status: "ready", data: loaded[key] };
  return { status: failed[key] ? "error" : "loading", data: null };
}

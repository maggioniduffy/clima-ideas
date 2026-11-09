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

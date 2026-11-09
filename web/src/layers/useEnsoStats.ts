import { useEffect, useState } from "react";
import { fetchLayerData, type EnsoStats, type LayerManifest } from "../api/client";

export const ENSO_FILE = "enso.json";

/**
 * ENSO-phase statistics (F1.8) of an `events` layer: fetched once the layer is active and its manifest lists
 * `enso.json`. "none" = the layer publishes no ENSO report.
 */
export function useEnsoStats(layer: LayerManifest | undefined, active: boolean) {
  const layerId = layer?.id;
  const listed = !!layer?.files.includes(ENSO_FILE);
  const [data, setData] = useState<EnsoStats | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!active || !layerId || !listed || data || failed) return;
    let cancelled = false;
    fetchLayerData<EnsoStats>(layerId, ENSO_FILE)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [active, layerId, listed, data, failed]);

  const status: "none" | "loading" | "ready" | "error" = !listed
    ? "none"
    : failed
      ? "error"
      : data
        ? "ready"
        : "loading";
  return { status, data };
}

import { useEffect, useState } from "react";
import { fetchLayerData, type EnsoExtremes, type LayerManifest } from "../api/client";

export const ENSO_EXTREMES_FILE = "enso-extremes.json";

/**
 * Extreme-rain days by ENSO phase (F1.9) of an `events` layer: fetched once the layer is active and its manifest
 * lists `enso-extremes.json`. "none" = the layer publishes no F1.9 report.
 */
export function useEnsoExtremes(layer: LayerManifest | undefined, active: boolean) {
  const layerId = layer?.id;
  const listed = !!layer?.files.includes(ENSO_EXTREMES_FILE);
  const [data, setData] = useState<EnsoExtremes | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!active || !layerId || !listed || data || failed) return;
    let cancelled = false;
    fetchLayerData<EnsoExtremes>(layerId, ENSO_EXTREMES_FILE)
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

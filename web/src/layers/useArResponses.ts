import { useEffect, useState } from "react";
import { fetchLayerData, type ArResponses, type LayerManifest } from "../api/client";

export const AR_RESPONSES_FILE = "responses.json";

/**
 * Caudal response around each event (`responses.json`) of an `events` layer. Optional: a layer that does not list the
 * file, or whose request fails, gives `data: null` and the viewer simply shows no caudal chart and no response sort.
 */
export function useArResponses(layer: LayerManifest | undefined, active: boolean) {
  const layerId = layer?.id;
  const listed = !!layer?.files.includes(AR_RESPONSES_FILE);
  const [data, setData] = useState<ArResponses | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!active || !layerId || !listed || data || failed) return;
    let cancelled = false;
    fetchLayerData<ArResponses>(layerId, AR_RESPONSES_FILE)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [active, layerId, listed, data, failed]);

  return { data };
}

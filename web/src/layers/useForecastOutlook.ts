import { useEffect, useState } from "react";
import { fetchLayerData, type LayerManifest } from "../api/client";
import type { Outlook } from "./forecast";

/** `forecast-outlook` layer (F6.6): loads `outlook.json` when the layer is switched on. */
export function useForecastOutlook(layer: LayerManifest | undefined, active: boolean) {
  const layerId = layer?.id;
  const file = layer?.files.find((f) => f === "outlook.json");
  const [data, setData] = useState<Outlook | null>(null);
  const [failed, setFailed] = useState(false);
  const [wasActive, setWasActive] = useState(active);

  if (wasActive !== active) {
    setWasActive(active);
    if (active) setFailed(false); // switching the layer back on retries a failed load
  }

  useEffect(() => {
    if (!active || !layerId || !file || data || failed) return;
    let cancelled = false;
    fetchLayerData<Outlook>(layerId, file)
      .then((o) => !cancelled && setData(o))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [active, layerId, file, data, failed]);

  const status: "idle" | "loading" | "ready" | "error" = failed ? "error" : data ? "ready" : active && file ? "loading" : "idle";
  return { status, outlook: data };
}

export type ForecastState = ReturnType<typeof useForecastOutlook>;

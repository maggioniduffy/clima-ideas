import { useEffect, useState } from "react";
import { fetchLayerData, type LayerManifest } from "../api/client";
import type { AnalogsData, HindcastCases, HindcastSkill } from "./hindcast";

interface Loaded {
  cases: HindcastCases;
  skill: HindcastSkill;
  /** `null` when the `hindcast-analogs` layer is absent or fails to load: the panel then omits that section. */
  analogs: AnalogsData | null;
}

const fileOf = (layer: LayerManifest | undefined, name: string) => layer?.files.find((f) => f === name);

/**
 * `hindcast-verification` layer (F5.6): forecasts of the F1.3 events against ERA5, skill curves and the evidence gate.
 * Loads when the layer is switched on; the analogs of the optional `hindcast-analogs` layer come with it when published.
 */
export function useHindcast(layer: LayerManifest | undefined, analogsLayer: LayerManifest | undefined, active: boolean) {
  const layerId = layer?.id;
  const casesFile = fileOf(layer, "cases.json");
  const skillFile = fileOf(layer, "skill.json");
  const analogsId = analogsLayer?.id;
  const analogsFile = fileOf(analogsLayer, "analogs.json");
  const [data, setData] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  const [wasActive, setWasActive] = useState(active);

  if (wasActive !== active) {
    setWasActive(active);
    if (active) setFailed(false); // switching the layer back on retries a failed load
  }

  useEffect(() => {
    if (!active || !layerId || !casesFile || !skillFile || data || failed) return;
    let cancelled = false;
    (async () => {
      const [cases, skill, analogs] = await Promise.all([
        fetchLayerData<HindcastCases>(layerId, casesFile),
        fetchLayerData<HindcastSkill>(layerId, skillFile),
        analogsId && analogsFile
          ? fetchLayerData<AnalogsData>(analogsId, analogsFile).catch(() => null)
          : Promise.resolve(null),
      ]);
      if (!cancelled) setData({ cases, skill, analogs });
    })().catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [active, layerId, casesFile, skillFile, analogsId, analogsFile, data, failed]);

  const status: "idle" | "loading" | "ready" | "error" = failed
    ? "error"
    : data
      ? "ready"
      : active && casesFile && skillFile
        ? "loading"
        : "idle";
  return { status, cases: data?.cases ?? null, skill: data?.skill ?? null, analogs: data?.analogs ?? null };
}

export type HindcastState = ReturnType<typeof useHindcast>;

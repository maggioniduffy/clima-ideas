import { useCallback, useEffect, useMemo, useState } from "react";
import type { Layer } from "@deck.gl/core";
import { fetchLayerBinary, fetchLayerData, fetchLayers, type LayerManifest, type PointFeature } from "../api/client";
import { buildPointsLayer } from "./pointsLayer";
import { useTheme } from "../theme/themeStore";
import { buildReliefLayer, parseRelief, RELIEF_STEP, type ReliefData } from "./reliefLayer";

/** Grid step (degrees) from the layer's `*.meta.json` (field `step`); RELIEF_STEP when absent or unreadable. */
async function fetchReliefStep(id: string, layer: LayerManifest): Promise<number> {
  const meta = layer.files.find((f) => f.endsWith(".meta.json"));
  if (!meta) return RELIEF_STEP;
  try {
    const step = (JSON.parse(new TextDecoder().decode(await fetchLayerBinary(id, meta))) as { step?: unknown }).step;
    return typeof step === "number" && step > 0 ? step : RELIEF_STEP;
  } catch {
    return RELIEF_STEP;
  }
}

/** Binary point-cloud layers: kind "points" whose manifest lists a .bin file. */
const binaryFile = (l: LayerManifest) => (l.kind === "points" ? l.files.find((f) => f.endsWith(".bin")) : undefined);

/** Layer catalogue + activation + selection state for the viewer shell. */
export function useLayers() {
  const [layers, setLayers] = useState<LayerManifest[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [activeIds, setActiveIds] = useState<ReadonlySet<string>>(new Set());
  const [data, setData] = useState<Record<string, PointFeature[]>>({});
  const [reliefs, setReliefs] = useState<Record<string, ReliefData>>({});
  const theme = useTheme();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedPointId, setSelectedPointId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchLayers()
      .then((l) => {
        if (cancelled) return;
        setLayers(l);
        setStatus("ready");
      })
      .catch(() => !cancelled && setStatus("error"));
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = useCallback(
    (id: string) => {
      const turnOn = !activeIds.has(id);
      setActiveIds((prev) => {
        const next = new Set(prev);
        if (turnOn) next.add(id);
        else next.delete(id);
        return next;
      });
      if (turnOn) {
        setSelectedId(id);
        const layer = layers.find((l) => l.id === id);
        const bin = layer ? binaryFile(layer) : undefined;
        const failed = () => setActiveIds((prev) => new Set([...prev].filter((x) => x !== id)));
        if (bin) {
          if (!reliefs[id]) {
            Promise.all([fetchLayerBinary(id, bin), fetchReliefStep(id, layer!)])
              .then(([b, step]) => setReliefs((prev) => ({ ...prev, [id]: parseRelief(b, step) })))
              .catch(failed);
          }
        } else if (layer?.kind === "points" && !data[id]) {
          fetchLayerData(id)
            .then((d) => setData((prev) => ({ ...prev, [id]: d })))
            .catch(failed);
        }
      }
    },
    [activeIds, layers, data, reliefs],
  );

  const select = useCallback((id: string) => {
    setSelectedId(id);
    setSelectedPointId(null);
  }, []);

  const pickPoint = useCallback((layerId: string, f: PointFeature) => {
    setSelectedId(layerId);
    setSelectedPointId(f.id);
  }, []);

  const deckLayers = useMemo(
    () =>
      layers
        .filter((l) => activeIds.has(l.id))
        .sort((a, b) => Number(!!reliefs[b.id]) - Number(!!reliefs[a.id])) // terrain at the bottom
        .flatMap((l): Layer[] => {
          if (reliefs[l.id]) return [buildReliefLayer(l.id, reliefs[l.id]!, theme)];
          if (l.kind === "points" && data[l.id])
            return [
              buildPointsLayer(l.id, data[l.id]!, selectedId === l.id ? selectedPointId : null, (f) =>
                pickPoint(l.id, f),
              ),
            ];
          return [];
        }),
    [layers, activeIds, data, reliefs, theme, selectedId, selectedPointId, pickPoint],
  );

  const reliefId = layers.find((l) => activeIds.has(l.id) && reliefs[l.id])?.id;
  /** The active relief (id + parsed data), for layers that color it (IVT drape); null when none is on. */
  const activeRelief = useMemo(
    () => (reliefId ? { layerId: reliefId, data: reliefs[reliefId]! } : null),
    [reliefId, reliefs],
  );

  const selectedLayer = layers.find((l) => l.id === selectedId) ?? null;
  const selectedFeatures = selectedLayer && activeIds.has(selectedLayer.id) ? (data[selectedLayer.id] ?? []) : [];

  return {
    layers,
    status,
    activeIds,
    selectedId,
    selectedLayer,
    selectedFeatures,
    selectedPointId,
    deckLayers,
    activeRelief,
    toggle,
    select,
    selectPoint: (pid: string) => setSelectedPointId(pid),
  };
}

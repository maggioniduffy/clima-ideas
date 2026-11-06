import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchLayerData, fetchLayers, type LayerManifest, type PointFeature } from "../api/client";
import { buildPointsLayer } from "./pointsLayer";

/** Layer catalogue + activation + selection state for the viewer shell. */
export function useLayers() {
  const [layers, setLayers] = useState<LayerManifest[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [activeIds, setActiveIds] = useState<ReadonlySet<string>>(new Set());
  const [data, setData] = useState<Record<string, PointFeature[]>>({});
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
        if (layer?.kind === "points" && !data[id]) {
          fetchLayerData(id)
            .then((d) => setData((prev) => ({ ...prev, [id]: d })))
            .catch(() => setActiveIds((prev) => new Set([...prev].filter((x) => x !== id))));
        }
      }
    },
    [activeIds, layers, data],
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
        .filter((l) => activeIds.has(l.id) && l.kind === "points" && data[l.id])
        .map((l) =>
          buildPointsLayer(l.id, data[l.id]!, selectedId === l.id ? selectedPointId : null, (f) =>
            pickPoint(l.id, f),
          ),
        ),
    [layers, activeIds, data, selectedId, selectedPointId, pickPoint],
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
    toggle,
    select,
    selectPoint: (pid: string) => setSelectedPointId(pid),
  };
}

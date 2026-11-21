import { useEffect, useMemo, useState } from "react";
import type { Layer } from "@deck.gl/core";
import { fetchLayerData, type LayerManifest } from "../api/client";
import { useTheme } from "../theme/themeStore";
import {
  buildDebrisLayers,
  centralScenario,
  colorDomain,
  DEBRIS_DEFAULT_T,
  DEBRIS_TOP_N,
  peakAt,
  rankCatchments,
  visibleFeatures,
  type CatchmentCollection,
  type DebrisPeaks,
} from "./debrisCatchments";

interface Loaded {
  geo: CatchmentCollection;
  peaks: DebrisPeaks;
}

const fileOf = (layer: LayerManifest | undefined, name: string) => layer?.files.find((f) => f === name);

/**
 * `debris-catchments` layer (F4.3): catchment polygons coloured by peak discharge for the chosen return period and CN
 * scenario, the ranking and the selected catchment. Loads when the layer is switched on.
 */
export function useDebrisCatchments(layer: LayerManifest | undefined, active: boolean) {
  const layerId = layer?.id;
  const geoFile = fileOf(layer, "catchments.geojson");
  const peaksFile = fileOf(layer, "peaks.json");
  const [data, setData] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  const [t, setT] = useState(DEBRIS_DEFAULT_T);
  const [cnPick, setCnPick] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showPlanar, setShowPlanarRaw] = useState(false);
  const [wasActive, setWasActive] = useState(active);
  const theme = useTheme();

  if (wasActive !== active) {
    setWasActive(active);
    if (active) setFailed(false); // switching the layer back on retries a failed load
    if (!active) setSelectedId(null);
  }

  useEffect(() => {
    if (!active || !layerId || !geoFile || !peaksFile || data || failed) return;
    let cancelled = false;
    Promise.all([
      fetchLayerData<CatchmentCollection>(layerId, geoFile),
      fetchLayerData<DebrisPeaks>(layerId, peaksFile),
    ])
      .then(([geo, peaks]) => !cancelled && setData({ geo, peaks }))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [active, layerId, geoFile, peaksFile, data, failed]);

  const status: "idle" | "loading" | "ready" | "error" = failed
    ? "error"
    : data
      ? "ready"
      : active && geoFile && peaksFile
        ? "loading"
        : "idle";
  const peaks = data?.peaks ?? null;
  const geo = data?.geo ?? null;
  const cnId = peaks ? (cnPick && peaks.cn.scenarios.some((s) => s.id === cnPick) ? cnPick : centralScenario(peaks).id) : null;
  const tNow = peaks && peaks.return_periods.includes(t) ? t : (peaks?.return_periods[0] ?? t);

  const ranking = useMemo(
    () => (geo && peaks && cnId ? rankCatchments(geo.features, peaks, cnId, tNow) : []),
    [geo, peaks, cnId, tNow],
  );
  const domain = useMemo(() => colorDomain(ranking.map((r) => r.peak)), [ranking]);
  const planarCount = useMemo(() => geo?.features.filter((f) => f.properties.planar_flow).length ?? 0, [geo]);
  const selected = selectedId != null ? (geo?.features.find((f) => f.properties.id === selectedId)?.properties ?? null) : null;

  const setShowPlanar = (on: boolean) => {
    setShowPlanarRaw(on);
    if (!on && selected?.planar_flow) setSelectedId(null); // a hidden catchment cannot stay selected
  };

  const deckLayers = useMemo<Layer[]>(
    () =>
      active && geo && peaks && cnId
        ? buildDebrisLayers({
            data: { type: "FeatureCollection", features: visibleFeatures(geo.features, showPlanar) },
            peaks,
            cnId,
            t: tNow,
            domain,
            selectedId,
            theme,
            onPick: setSelectedId,
          })
        : [],
    [active, geo, peaks, cnId, tNow, domain, selectedId, theme, showPlanar],
  );

  return {
    status,
    peaks,
    geo,
    t: tNow,
    setT,
    cnId,
    setCnId: setCnPick,
    selectedId,
    selected,
    select: setSelectedId,
    ranking,
    top: ranking.slice(0, DEBRIS_TOP_N),
    domain,
    showPlanar,
    setShowPlanar,
    planarCount,
    shownCount: geo ? visibleFeatures(geo.features, showPlanar).length : 0,
    selectedPeak: selected && peaks && cnId ? peakAt(peaks, selected.id, cnId, tNow) : null,
    deckLayers,
  };
}

export type DebrisState = ReturnType<typeof useDebrisCatchments>;

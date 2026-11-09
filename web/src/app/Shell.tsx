import { useEffect, useMemo, useState } from "react";
import { es } from "../i18n/es";
import type { IvtView } from "../layers/arEvents";
import { useArEvents } from "../layers/useArEvents";
import { useEnsoStats } from "../layers/useEnsoStats";
import { buildReliefLayer } from "../layers/reliefLayer";
import { useReferenceLayers } from "../layers/referenceLayers";
import { useLayers } from "../layers/useLayers";
import { useTheme } from "../theme/themeStore";
import { EnsoPanel } from "./EnsoPanel";
import { Inspector } from "./Inspector";
import { LayerPanel } from "./LayerPanel";
import { MapCanvas } from "./MapCanvas";
import { MapLegend } from "./MapLegend";
import { Timeline } from "./Timeline";
import { TopBar, type Drawer } from "./TopBar";
import "./shell.css";

export function Shell() {
  // narrow screens: the side panels are drawers, one open at a time (CSS decides whether it applies)
  const [drawer, setDrawer] = useState<Drawer | null>(null);
  const toggleDrawer = (d: Drawer) => setDrawer((cur) => (cur === d ? null : d));
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);
  const s = useLayers();
  const eventsLayer = s.layers.find((l) => l.kind === "events");
  const eventsActive = !!eventsLayer && s.activeIds.has(eventsLayer.id);
  const enso = useEnsoStats(eventsLayer, eventsActive);
  const [ensoOpen, setEnsoOpen] = useState(false);
  const showEnso = ensoOpen && eventsActive && enso.status !== "none";
  const [ivtView, setIvtView] = useState<IvtView>("drape");
  const theme = useTheme();
  const ar = useArEvents(eventsLayer, eventsActive, { relief: s.activeRelief?.data ?? null, view: ivtView });
  // In the drape view the relief itself carries the IVT: swap its slate colors for the frame's drape colors.
  const baseLayers = useMemo(
    () =>
      ar.drapeColors && s.activeRelief
        ? s.deckLayers.map((l) =>
            l.id === `relief-${s.activeRelief!.layerId}`
              ? buildReliefLayer(s.activeRelief!.layerId, s.activeRelief!.data, theme, ar.drapeColors!)
              : l,
          )
        : s.deckLayers,
    [s.deckLayers, s.activeRelief, ar.drapeColors, theme],
  );
  const refLayers = useReferenceLayers();
  const selectEvent = (id: string) => {
    if (eventsLayer) s.select(eventsLayer.id);
    ar.select(id);
  };
  return (
    <div className="shell" data-testid="shell" data-drawer={drawer ?? undefined}>
      <TopBar drawer={drawer} onToggleDrawer={toggleDrawer} />
      <LayerPanel
        layers={s.layers}
        status={s.status}
        activeIds={s.activeIds}
        selectedId={s.selectedId}
        onToggle={s.toggle}
        onSelect={s.select}
        events={
          eventsLayer && {
            layerId: eventsLayer.id,
            status: ar.status,
            items: ar.events,
            selectedEventId: ar.selectedEventId,
            onSelectEvent: selectEvent,
            ensoStatus: enso.status,
            ensoOpen: showEnso,
            onToggleEnso: () => setEnsoOpen((o) => !o),
          }
        }
      />
      <MapCanvas layers={[...baseLayers, ...ar.deckLayers, ...refLayers]}>
        {showEnso && eventsLayer && enso.status !== "none" && (
          <EnsoPanel
            status={enso.status}
            stats={enso.data}
            source={eventsLayer.source}
            period={eventsLayer.period}
            onClose={() => setEnsoOpen(false)}
          />
        )}
        {eventsActive && <MapLegend view={ivtView} onViewChange={setIvtView} />}
      </MapCanvas>
      <Inspector
        layer={s.selectedLayer}
        features={s.selectedFeatures}
        selectedPointId={s.selectedPointId}
        onSelectPoint={s.selectPoint}
        event={{ selected: ar.selectedEvent, loadingFrames: ar.loadingFrames, reading: ar.reading }}
      />
      <button
        type="button"
        className="drawer-scrim"
        data-testid="drawer-scrim"
        aria-label={es.drawers.close}
        tabIndex={-1}
        onClick={() => setDrawer(null)}
      />
      <Timeline
        events={eventsActive ? ar.events : []}
        period={eventsLayer?.period}
        selectedEventId={ar.selectedEventId}
        onSelectEvent={selectEvent}
        replay={ar.selectedEvent ? ar : null}
      />
    </div>
  );
}

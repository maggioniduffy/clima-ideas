import { useEffect, useState } from "react";
import { IVT_OVER_RELIEF_OPACITY } from "../layers/ivtRasterLayer";
import { es } from "../i18n/es";
import { useArEvents } from "../layers/useArEvents";
import { useReferenceLayers } from "../layers/referenceLayers";
import { useLayers } from "../layers/useLayers";
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
  const reliefOn = s.deckLayers.some((l) => l.id.startsWith("relief-"));
  const ar = useArEvents(eventsLayer, eventsActive, reliefOn ? IVT_OVER_RELIEF_OPACITY : 1);
  const refLayers = useReferenceLayers(eventsActive);
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
          }
        }
      />
      <MapCanvas layers={[...s.deckLayers, ...ar.deckLayers, ...refLayers]}>
        {eventsActive && <MapLegend />}
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

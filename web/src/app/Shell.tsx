import { IVT_OVER_RELIEF_OPACITY } from "../layers/ivtRasterLayer";
import { useArEvents } from "../layers/useArEvents";
import { useReferenceLayers } from "../layers/referenceLayers";
import { useLayers } from "../layers/useLayers";
import { Inspector } from "./Inspector";
import { LayerPanel } from "./LayerPanel";
import { MapCanvas } from "./MapCanvas";
import { MapLegend } from "./MapLegend";
import { Timeline } from "./Timeline";
import { TopBar } from "./TopBar";
import "./shell.css";

export function Shell() {
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
    <div className="shell" data-testid="shell">
      <TopBar />
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

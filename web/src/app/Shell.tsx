import { useLayers } from "../layers/useLayers";
import { Inspector } from "./Inspector";
import { LayerPanel } from "./LayerPanel";
import { MapCanvas } from "./MapCanvas";
import { Timeline } from "./Timeline";
import { TopBar } from "./TopBar";
import "./shell.css";

export function Shell() {
  const s = useLayers();
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
      />
      <MapCanvas layers={s.deckLayers} />
      <Inspector
        layer={s.selectedLayer}
        features={s.selectedFeatures}
        selectedPointId={s.selectedPointId}
        onSelectPoint={s.selectPoint}
      />
      <Timeline />
    </div>
  );
}

import { Inspector } from "./Inspector";
import { LayerPanel } from "./LayerPanel";
import { MapCanvas } from "./MapCanvas";
import { Timeline } from "./Timeline";
import { TopBar } from "./TopBar";
import "./shell.css";

export function Shell() {
  return (
    <div className="shell" data-testid="shell">
      <TopBar />
      <LayerPanel />
      <MapCanvas />
      <Inspector />
      <Timeline />
    </div>
  );
}

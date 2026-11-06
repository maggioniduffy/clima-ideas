import DeckGL from "@deck.gl/react";
import { MapView } from "@deck.gl/core";

// Neuquén province; pitch leaves room for the 3D relief layer (F0.5).
const INITIAL_VIEW_STATE = {
  longitude: -69.5,
  latitude: -38.5,
  zoom: 6,
  pitch: 40,
  bearing: 0,
};

export function MapCanvas() {
  return (
    <main className="shell-canvas" data-testid="map-canvas">
      <DeckGL
        views={new MapView({ repeat: false })}
        initialViewState={INITIAL_VIEW_STATE}
        controller
        layers={[]}
        style={{ background: "transparent" }}
      />
    </main>
  );
}

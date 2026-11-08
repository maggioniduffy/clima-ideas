import DeckGL from "@deck.gl/react";
import { MapView, type Layer } from "@deck.gl/core";
import type { ReactNode } from "react";

// Neuquén province; pitch leaves room for the 3D relief layer (F0.5).
const INITIAL_VIEW_STATE = {
  longitude: -69.5,
  latitude: -38.5,
  zoom: 6,
  pitch: 40,
  bearing: 0,
};

export function MapCanvas({ layers = [], children }: { layers?: Layer[]; children?: ReactNode }) {
  return (
    <main className="shell-canvas" data-testid="map-canvas" data-deck-layers={layers.map((l) => l.id).join(",")}>
      <DeckGL
        views={new MapView({ repeat: false })}
        initialViewState={INITIAL_VIEW_STATE}
        controller
        layers={layers}
        style={{ background: "transparent" }}
      />
      {children}
    </main>
  );
}

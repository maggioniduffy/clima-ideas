import DeckGL from "@deck.gl/react";
import { MapView, WebMercatorViewport, type Layer, type MapViewState } from "@deck.gl/core";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

// Neuquén province; pitch leaves room for the 3D relief layer (F0.5).
const INITIAL_VIEW_STATE: MapViewState = {
  longitude: -69.5,
  latitude: -38.5,
  zoom: 6,
  pitch: 40,
  bearing: 0,
};

/** A labelled point over the map (HTML, positioned from the live view state). */
export interface MapMarker {
  id: string;
  kind: "station" | "cell";
  lon: number;
  lat: number;
  label: string;
  /** Hover text (native tooltip, also the accessible description). */
  tooltip: string;
  /**
   * Where the label sits relative to the point. `left-up` / `left-down` put it to the left of the dot, above /
   * below the point's row, joined by a short leader line (so two labels on nearly the same point stack, and
   * neither covers what lies to the right of the point, such as a city label).
   */
  placement: "up" | "down" | "left-up" | "left-down";
}

const MAP_VIEW = new MapView({ repeat: false });

/**
 * The map card. deck.gl sizes its canvas to this element, so it follows layout changes (panel resizes, grid
 * reflow); the element size is also tracked here to place the HTML markers.
 */
export function MapCanvas({ layers = [], markers = [], children }: { layers?: Layer[]; markers?: MapMarker[]; children?: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const [view, setView] = useState<MapViewState>(INITIAL_VIEW_STATE);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const read = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const placed = useMemo(() => {
    if (!markers.length || size.width < 1 || size.height < 1) return [];
    const vp = new WebMercatorViewport({ ...view, width: size.width, height: size.height });
    return markers.flatMap((m) => {
      const [x, y] = vp.project([m.lon, m.lat]);
      return Number.isFinite(x) && Number.isFinite(y) && x >= 0 && y >= 0 && x <= size.width && y <= size.height
        ? [{ m, x, y }]
        : [];
    });
  }, [markers, view, size]);
  return (
    <main ref={ref} className="shell-canvas" data-testid="map-canvas" data-deck-layers={layers.map((l) => l.id).join(",")}>
      <DeckGL
        views={MAP_VIEW}
        viewState={view}
        onViewStateChange={({ viewState }) => setView(viewState as MapViewState)}
        controller
        layers={layers}
        style={{ background: "transparent" }}
      />
      {placed.map(({ m, x, y }) => (
        <div
          key={m.id}
          className={`map-marker map-marker-${m.kind}`}
          data-testid={`marker-${m.id}`}
          data-placement={m.placement}
          style={{ left: x, top: y }}
          title={m.tooltip}
          role="img"
          aria-label={m.tooltip}
        >
          <span className="map-marker-dot" />
          <span className="map-marker-label">{m.label}</span>
        </div>
      ))}
      {children}
    </main>
  );
}

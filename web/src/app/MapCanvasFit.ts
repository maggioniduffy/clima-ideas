import { WebMercatorViewport, type MapViewState } from "@deck.gl/core";

/** [minLon, minLat, maxLon, maxLat] */
export type Bounds = [number, number, number, number];

/**
 * Ask the map to frame a box. A new object (new identity) is a new request; the map acts once per object.
 * `ifNeeded` is for requests that come from the map itself (a click): the view then only moves when the box is not
 * comfortably in view already.
 */
export interface FocusRequest {
  bounds: Bounds;
  ifNeeded?: boolean;
}

export const FIT_PADDING_PX = 48;
/** Keeps a ~0.1 km² box from zooming past useful context. */
export const FIT_MAX_ZOOM = 13;
export const FIT_TRANSITION_MS = 800;
/** With `ifNeeded`, a box that would need this many more zoom levels than the current view is "too small" to leave. */
export const TOO_SMALL_ZOOM_DELTA = 1.5;

export interface Size {
  width: number;
  height: number;
}

/** Padding that never exceeds what the viewport can spare (deck throws when padding eats the whole viewport). */
const paddingFor = (size: Size, padding: number) => Math.max(0, Math.min(padding, Math.floor(Math.min(size.width, size.height) / 2) - 1));

/** View state that frames `bounds` (pitch and bearing are kept); null while the viewport has no size. */
export function fitView(
  view: MapViewState,
  bounds: Bounds,
  size: Size,
  { padding = FIT_PADDING_PX, maxZoom = FIT_MAX_ZOOM }: { padding?: number; maxZoom?: number } = {},
): MapViewState | null {
  if (size.width < 1 || size.height < 1 || bounds.some((n) => !Number.isFinite(n))) return null;
  const vp = new WebMercatorViewport({ ...view, width: size.width, height: size.height });
  const { longitude, latitude, zoom } = vp.fitBounds(
    [
      [bounds[0], bounds[1]],
      [bounds[2], bounds[3]],
    ],
    { padding: paddingFor(size, padding), maxZoom },
  );
  return { ...view, longitude, latitude, zoom };
}

/** True when the box lies inside the viewport (inside the padding) and is not far smaller than the view calls for. */
export function isComfortablyInView(view: MapViewState, bounds: Bounds, size: Size, fitZoom: number): boolean {
  const vp = new WebMercatorViewport({ ...view, width: size.width, height: size.height });
  const pad = paddingFor(size, FIT_PADDING_PX);
  const corners: [number, number][] = [
    [bounds[0], bounds[1]],
    [bounds[2], bounds[3]],
  ];
  const inside = corners.every(([lon, lat]) => {
    const [x, y] = vp.project([lon, lat]);
    return x >= pad && y >= pad && x <= size.width - pad && y <= size.height - pad;
  });
  return inside && fitZoom - view.zoom <= TOO_SMALL_ZOOM_DELTA;
}

/** Target view for a request, or null when nothing should move. */
export function resolveFocus(view: MapViewState, req: FocusRequest, size: Size): MapViewState | null {
  const target = fitView(view, req.bounds, size);
  if (!target) return null;
  if (req.ifNeeded && isComfortablyInView(view, req.bounds, size, target.zoom)) return null;
  return target;
}

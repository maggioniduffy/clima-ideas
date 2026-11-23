import type { MapViewState } from "@deck.gl/core";
import type { Bounds, Size } from "./MapCanvasFit";

/** Covered area: the ERA5 box (`era5.NEUQUEN_BOX`, 34–43 °S, 74–66 °O; docs/architecture.md, "Área del visor"). */
export const COVER_BOX: Bounds = [-74, -43, -66, -34];
export const MAX_ZOOM = 12;
const TILE = 512;

/** World-pixel coordinates at zoom 0 (Web Mercator, y down), same convention as deck.gl's WebMercatorViewport. */
const worldX = (lon: number) => ((lon + 180) / 360) * TILE;
const worldY = (lat: number) => {
  const r = (lat * Math.PI) / 180;
  return (TILE / 2) * (1 - Math.log(Math.tan(Math.PI / 4 + r / 2)) / Math.PI);
};
const lonOf = (x: number) => (x / TILE) * 360 - 180;
const latOf = (y: number) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / TILE))) * 180) / Math.PI;

const BOX_W = worldX(COVER_BOX[2]) - worldX(COVER_BOX[0]);
const BOX_H = worldY(COVER_BOX[1]) - worldY(COVER_BOX[3]);

/** Smallest zoom at which the box covers (not just fits) a card of this size. */
export function coverZoom(size: Size): number {
  return Math.max(Math.log2(size.width / BOX_W), Math.log2(size.height / BOX_H));
}

/**
 * Limit a view to the covered area: zoom between the cover zoom and `MAX_ZOOM`, and the center such that, at pitch 0,
 * no box edge enters the card. Pitch, bearing and transition props pass through. Pure; a card without size, or a
 * non-finite view, is returned unchanged.
 */
export function clampView<T extends MapViewState>(view: T, size: Size): T {
  if (size.width < 1 || size.height < 1) return view;
  if (![view.longitude, view.latitude, view.zoom].every(Number.isFinite)) return view;
  const zoom = Math.min(MAX_ZOOM, Math.max(coverZoom(size), view.zoom));
  const scale = 2 ** zoom;
  const halfW = size.width / 2 / scale;
  const halfH = size.height / 2 / scale;
  const clamp = (v: number, lo: number, hi: number) => (lo > hi ? (lo + hi) / 2 : Math.min(hi, Math.max(lo, v)));
  const cx = clamp(worldX(view.longitude), worldX(COVER_BOX[0]) + halfW, worldX(COVER_BOX[2]) - halfW);
  const cy = clamp(worldY(view.latitude), worldY(COVER_BOX[3]) + halfH, worldY(COVER_BOX[1]) - halfH);
  const longitude = Math.abs(cx - worldX(view.longitude)) < 1e-9 ? view.longitude : lonOf(cx);
  const latitude = Math.abs(cy - worldY(view.latitude)) < 1e-9 ? view.latitude : latOf(cy);
  if (zoom === view.zoom && longitude === view.longitude && latitude === view.latitude) return view;
  return { ...view, zoom, longitude, latitude };
}

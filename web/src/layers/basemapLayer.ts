import { BitmapLayer } from "@deck.gl/layers";
import { TileLayer } from "@deck.gl/geo-layers";
import type { Theme } from "../theme/themeStore";

/** Layer id: the bottom layer of the stack (the map card excludes it from `data-deck-layers`). */
export const BASEMAP_LAYER_ID = "basemap";
/** CARTO raster style per theme (OpenStreetMap data). */
export const BASEMAP_STYLE: Record<Theme, string> = { light: "light_all", dark: "dark_all" };
/**
 * CARTO basemaps API key (build-time `VITE_CARTO_KEY`). CARTO requires one since 2026 (free for non-commercial use;
 * see reports/web/T4-basemap.md). Without it the tiles would only say "API KEY REQUIRED", so no basemap is drawn.
 */
export const BASEMAP_KEY: string = (import.meta.env.VITE_CARTO_KEY ?? "").trim();
export const basemapAvailable = (key: string = BASEMAP_KEY) => key.length > 0;
export const BASEMAP_ATTRIBUTION_URL = "https://carto.com/attributions";
export const OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright";

/** Tile URL template (@2x raster tiles, keyed). */
export const basemapUrl = (theme: Theme, key: string = BASEMAP_KEY): string =>
  `https://basemaps.cartocdn.com/rastertiles/${BASEMAP_STYLE[theme]}/{z}/{x}/{y}@2x.png?key=${encodeURIComponent(key)}`;

/** Raster basemap: deck.gl tiles drawn flat under every other layer. */
export function buildBasemapLayer(theme: Theme, visible = true, key: string = BASEMAP_KEY) {
  return new TileLayer({
    id: BASEMAP_LAYER_ID,
    data: basemapUrl(theme, key),
    // 256-unit tiles of @2x images: 512 px of image per tile, sharp on dense screens.
    tileSize: 256,
    minZoom: 0,
    maxZoom: 18,
    visible: visible && basemapAvailable(key),
    pickable: false,
    renderSubLayers: (props) => {
      const { boundingBox } = props.tile;
      const [[west, south], [east, north]] = boundingBox as [[number, number], [number, number]];
      const { data, ...rest } = props as typeof props & { data: unknown };
      return new BitmapLayer({
        id: props.id,
        image: data as ImageBitmap | null,
        bounds: [west, south, east, north],
        opacity: rest.opacity,
        pickable: false,
      });
    },
  });
}

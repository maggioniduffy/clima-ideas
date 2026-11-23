import { BitmapLayer } from "@deck.gl/layers";
import { TileLayer } from "@deck.gl/geo-layers";
import type { Theme } from "../theme/themeStore";

/** Layer id: the bottom layer of the stack (the map card excludes it from `data-deck-layers`). */
export const BASEMAP_LAYER_ID = "basemap";
/** CARTO raster style per theme (OpenStreetMap data). */
export const BASEMAP_STYLE: Record<Theme, string> = { light: "light_all", dark: "dark_all" };
/** Terms of use of CARTO basemaps for this use are "sin verificar" (see reports/web/T4-basemap.md). */
export const BASEMAP_ATTRIBUTION_URL = "https://carto.com/attributions";
export const OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright";

/** Tile URL templates (@2x tiles), one per subdomain a-d: deck.gl spreads requests over an array. */
export const basemapUrls = (theme: Theme): string[] =>
  ["a", "b", "c", "d"].map((s) => `https://${s}.basemaps.cartocdn.com/${BASEMAP_STYLE[theme]}/{z}/{x}/{y}@2x.png`);

/** Raster basemap: deck.gl tiles drawn flat under every other layer. */
export function buildBasemapLayer(theme: Theme, visible = true) {
  return new TileLayer({
    id: BASEMAP_LAYER_ID,
    data: basemapUrls(theme),
    // 256-unit tiles of @2x images: 512 px of image per tile, sharp on dense screens.
    tileSize: 256,
    minZoom: 0,
    maxZoom: 18,
    visible,
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

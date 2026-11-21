import { WebMercatorViewport } from "@deck.gl/core";
import { expect, test } from "@playwright/test";

// Same initial view as MapCanvas (INITIAL_VIEW_STATE) and the city position of referenceLayers (NEUQUEN_CITY).
const VIEW = { longitude: -69.5, latitude: -38.5, pitch: 40, bearing: 0 };
const CITY = [-68.06, -38.95] as const;
const STATION = [-68.156, -38.949] as const;

type Box = { x: number; y: number; width: number; height: number };
const intersects = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

/**
 * The "Neuquén" city label is drawn by a deck.gl TextLayer (canvas), so it has no DOM box. Its geometry is known from
 * referenceLayers.ts: anchor "start", baseline "bottom", pixel offset [6, -4], 12px monospace (about 7.2px per
 * glyph), background padding [3, 1]. The box below is that estimate, grown by 4px of margin, around the city
 * point projected with the same WebMercatorViewport the app uses.
 */
function cityLabelBox(zoom: number, map: Box): Box {
  const vp = new WebMercatorViewport({ ...VIEW, zoom, width: map.width, height: map.height });
  const [cx, cy] = vp.project([CITY[0], CITY[1]]) as [number, number];
  const w = 7 * 7.2 + 6;
  const h = 12 * 1.2 + 2;
  const m = 4;
  return { x: map.x + cx + 6 - 3 - m, y: map.y + cy - 4 - h - m, width: w + 2 * m, height: h + 2 * m + 2 };
}

test("convection markers do not cover the city label nor each other", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByTestId("layer-toggle-convection-idf").check();
  const station = page.getByTestId("marker-convection-station");
  const cell = page.getByTestId("marker-convection-cell");
  await expect(station).toBeVisible();
  await expect(cell).toBeVisible();
  const map = (await page.getByTestId("map-canvas").boundingBox())! as Box;
  const sLabel = (await station.locator(".map-marker-label").boundingBox())! as Box;
  const cLabel = (await cell.locator(".map-marker-label").boundingBox())! as Box;

  // initial zoom (6)
  expect(intersects(sLabel, cityLabelBox(6, map))).toBe(false);
  expect(intersects(cLabel, cityLabelBox(6, map))).toBe(false);
  expect(intersects(sLabel, cLabel)).toBe(false);

  // zooms 5-9: the labels keep a constant pixel offset from their point, only the city moves relative to them
  const vp = (z: number) => new WebMercatorViewport({ ...VIEW, zoom: z, width: map.width, height: map.height });
  const [sx, sy] = vp(6).project([STATION[0], STATION[1]]) as [number, number];
  for (const z of [5, 6, 7, 8, 9]) {
    const [px, py] = vp(z).project([STATION[0], STATION[1]]) as [number, number];
    const shift = (b: Box): Box => ({ ...b, x: b.x - (map.x + sx) + map.x + px, y: b.y - (map.y + sy) + map.y + py });
    const city = cityLabelBox(z, map);
    expect(intersects(shift(sLabel), city), `station label at zoom ${z}`).toBe(false);
    expect(intersects(shift(cLabel), city), `cell label at zoom ${z}`).toBe(false);
  }

  // tooltips and accessible labels are kept
  await expect(station).toHaveAttribute("title", /NOAA ISD/);
  await expect(station).toHaveAttribute("aria-label", /-38,949/);
  await expect(cell).toHaveAttribute("title", /IMERG falso de prueba/);
  await expect(cell).toHaveAttribute("aria-label", /-38,950/);
});

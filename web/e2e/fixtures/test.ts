import { readFileSync } from "node:fs";
import { test as base, expect, type Page } from "@playwright/test";

const TILE = readFileSync(new URL("./tile.png", import.meta.url));

/** `test` with the CARTO basemap tiles answered by a fixture PNG: e2e never reaches the tile server. */
export const test = base.extend({
  page: async ({ page }, provide) => {
    await page.route(/^https:\/\/([a-d]\.)?basemaps\.cartocdn\.com\//, (route) =>
      route.fulfill({ status: 200, contentType: "image/png", body: TILE, headers: { "access-control-allow-origin": "*" } }),
    );
    await provide(page);
  },
});
export { expect };

/** The layer list lives in the closed-by-default menu: open it (idempotent) and return the menu locator. */
export async function openLayerMenu(page: Page) {
  const btn = page.getByTestId("menu-toggle");
  if ((await btn.getAttribute("aria-expanded")) !== "true") await btn.click();
  const menu = page.getByTestId("layer-menu");
  await expect(menu).toBeVisible();
  return menu;
}

/** Closes the menu with its button (no-op when closed). */
export async function closeLayerMenu(page: Page) {
  const btn = page.getByTestId("menu-toggle");
  if ((await btn.getAttribute("aria-expanded")) === "true") await btn.click();
  await expect(page.getByTestId("layer-menu")).toHaveCount(0);
}

/** Turns a layer on or off through its menu checkbox and closes the menu so it never covers the map. */
export async function setLayer(page: Page, id: string, on = true) {
  await openLayerMenu(page);
  const box = page.getByTestId(`layer-toggle-${id}`);
  if (on) await box.check();
  else await box.uncheck();
  await closeLayerMenu(page);
}

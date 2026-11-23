import { readFileSync } from "node:fs";
import { test as base, expect } from "@playwright/test";

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

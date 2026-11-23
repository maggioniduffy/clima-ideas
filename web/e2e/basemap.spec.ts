import { expect, test } from "./fixtures/test";

test("basemap tiles come from the routed fixture and the attribution is always visible", async ({ page }) => {
  const tiles: string[] = [];
  page.on("request", (r) => r.url().includes("basemaps.cartocdn.com") && tiles.push(r.url()));
  await page.goto("/");
  const attribution = page.getByTestId("map-attribution");
  await expect(attribution).toBeVisible();
  await expect(attribution).toContainText("© OpenStreetMap contributors © CARTO");
  await expect(attribution.getByRole("link", { name: "CARTO" })).toHaveAttribute("href", /carto\.com/);
  await expect.poll(() => tiles.length).toBeGreaterThan(0);
  expect(tiles.every((u) => /^https:\/\/[a-d]\.basemaps\.cartocdn\.com\/(light_all|dark_all)\/\d+\/\d+\/\d+@2x\.png$/.test(u))).toBe(true);
  // the basemap is the bottom layer but is not listed among the data layers
  await expect(page.getByTestId("map-canvas")).not.toHaveAttribute("data-deck-layers", /basemap/);
});

test("background control: default Ambos, persists the choice and ignores invalid stored values", async ({ page }) => {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("seeded")) {
      sessionStorage.setItem("seeded", "1");
      localStorage.setItem("map-background", "garbage");
    }
  });
  await page.goto("/");
  await expect(page.getByTestId("map-bg-both")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("map-bg-relief").click();
  await expect(page.getByTestId("map-bg-relief")).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => localStorage.getItem("map-background"))).toBe("relief");
  await page.getByTestId("map-bg-basemap").click();
  expect(await page.evaluate(() => localStorage.getItem("map-background"))).toBe("basemap");
  await page.reload();
  await expect(page.getByTestId("map-bg-basemap")).toHaveAttribute("aria-pressed", "true");
});

test("camera never zooms out past the covered area and the canvas fills the card", async ({ page }) => {
  await page.goto("/");
  const card = page.getByTestId("map-canvas");
  await expect(card).toHaveAttribute("data-view-zoom", /./);
  const box = (await card.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < 12; i++) await page.mouse.wheel(0, 600);
  await page.waitForTimeout(400);
  const zoom = Number(await card.getAttribute("data-view-zoom"));
  // cover zoom of the 34-43 S / 74-66 W box for this card (same formula as mapCamera.coverZoom)
  const w = (512 * 8) / 360;
  const merc = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const h = (512 / (2 * Math.PI)) * (merc(-34) - merc(-43));
  const cover = Math.max(Math.log2(box.width / w), Math.log2(box.height / h));
  expect(zoom).toBeGreaterThanOrEqual(cover - 0.01);
  expect(zoom).toBeLessThan(cover + 0.2);
  const canvas = await card.locator("canvas").first().boundingBox();
  expect(canvas!.width).toBeCloseTo(box.width, 0);
  expect(canvas!.height).toBeCloseTo(box.height, 0);
});

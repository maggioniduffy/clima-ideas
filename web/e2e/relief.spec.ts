import { expect, test, openLayerMenu, closeLayerMenu } from "./fixtures/test";

test("relief is not a menu layer: it is on by default and only the background control switches it", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await openLayerMenu(page);
  await expect(page.getByTestId("layer-item-relief")).toHaveCount(0);
  await expect(page.getByTestId("layer-panel")).not.toContainText("Relieve");
  await closeLayerMenu(page);

  // on without any user action, drawn as a point cloud
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toHaveAttribute("data-deck-layers", /^relief-relief(,|$)/);
  await expect(canvas).toHaveAttribute("data-hidden-layers", "");
  await expect(page.getByTestId("map-bg-relief")).toHaveAttribute("aria-pressed", "true");

  // "Mapa" hides the relief; "Ambos" and "Relieve" show it again
  await page.getByTestId("map-bg-basemap").click();
  await expect(canvas).toHaveAttribute("data-hidden-layers", "relief-relief");
  await page.getByTestId("map-bg-both").click();
  await expect(canvas).toHaveAttribute("data-hidden-layers", "");
  await page.getByTestId("map-bg-relief").click();
  await expect(canvas).toHaveAttribute("data-hidden-layers", "");

  await page.waitForTimeout(500);
  expect(errors).toEqual([]);
});

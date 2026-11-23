import { closeLayerMenu, expect, openLayerMenu, setLayer, test } from "./fixtures/test";

test("test layer appears, activates and inspects with source and period", async ({ page }) => {
  await page.goto("/");

  await openLayerMenu(page);
  const item = page.getByTestId("layer-item-test-points");
  await expect(item).toContainText("Capa de prueba");
  await expect(item).toHaveAttribute("data-active", "false");
  await closeLayerMenu(page);
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /^(relief-relief,)?(ref-[a-z-]+(,|$))+$/);

  await setLayer(page, "test-points", true);
  await openLayerMenu(page);
  await expect(item).toHaveAttribute("data-active", "true");
  await closeLayerMenu(page);
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /^(relief-relief,)?points-test-points(,|$)/);

  await expect(page.getByTestId("inspector-source")).toHaveText("Datos falsos de prueba");
  await expect(page.getByTestId("inspector-period")).toHaveText("2000-01-01/2000-12-31");

  await page.getByTestId("feature-p3").click();
  await expect(page.getByTestId("inspector-point")).toContainText("48");
  await expect(page.getByTestId("inspector-source")).toHaveText("Datos falsos de prueba");
});

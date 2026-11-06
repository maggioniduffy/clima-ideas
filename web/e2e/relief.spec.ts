import { expect, test } from "@playwright/test";

test("relief layer appears, activates and renders as a point cloud without console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  const item = page.getByTestId("layer-item-relief");
  await expect(item).toContainText("Relieve");
  await expect(item).toHaveAttribute("data-active", "false");

  await page.getByTestId("layer-toggle-relief").check();
  await expect(item).toHaveAttribute("data-active", "true");
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", "relief-relief");
  await expect(page.getByTestId("inspector-source")).toHaveText("Relieve falso de prueba");
  await expect(page.getByTestId("inspector-period")).toHaveText("2021-01-01/2021-12-31");

  await page.waitForTimeout(500);
  expect(errors).toEqual([]);
});

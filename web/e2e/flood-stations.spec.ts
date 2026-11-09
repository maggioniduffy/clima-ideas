import { expect, test } from "@playwright/test";

test("flood stations: pick a station, see the return-period curve and the top floods", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.getByTestId("layer-item-flood-stations")).toContainText("Crecidas: caudal y período de retorno");

  await page.getByTestId("layer-toggle-flood-stations").check();
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /^points-flood-stations(,|$)/);
  await expect(page.getByTestId("inspector-source")).toHaveText("Datos falsos de prueba");

  // the list names stations, not "Punto <id>"
  const list = page.getByTestId("feature-list");
  await expect(list).toContainText("Estación Falsa Natural");
  await expect(list).not.toContainText("Punto");

  await page.getByTestId("feature-1001").click();
  const chart = page.getByTestId("return-period-chart");
  await expect(chart).toBeVisible();
  await expect(page.getByTestId("return-period-curve")).toBeVisible();
  await expect(page.getByTestId("return-period-band")).toBeVisible();
  await expect(page.getByTestId("flow-series-chart")).toBeVisible();
  const top = page.getByTestId("top-floods");
  await expect(top.locator("li")).toHaveCount(3);
  await expect(top.locator("li").first()).toContainText("01/03/2002");
  await expect(top.locator("li").first()).toContainText("520 m³/s");
  await expect(top.locator("li").first()).toContainText("T ≈ 22 años");
  await expect(page.getByTestId("flood-no-gev")).toHaveCount(0);

  // the regulated station has no GEV curve
  await page.getByTestId("feature-1002").click();
  await expect(page.getByTestId("flood-no-gev")).toHaveText("Río regulado aguas arriba: sin GEV");
  await expect(page.getByTestId("return-period-curve")).toHaveCount(0);
  await expect(page.getByTestId("top-floods").locator("li").first()).toContainText("140 m³/s");

  // no horizontal scroll in the inspector
  const overflow = await page
    .getByTestId("inspector")
    .evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
});

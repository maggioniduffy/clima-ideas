import { expect, test } from "@playwright/test";

test("convection: IDF chart, storm replay and station comparison", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.getByTestId("layer-item-convection-idf")).toContainText("Convección: curva IDF y temporal de abril de 2014");
  await page.getByTestId("layer-toggle-convection-idf").check();
  await expect(page.getByTestId("inspector-source")).toHaveText("IMERG falso de prueba");
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /rain-convection-idf/);

  // IDF chart: one curve per return period, Gumbel baseline, extrapolation marked, label and caveats
  const panel = page.getByTestId("convection-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("idf-label")).toHaveText("IDF solo con IMERG, sin corrección de sesgo");
  await expect(page.getByTestId("idf-chart")).toBeVisible();
  await expect(page.locator('[data-testid^="idf-curve-"]')).toHaveCount(6);
  await expect(page.locator('[data-testid^="idf-gumbel-"]')).toHaveCount(6);
  await expect(page.getByTestId("idf-curve-100")).toHaveAttribute("data-extrapolated", "true");
  await expect(page.getByTestId("idf-curve-10")).toHaveAttribute("data-extrapolated", "false");
  await expect(page.getByTestId("idf-label-100")).toHaveText("T 100†");
  await expect(page.getByTestId("idf-extrapolation")).toContainText("Extrapolación (T > 50 años");
  await expect(page.getByTestId("idf-band")).toHaveAttribute("data-t", "10");
  await page.getByTestId("idf-t-25").click();
  await expect(page.getByTestId("idf-band")).toHaveAttribute("data-t", "25");
  await expect(page.getByTestId("idf-source")).toContainText("IMERG falso de prueba");
  await expect(page.getByTestId("idf-source")).toContainText("2000/01–2024/25");
  await expect(page.getByTestId("conv-bias-caveat")).toContainText("sin corrección de sesgo");
  await expect(page.getByTestId("conv-not-alert")).toContainText("No es un sistema de alerta oficial");

  // sensitivity scenarios toggle
  await expect(page.locator('[data-testid^="idf-scenario-"]')).toHaveCount(0);
  await page.getByTestId("idf-scenarios").check();
  await expect(page.locator('[data-testid^="idf-scenario-"]')).toHaveCount(2);
  await page.getByTestId("idf-metric-depth").click();
  await expect(page.getByTestId("idf-chart")).toBeVisible();

  // replay: the time label advances while playing and ends on the last frame
  const controls = page.getByTestId("rain-controls");
  await expect(controls).toHaveAttribute("data-frame", "0");
  await expect(page.getByTestId("rain-time")).toHaveText("2014-04-06 10:00 UTC");
  await expect(page.getByTestId("rain-clock")).toContainText("2014-04-06 10:00 UTC");
  await expect(page.getByTestId("compare-current")).toHaveText("antes de la ventana");
  await page.getByTestId("rain-play").click();
  await expect(controls).toHaveAttribute("data-frame", "11");
  await expect(controls).toHaveAttribute("data-playing", "false");
  await expect(page.getByTestId("rain-time")).toHaveText("2014-04-06 15:30 UTC");
  await expect(page.getByTestId("rain-clock")).toContainText("2014-04-06 15:30 UTC");

  // comparison: station 118 mm against IMERG 97,6 mm, and the cumulative follows the frame
  await expect(page.getByTestId("compare-station")).toHaveText("118 mm");
  await expect(page.getByTestId("compare-imerg")).toHaveText("97,6 mm");
  await expect(page.getByTestId("compare-ratio")).toHaveText("0,83");
  await expect(page.getByTestId("compare-station-point")).toBeVisible();
  await expect(page.getByTestId("compare-source")).toContainText("NOAA ISD");
  await page.getByTestId("rain-slider").fill("8"); // 14:00 = end of the comparison window
  await expect(page.getByTestId("compare-current")).toHaveText("97,6 mm");
  await page.getByTestId("rain-slider").fill("4"); // 12:00 = start
  await expect(page.getByTestId("compare-current")).toHaveText("0 mm");
  await page.getByTestId("rain-forward").click();
  await expect(controls).toHaveAttribute("data-frame", "5");
  await expect(page.getByTestId("compare-current")).toHaveText("20 mm");

  // legend with source, no horizontal overflow
  await expect(page.getByTestId("rain-legend")).toContainText("Fuente: IMERG falso de prueba");
  const overflow = await page.getByTestId("detail-card").evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  // turning the layer off removes map layer and panel
  await page.getByTestId("layer-toggle-convection-idf").uncheck();
  await expect(page.getByTestId("convection-panel")).toHaveCount(0);
  await expect(page.getByTestId("map-canvas")).not.toHaveAttribute("data-deck-layers", /rain-convection-idf/);
  expect(errors).toEqual([]);
});

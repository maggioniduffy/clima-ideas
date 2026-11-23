import { expect, test, setLayer, openLayerMenu, closeLayerMenu } from "./fixtures/test";

test("convection: IDF chart, storm replay and station comparison", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await openLayerMenu(page);
  await expect(page.getByTestId("layer-item-convection-idf")).toHaveAttribute("title", "Convección: curva IDF y temporal de abril de 2014");
  await closeLayerMenu(page);
  await setLayer(page, "convection-idf", true);
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
  // notes are collapsed by default and readable once opened
  const notes = page.getByTestId("conv-notes");
  await expect(notes).not.toHaveAttribute("open", "");
  await expect(page.getByTestId("idf-extrapolation")).toBeHidden();
  await expect(page.getByTestId("conv-bias-caveat")).toBeHidden();
  await notes.locator("summary").click();
  await expect(page.getByTestId("idf-extrapolation")).toContainText("Extrapolación (T > 50 años");
  await expect(page.getByTestId("idf-legend")).toBeVisible();
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
  // the replay (controls and cumulative chart) lives in the timeline strip, not in the right column
  const timeline = page.getByTestId("timeline");
  await expect(timeline).toContainText("Replay del temporal");
  await expect(timeline.getByTestId("compare-chart")).toBeVisible();
  await expect(timeline.getByTestId("rain-controls")).toBeVisible();
  await expect(page.getByTestId("panels-slot").getByTestId("compare-chart")).toHaveCount(0);
  await expect(timeline).not.toContainText("Sin serie temporal");
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
  await setLayer(page, "convection-idf", false);
  await expect(page.getByTestId("convection-panel")).toHaveCount(0);
  await expect(page.getByTestId("map-canvas")).not.toHaveAttribute("data-deck-layers", /rain-convection-idf/);
  expect(errors).toEqual([]);
});

test("convection: the right column scrolls and the IDF chart is reachable at 1440x900", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLayer(page, "convection-idf", true);
  await expect(page.getByTestId("compare-chart")).toBeVisible();
  const col = page.getByTestId("panels-slot");
  expect(await col.evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
  await page.getByTestId("idf-chart").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("idf-chart")).toBeInViewport();
  const c = (await col.boundingBox())!;
  const i = (await page.getByTestId("idf-chart").boundingBox())!;
  expect(i.y).toBeGreaterThanOrEqual(c.y - 1);
  expect(i.y + i.height).toBeLessThanOrEqual(c.y + c.height + 1);
  // end-of-curve labels do not touch the x tick labels
  const labels = await page.locator('[data-testid^="idf-label-"]').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().bottom));
  const ticks = await page.getByTestId("idf-chart").locator("text.flood-tick").evaluateAll((els) =>
    els.filter((e) => /\d+ (h|min)$/.test(e.textContent ?? "")).map((e) => e.getBoundingClientRect().top),
  );
  expect(Math.max(...labels)).toBeLessThanOrEqual(Math.min(...ticks) + 1);
  // the replay chart sits inside the timeline region
  const tl = (await page.getByTestId("timeline-slot").boundingBox())!;
  const ch = (await page.getByTestId("compare-chart").boundingBox())!;
  expect(ch.y).toBeGreaterThanOrEqual(tl.y);
  expect(ch.y + ch.height).toBeLessThanOrEqual(tl.y + tl.height + 1);
  // opening the notes lengthens the column, nothing is cut horizontally
  await page.getByTestId("conv-notes").locator("summary").click();
  await expect(page.getByTestId("conv-bias-caveat")).toBeVisible();
});

test("convection: station marker and IMERG cell outline, with source tooltips", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("marker-convection-station")).toHaveCount(0);
  await setLayer(page, "convection-idf", true);
  const station = page.getByTestId("marker-convection-station");
  const cell = page.getByTestId("marker-convection-cell");
  await expect(station).toBeVisible();
  await expect(station).toContainText("Neuquén Aero (estación)");
  await expect(station).toHaveAttribute("title", /NOAA ISD/);
  await expect(cell).toContainText("Celda IMERG");
  await expect(cell).toHaveAttribute("title", /IMERG falso de prueba/);
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /convection-cell/);
  // both sit inside the map card
  const map = (await page.getByTestId("map-canvas").boundingBox())!;
  for (const m of [station, cell]) {
    const b = (await m.locator(".map-marker-label").boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(map.x);
    expect(b.x + b.width).toBeLessThanOrEqual(map.x + map.width);
    expect(b.y).toBeGreaterThanOrEqual(map.y);
  }
  await setLayer(page, "convection-idf", false);
  await expect(station).toHaveCount(0);
  await expect(page.getByTestId("map-canvas")).not.toHaveAttribute("data-deck-layers", /convection-cell/);
});

test("map legends stack without overlapping when the IVT and rain layers are both on", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLayer(page, "ar-events", true);
  await setLayer(page, "convection-idf", true);
  const ivt = page.getByTestId("map-legend");
  const rain = page.getByTestId("rain-legend");
  await expect(ivt).toBeVisible();
  await expect(rain).toBeVisible();
  const a = (await ivt.boundingBox())!;
  const b = (await rain.boundingBox())!;
  const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
  expect(overlap).toBe(false);
  const map = (await page.getByTestId("map-canvas").boundingBox())!;
  for (const r of [a, b]) {
    expect(r.x).toBeGreaterThanOrEqual(map.x);
    expect(r.y).toBeGreaterThanOrEqual(map.y);
    expect(r.y + r.height).toBeLessThanOrEqual(map.y + map.height);
  }
  // the clocks stack too: select an AR event so its clock shows next to the rain clock
  await page.getByTestId("timeline-event-AR-2000-001").click();
  await expect(page.getByTestId("map-clock")).toBeVisible();
  const c1 = (await page.getByTestId("map-clock").boundingBox())!;
  const c2 = (await page.getByTestId("rain-clock").boundingBox())!;
  expect(c1.y + c1.height <= c2.y || c2.y + c2.height <= c1.y).toBe(true);
});

import { expect, test } from "@playwright/test";

test("AR events: enable layer, choose an event, replay it and inspect a cell value", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.getByTestId("layer-item-ar-events")).toContainText("Ríos atmosféricos");
  await expect(page.getByTestId("timeline")).toContainText("Sin serie temporal");

  await page.getByTestId("layer-toggle-ar-events").check();
  await expect(page.getByTestId("inspector-source")).toHaveText("Eventos falsos de prueba");
  await expect(page.getByTestId("inspector-period")).toHaveText("2000-01-01/2000-12-31");

  // both events appear in the panel list and as marks on the timeline
  await expect(page.getByTestId("event-AR-2000-001")).toBeVisible();
  await expect(page.getByTestId("event-AR-2000-002")).toBeVisible();
  await expect(page.getByTestId("timeline-event-AR-2000-001")).toBeVisible();
  await expect(page.getByTestId("timeline-event-AR-2000-002")).toBeVisible();

  // choose the first event from its timeline mark
  await page.getByTestId("timeline-event-AR-2000-001").click();
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toHaveAttribute("data-deck-layers", /^ivt-ar-events,/);
  // outlines draw above the raster: province (loaded from the static GeoJSON), city and labels
  for (const id of ["ref-province", "ref-city", "ref-labels"])
    await expect(canvas).toHaveAttribute("data-deck-layers", new RegExp(`ivt-ar-events,.*${id}`));
  // legend: Spanish title, ticks up to "≥1200" and the outline source
  const legend = page.getByTestId("map-legend");
  await expect(legend).toContainText("IVT (kg m⁻¹ s⁻¹)");
  await expect(page.getByTestId("map-legend-ticks")).toHaveText("03006009001200".replace("1200", "≥1200"));
  await expect(legend).toContainText("Natural Earth");
  await expect(page.getByTestId("event-start")).toHaveText("2000-03-10 06:00 UTC");
  await expect(page.getByTestId("event-ivt-max")).toHaveText("350 kg m-1 s-1");
  await expect(page.getByTestId("replay-time")).toHaveText("2000-03-10 06:00 UTC");
  // clock box over the map while the replay is active
  await expect(page.getByTestId("map-clock")).toContainText("2000-03-10 06:00 UTC");
  await expect(page.getByTestId("map-canvas").getByTestId("map-clock")).toBeVisible();
  // the event list is its own card in the card row, not in the layer panel
  await expect(page.getByTestId("event-card")).toContainText("Eventos");
  await expect(page.getByTestId("layer-panel").getByTestId("event-list")).toHaveCount(0);

  // replay: the timeline cursor advances hour by hour
  const frame = () => page.getByTestId("replay-controls").getAttribute("data-frame");
  expect(await frame()).toBe("0");
  const left0 = await page.getByTestId("timeline-detail-cursor").evaluate((el) => (el as HTMLElement).style.left);
  await page.getByTestId("replay-play").click();
  await expect(page.getByTestId("replay-controls")).toHaveAttribute("data-frame", "3"); // last of 4 frames
  await expect(page.getByTestId("replay-controls")).toHaveAttribute("data-playing", "false");
  const left3 = await page.getByTestId("timeline-detail-cursor").evaluate((el) => (el as HTMLElement).style.left);
  expect(parseFloat(left3)).toBeGreaterThan(parseFloat(left0));
  await expect(page.getByTestId("replay-time")).toHaveText("2000-03-10 09:00 UTC");

  // step back and use the slider
  await page.getByTestId("replay-back").click();
  await expect(page.getByTestId("replay-controls")).toHaveAttribute("data-frame", "2");
  await page.getByTestId("replay-slider").fill("1");
  await expect(page.getByTestId("replay-controls")).toHaveAttribute("data-frame", "1");

  // inspect: click the raster at the view center; hour 1 of the fake field is 200 + 50 = 250
  const box = (await page.getByTestId("map-canvas").boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByTestId("cell-value")).toHaveText("250 kg m-1 s-1");
  await expect(page.getByTestId("cell-where")).toContainText("2000-03-10 07:00 UTC");

  // the value follows the hour
  await page.getByTestId("replay-slider").fill("2");
  await expect(page.getByTestId("cell-value")).toHaveText("300 kg m-1 s-1");

  // second event from the panel list: fields with missing values read "sin dato"
  await page.getByTestId("event-AR-2000-002").click();
  await expect(page.getByTestId("event-ivt-max")).toHaveText("720 kg m-1 s-1");
  await expect(page.getByTestId("inspector-event")).toContainText("sin dato");
  await expect(page.getByTestId("replay-controls")).toHaveAttribute("data-frame", "0");

  // turning the layer off removes marks, raster and replay
  await page.getByTestId("layer-toggle-ar-events").uncheck();
  await expect(canvas).toHaveAttribute("data-deck-layers", /^(ref-[a-z-]+(,|$))+$/);
  await expect(page.getByTestId("map-legend")).toHaveCount(0);
  await expect(page.getByTestId("map-clock")).toHaveCount(0);
  await expect(page.getByTestId("event-card")).toHaveCount(0);
  await expect(page.getByTestId("timeline")).toContainText("Sin serie temporal");

  expect(errors).toEqual([]);
});

test("IVT view toggle: drape over the relief by default, isolines add contour layers, cell readings work in both", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await page.getByTestId("layer-toggle-relief").check();
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /^relief-relief(,|$)/);
  await page.getByTestId("layer-toggle-ar-events").check();
  await page.getByTestId("timeline-event-AR-2000-001").click();
  const canvas = page.getByTestId("map-canvas");
  const drape = page.getByTestId("ivt-view-drape");
  const lines = page.getByTestId("ivt-view-isolines");
  await expect(canvas).toHaveAttribute("data-deck-layers", /^relief-relief,ivt-ar-events,ref-/);
  await expect(drape).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("map-legend-bar")).toBeVisible();

  // drape: the cells carry no fill but still answer the click (hour 1 of the fake field is 250)
  await page.getByTestId("replay-slider").fill("1");
  const box = (await canvas.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByTestId("cell-value")).toHaveText("250 kg m-1 s-1");

  // isolines: contour layers (halo + line) sit above the raster and below the reference outlines
  await lines.click();
  await expect(lines).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("map-legend-levels")).toContainText("1000");
  await expect(canvas).toHaveAttribute(
    "data-deck-layers",
    /^relief-relief,ivt-ar-events,ivt-contours-halo-ar-events,ivt-contours-ar-events,ref-/,
  );
  await page.getByTestId("replay-slider").fill("2");
  await expect(page.getByTestId("cell-value")).toHaveText("300 kg m-1 s-1");

  // back to drape: contours gone
  await drape.click();
  await expect(canvas).not.toHaveAttribute("data-deck-layers", /ivt-contours/);

  expect(errors).toEqual([]);
});

test("ENSO panel: opens in the detail card with the F1.8 table, source and caveats, switches season and closes", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.setViewportSize({ width: 1400, height: 820 });
  await page.goto("/");
  await expect(page.getByTestId("enso-open")).toHaveCount(0);
  await page.getByTestId("layer-toggle-ar-events").check();
  await page.getByTestId("enso-open").click();

  const panel = page.getByTestId("enso-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("enso-tab-DJF")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("enso-row-ivt_mean")).toContainText("527 ± 132 (n=14)");
  await expect(page.getByTestId("enso-row-ar_share")).toContainText("2,2 ± 0,5 (n=14)");
  await expect(page.getByTestId("enso-years")).toContainText("El Niño 14 · Neutro 18 · La Niña 14");
  await expect(page.getByTestId("enso-source")).toContainText("Estadísticas ENSO falsas de prueba");
  await expect(page.getByTestId("enso-caveats")).toContainText("Ninguna diferencia Niño − Niña mantiene p BH < 0,05");
  await expect(page.getByTestId("enso-caveats")).toContainText("no es robusto a la elección del polígono");

  await page.getByTestId("enso-tab-JJA").click();
  await expect(page.getByTestId("enso-row-ar_share")).toContainText("sin dato (n=14)");
  await page.getByTestId("enso-tab-SON").click();
  await expect(page.getByTestId("enso-tab-SON")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("enso-row-ivt_mean")).toContainText("0,0312");

  // the inspector keeps fitting without scrolling and the panel sits in the card row under the map
  const inspector = page.getByTestId("inspector");
  expect(await inspector.evaluate((el) => el.scrollHeight <= el.clientHeight)).toBe(true);
  await expect(page.getByTestId("cards-row").getByTestId("detail-card")).toContainText("Ríos atmosféricos y ENSO");
  const map = (await page.getByTestId("map-canvas").boundingBox())!;
  const box = (await panel.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(map.y + map.height);
  expect(box.x + box.width).toBeLessThanOrEqual(map.x + map.width);

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);

  // narrow screen: the detail card takes the map width
  await page.setViewportSize({ width: 600, height: 820 });
  await page.getByTestId("drawer-toggle-layers").click();
  await page.getByTestId("enso-open").click();
  await page.getByTestId("drawer-scrim").click({ position: { x: 560, y: 100 } }); // right of the drawer
  const narrowMap = (await page.getByTestId("map-canvas").boundingBox())!;
  const narrow = (await page.getByTestId("detail-card").boundingBox())!;
  expect(narrow.width).toBeGreaterThan(narrowMap.width - 24);

  expect(errors).toEqual([]);
});

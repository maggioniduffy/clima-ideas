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
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", "ivt-ar-events");
  await expect(page.getByTestId("event-start")).toHaveText("2000-03-10 06:00 UTC");
  await expect(page.getByTestId("event-ivt-max")).toHaveText("350 kg m-1 s-1");
  await expect(page.getByTestId("replay-time")).toHaveText("2000-03-10 06:00 UTC");

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
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", "");
  await expect(page.getByTestId("timeline")).toContainText("Sin serie temporal");

  expect(errors).toEqual([]);
});

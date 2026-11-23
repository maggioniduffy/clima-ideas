import { expect, test, setLayer } from "./fixtures/test";

const box = async (loc: import("@playwright/test").Locator) => {
  const b = await loc.boundingBox();
  if (!b) throw new Error("not visible");
  return b;
};
const intersects = (a: { x: number; y: number; width: number; height: number }, b: typeof a) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

test("timeline: the AR replay and the storm replay stack as separate rows and never overlap", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLayer(page, "ar-events", true);
  await page.getByTestId("year-expand-2000").click();
  await page.getByTestId("month-expand-2000-03").click();
  await page.getByTestId("timeline-event-AR-2000-001").click();
  await setLayer(page, "convection-idf", true);

  const conv = page.getByTestId("convection-replay");
  const ar = page.getByTestId("replay-controls");
  const track = page.getByTestId("timeline-track");
  const slot = page.getByTestId("timeline-slot");
  await expect(conv).toBeVisible();
  await expect(ar).toBeVisible();
  await expect(page.getByTestId("rain-controls")).toBeVisible();
  await expect(track).toBeVisible();

  const [c, a, t, s] = [await box(conv), await box(ar), await box(track), await box(slot)];
  expect(intersects(c, a)).toBe(false);
  expect(intersects(c, t)).toBe(false);
  expect(c.y + c.height).toBeLessThanOrEqual(a.y + 0.5); // storm replay row above the AR row
  // the strip grew to hold both rows, and its card shape is the tall one
  for (const r of [c, a, t]) {
    expect(r.y).toBeGreaterThanOrEqual(s.y - 0.5);
    expect(r.y + r.height).toBeLessThanOrEqual(s.y + s.height + 0.5);
  }
  await expect(slot).toHaveAttribute("data-tall", "");
});

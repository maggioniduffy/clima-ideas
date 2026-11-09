import { expect, test } from "@playwright/test";

const regions = ["topbar", "layer-panel", "map-canvas", "inspector", "timeline"];

test("shell layout is fixed across themes without reload", async ({ page }) => {
  await page.goto("/");
  for (const id of regions) await expect(page.getByTestId(id)).toBeVisible();
  await page.evaluate(() => {
    (window as unknown as { __marker: number }).__marker = 42;
  });

  const boxes = async () =>
    Object.fromEntries(
      await Promise.all(regions.map(async (id) => [id, await page.getByTestId(id).boundingBox()] as const)),
    );
  const bg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const theme = () => page.evaluate(() => document.documentElement.dataset.theme);

  const themeBefore = await theme();
  const bgBefore = await bg();
  const boxesBefore = await boxes();

  await page.getByRole("button", { name: "Cambiar tema" }).click();

  expect(await theme()).not.toBe(themeBefore);
  expect(await bg()).not.toBe(bgBefore);
  expect(await boxes()).toEqual(boxesBefore);
  expect(await page.evaluate(() => (window as unknown as { __marker: number }).__marker)).toBe(42);
});

test("narrow layout: map uses the width and the layer drawer opens", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toBeVisible();
  expect((await canvas.boundingBox())!.width).toBeGreaterThan(300);
  for (const sep of await page.getByRole("separator").all()) await expect(sep).toBeHidden();

  const toggle = page.getByTestId("drawer-toggle-layers");
  await expect(page.getByTestId("layer-panel")).toBeHidden();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("layer-panel")).toBeVisible();
  await page.getByTestId("drawer-toggle-inspector").click();
  await expect(page.getByTestId("inspector")).toBeVisible();
  await expect(page.getByTestId("layer-panel")).toBeHidden();
});

test("inspector handle resizes the panel, the canvas follows and the width persists", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 800 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const inspector = page.getByTestId("inspector");
  const canvas = page.getByTestId("map-canvas");
  const w0 = (await inspector.boundingBox())!.width;
  const c0 = (await canvas.boundingBox())!.width;
  const handle = page.getByRole("separator", { name: "Ancho del panel de detalle" });
  const hb = (await handle.boundingBox())!;
  const x = hb.x + hb.width / 2;
  const y = hb.y + hb.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - 100, y, { steps: 5 });
  await page.mouse.move(x - 200, y, { steps: 5 });
  await page.mouse.up();

  const w1 = (await inspector.boundingBox())!.width;
  expect(Math.abs(w1 - (w0 + 200))).toBeLessThanOrEqual(2);
  const cb = (await canvas.boundingBox())!;
  expect(Math.abs(cb.width - (c0 - 200))).toBeLessThanOrEqual(2);
  // deck.gl's canvas follows its container
  const deckW = await page.evaluate(() => document.querySelector<HTMLCanvasElement>('[data-testid="map-canvas"] canvas')!.clientWidth);
  expect(Math.abs(deckW - cb.width)).toBeLessThanOrEqual(2);

  await page.reload();
  expect(Math.abs((await inspector.boundingBox())!.width - w1)).toBeLessThanOrEqual(1);
  await page.getByRole("separator", { name: "Ancho del panel de detalle" }).dblclick();
  expect(Math.abs((await inspector.boundingBox())!.width - w0)).toBeLessThanOrEqual(1);
});

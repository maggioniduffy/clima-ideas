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
  // no inspector drawer: the card row stacks under the map and the page scrolls
  await expect(page.getByTestId("drawer-toggle-inspector")).toHaveCount(0);
  await page.keyboard.press("Escape");
  const inspector = page.getByTestId("inspector");
  await inspector.scrollIntoViewIfNeeded();
  await expect(inspector).toBeVisible();
  expect((await inspector.boundingBox())!.y).toBeGreaterThan(0);
  const mapBox = (await canvas.boundingBox())!;
  const scrollY = await page.evaluate(() => window.scrollY);
  expect((await inspector.boundingBox())!.y + scrollY).toBeGreaterThanOrEqual(mapBox.y + scrollY + mapBox.height);
});

test("card-row handle resizes the row, the map follows and the height persists", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 1000 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const row = page.getByTestId("cards-row");
  const canvas = page.getByTestId("map-canvas");
  expect(await page.getByTestId("inspector").evaluate((el) => el.parentElement!.dataset.testid)).toBe("cards-row");
  const h0 = (await row.boundingBox())!.height;
  const c0 = (await canvas.boundingBox())!.height;
  const handle = page.getByRole("separator", { name: "Alto del panel de detalle" });
  const hb = (await handle.boundingBox())!;
  const x = hb.x + hb.width / 2;
  const y = hb.y + hb.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y - 50, { steps: 5 });
  await page.mouse.move(x, y - 100, { steps: 5 });
  await page.mouse.up();

  const h1 = (await row.boundingBox())!.height;
  expect(Math.abs(h1 - (h0 + 100))).toBeLessThanOrEqual(2);
  const cb = (await canvas.boundingBox())!;
  expect(Math.abs(cb.height - (c0 - 100))).toBeLessThanOrEqual(2);
  // deck.gl's canvas follows its container
  const deckH = await page.evaluate(() => document.querySelector<HTMLCanvasElement>('[data-testid="map-canvas"] canvas')!.clientHeight);
  expect(Math.abs(deckH - cb.height)).toBeLessThanOrEqual(2);

  await page.reload();
  expect(Math.abs((await row.boundingBox())!.height - h1)).toBeLessThanOrEqual(1);
  await page.getByRole("separator", { name: "Alto del panel de detalle" }).dblclick();
  expect(Math.abs((await row.boundingBox())!.height - h0)).toBeLessThanOrEqual(1);
});

test("dragging the layers handle past its minimum hides the panel, the map grows, and it survives a reload", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const layers = page.getByTestId("layer-panel");
  const canvas = page.getByTestId("map-canvas");
  const handle = page.getByRole("separator", { name: "Ancho del panel de capas" });
  await expect(layers).toBeVisible();
  const c0 = (await canvas.boundingBox())!.width;
  const hb = (await handle.boundingBox())!;
  const x = hb.x + hb.width / 2;
  const y = hb.y + hb.height / 2;

  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - 100, y, { steps: 5 });
  await page.mouse.move(x - 300, y, { steps: 5 });
  await page.mouse.up();

  await expect(layers).toBeHidden();
  await expect(handle).toHaveAttribute("aria-valuenow", "0");
  await expect(handle).toHaveAttribute("aria-valuemin", "0");
  const cb = (await canvas.boundingBox())!;
  expect(cb.width).toBeGreaterThan(c0 + 200);
  const deckW = await page.evaluate(() => document.querySelector<HTMLCanvasElement>('[data-testid="map-canvas"] canvas')!.clientWidth);
  expect(Math.abs(deckW - cb.width)).toBeLessThanOrEqual(2);

  await page.reload();
  await expect(layers).toBeHidden();
  await expect(handle).toHaveAttribute("aria-valuenow", "0");

  // drag back out: the panel returns from its minimum upward
  const hb2 = (await handle.boundingBox())!;
  const x2 = hb2.x + hb2.width / 2;
  const y2 = hb2.y + hb2.height / 2;
  await page.mouse.move(x2, y2);
  await page.mouse.down();
  await page.mouse.move(x2 + 100, y2, { steps: 5 });
  await page.mouse.move(x2 + 240, y2, { steps: 5 });
  await page.mouse.up();
  await expect(layers).toBeVisible();
  expect(Math.abs((await canvas.boundingBox())!.width - c0)).toBeLessThanOrEqual(30);

  // keyboard: Home collapses, Enter restores the default
  await handle.focus();
  await page.keyboard.press("Home");
  await expect(layers).toBeHidden();
  await page.keyboard.press("Enter");
  await expect(layers).toBeVisible();
  expect(Math.abs((await canvas.boundingBox())!.width - c0)).toBeLessThanOrEqual(1);
});

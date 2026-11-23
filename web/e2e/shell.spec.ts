import { expect, test } from "./fixtures/test";

const regions = ["topbar", "layer-panel", "hero", "map-canvas", "inspector", "timeline"];

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

test("narrow layout: map uses the width, the layer pills scroll in one row and there is no drawer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toBeVisible();
  expect((await canvas.boundingBox())!.width).toBeGreaterThan(300);
  for (const sep of await page.getByRole("separator").all()) await expect(sep).toBeHidden();

  await expect(page.getByTestId("drawer-toggle-layers")).toHaveCount(0);
  await expect(page.getByTestId("drawer-scrim")).toHaveCount(0);
  const pills = page.getByTestId("layer-panel");
  await expect(pills).toBeVisible();
  expect(await pills.evaluate((el) => getComputedStyle(el).overflowX)).toBe("auto");
  const tops = await pills.locator("label").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
  expect(tops.length).toBeGreaterThan(0);
  expect(new Set(tops).size).toBe(1); // one row
  // header, h1, then the map
  const top = (await page.getByTestId("topbar").boundingBox())!;
  const hero = (await page.getByTestId("hero").boundingBox())!;
  expect(hero.y).toBeGreaterThanOrEqual(top.y + top.height);
  expect((await canvas.boundingBox())!.y).toBeGreaterThanOrEqual(hero.y + hero.height);
  // no inspector drawer: the card row stacks under the map and the page scrolls
  await expect(page.getByTestId("drawer-toggle-inspector")).toHaveCount(0);
  const inspector = page.getByTestId("inspector");
  await inspector.scrollIntoViewIfNeeded();
  await expect(inspector).toBeVisible();
  expect((await inspector.boundingBox())!.y).toBeGreaterThan(0);
  const mapBox = (await canvas.boundingBox())!;
  const scrollY = await page.evaluate(() => window.scrollY);
  expect((await inspector.boundingBox())!.y + scrollY).toBeGreaterThanOrEqual(mapBox.y + scrollY + mapBox.height);
});

test("desktop layout at 1440x900: map left, panels right, timeline across the bottom", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const map = (await page.getByTestId("map-canvas").boundingBox())!;
  const panels = (await page.getByTestId("panels-slot").boundingBox())!;
  const timeline = (await page.getByTestId("timeline-slot").boundingBox())!;
  const top = (await page.getByTestId("topbar").boundingBox())!;
  expect(map.x + map.width).toBeLessThanOrEqual(panels.x); // map left of the panels
  expect(panels.width).toBeGreaterThanOrEqual(420);
  expect(panels.width).toBeLessThanOrEqual(480);
  expect(map.width).toBeGreaterThan(panels.width * 1.8); // the map takes the remaining width
  expect(map.y).toBeGreaterThanOrEqual(top.y + top.height);
  expect(Math.abs(map.y - panels.y)).toBeLessThanOrEqual(1);
  expect(timeline.y).toBeGreaterThanOrEqual(map.y + map.height); // timeline below both
  expect(timeline.y).toBeGreaterThanOrEqual(panels.y + panels.height);
  expect(Math.abs(timeline.x - map.x)).toBeLessThanOrEqual(1); // and spans the frame width
  expect(Math.abs(timeline.x + timeline.width - (panels.x + panels.width))).toBeLessThanOrEqual(1);
  // the inspector lives in the right column
  for (const id of ["inspector"]) {
    const b = (await page.getByTestId(id).boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(panels.x);
    expect(b.x + b.width).toBeLessThanOrEqual(panels.x + panels.width + 1);
  }
  // the page itself does not scroll
  expect(await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight)).toBeLessThanOrEqual(0);
});

test("the panels handle resizes the column, the map and its canvas follow, and the width persists", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const col = page.getByTestId("panels-slot");
  const canvas = page.getByTestId("map-canvas");
  const w0 = (await col.boundingBox())!.width;
  const c0 = (await canvas.boundingBox())!.width;
  const hb = (await page.getByRole("separator", { name: "Ancho de los paneles" }).boundingBox())!;
  const x = hb.x + hb.width / 2;
  const y = hb.y + hb.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - 50, y, { steps: 5 });
  await page.mouse.move(x - 100, y, { steps: 5 });
  await page.mouse.up();
  const w1 = (await col.boundingBox())!.width;
  expect(Math.abs(w1 - (w0 + 100))).toBeLessThanOrEqual(2);
  const cb = (await canvas.boundingBox())!;
  expect(Math.abs(cb.width - (c0 - 100))).toBeLessThanOrEqual(2);
  // deck.gl's canvas follows its container after the layout change
  const deckW = await page.evaluate(() => document.querySelector<HTMLCanvasElement>('[data-testid="map-canvas"] canvas')!.clientWidth);
  expect(Math.abs(deckW - cb.width)).toBeLessThanOrEqual(2);
  await page.reload();
  expect(Math.abs((await col.boundingBox())!.width - w1)).toBeLessThanOrEqual(1);
  await page.getByRole("separator", { name: "Ancho de los paneles" }).dblclick();
  expect(Math.abs((await col.boundingBox())!.width - w0)).toBeLessThanOrEqual(1);
});

test("dragging the panels handle past its minimum hides the column, the map grows, and it survives a reload", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const col = page.getByTestId("panels-slot");
  const canvas = page.getByTestId("map-canvas");
  const handle = page.getByRole("separator", { name: "Ancho de los paneles" });
  await expect(col).toBeVisible();
  const c0 = (await canvas.boundingBox())!.width;
  const hb = (await handle.boundingBox())!;
  const x = hb.x + hb.width / 2;
  const y = hb.y + hb.height / 2;

  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 100, y, { steps: 5 });
  await page.mouse.move(x + 400, y, { steps: 5 });
  await page.mouse.up();

  await expect(col).toBeHidden();
  await expect(handle).toHaveAttribute("aria-valuenow", "0");
  await expect(handle).toHaveAttribute("aria-valuemin", "0");
  const cb = (await canvas.boundingBox())!;
  expect(cb.width).toBeGreaterThan(c0 + 300);
  const deckW = await page.evaluate(() => document.querySelector<HTMLCanvasElement>('[data-testid="map-canvas"] canvas')!.clientWidth);
  expect(Math.abs(deckW - cb.width)).toBeLessThanOrEqual(2);

  await page.reload();
  await expect(col).toBeHidden();
  await expect(handle).toHaveAttribute("aria-valuenow", "0");

  // keyboard: Enter restores the default, Home collapses again
  await handle.focus();
  await page.keyboard.press("Enter");
  await expect(col).toBeVisible();
  expect(Math.abs((await canvas.boundingBox())!.width - c0)).toBeLessThanOrEqual(1);
  await page.keyboard.press("Home");
  await expect(col).toBeHidden();
});

test("a maximized timeline at 900 px high does not make the page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("panel-sizes", JSON.stringify({ panels: 440, timeline: 420 })));
  await page.reload();
  await expect(page.getByTestId("timeline")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight)).toBeLessThanOrEqual(0);
});

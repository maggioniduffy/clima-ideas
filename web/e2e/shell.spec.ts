import { expect, test, openLayerMenu } from "./fixtures/test";

const regions = ["topbar", "menu-toggle", "map-canvas", "inspector", "timeline"];

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

test("narrow layout: the map is on top at full width, the menu floats top-left, the panels stack below and nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toBeVisible();
  const map = (await canvas.boundingBox())!;
  expect(map.width).toBeGreaterThanOrEqual(389);
  expect(map.y).toBeLessThanOrEqual(1);
  for (const sep of await page.getByRole("separator").all()) await expect(sep).toBeHidden();
  await expect(page.getByTestId("drawer-toggle-layers")).toHaveCount(0);
  await expect(page.getByTestId("drawer-scrim")).toHaveCount(0);

  // the menu bar floats over the map, top-left
  const top = (await page.getByTestId("topbar").boundingBox())!;
  expect(top.x).toBeLessThanOrEqual(16);
  expect(top.y).toBeLessThanOrEqual(16);
  expect(top.x + top.width).toBeLessThanOrEqual(390);
  expect(top.y + top.height).toBeLessThanOrEqual(map.y + map.height);
  const menu = await openLayerMenu(page);
  const mb = (await menu.boundingBox())!;
  expect(mb.x).toBeGreaterThanOrEqual(0);
  expect(mb.x + mb.width).toBeLessThanOrEqual(390);
  await page.getByTestId("menu-toggle").click();

  // the card column stacks under the map and the page scrolls vertically only
  const inspector = page.getByTestId("inspector");
  await inspector.scrollIntoViewIfNeeded();
  await expect(inspector).toBeVisible();
  const scrollY = await page.evaluate(() => window.scrollY);
  expect((await inspector.boundingBox())!.y + scrollY).toBeGreaterThanOrEqual(map.y + map.height - 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
});

test("desktop layout at 1440x900: the map fills the window; the panels and the timeline float 16 px from its edges", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const map = (await page.getByTestId("map-canvas").boundingBox())!;
  const panels = (await page.getByTestId("panels-slot").boundingBox())!;
  const timeline = (await page.getByTestId("timeline-slot").boundingBox())!;
  const top = (await page.getByTestId("topbar").boundingBox())!;
  expect(map).toMatchObject({ x: 0, y: 0, width: 1440, height: 900 }); // edge to edge: no top bar, no hero, no frame
  expect(Math.abs(top.x - 16)).toBeLessThanOrEqual(1);
  expect(Math.abs(top.y - 16)).toBeLessThanOrEqual(1);
  expect(top.height).toBeGreaterThanOrEqual(50);
  expect(top.height).toBeLessThanOrEqual(54);
  expect(panels.width).toBeGreaterThanOrEqual(420);
  expect(panels.width).toBeLessThanOrEqual(480);
  expect(Math.abs(panels.x + panels.width - (1440 - 16))).toBeLessThanOrEqual(1);
  expect(Math.abs(panels.y - 16)).toBeLessThanOrEqual(1);
  expect(Math.abs(panels.y + panels.height - (900 - 16))).toBeLessThanOrEqual(1);
  expect(Math.abs(timeline.x - 16)).toBeLessThanOrEqual(1);
  expect(Math.abs(timeline.y + timeline.height - (900 - 16))).toBeLessThanOrEqual(1);
  expect(timeline.x + timeline.width).toBeLessThanOrEqual(panels.x - 15); // 16 px gap between timeline and panel
  // glass: translucent background with a blur
  const glass = await page.getByTestId("panels-slot").evaluate((el) => {
    const c = getComputedStyle(el);
    return { bg: c.backgroundColor, blur: c.backdropFilter, radius: c.borderTopLeftRadius };
  });
  expect(glass.bg).toMatch(/rgba\(/);
  expect(glass.blur).toContain("blur");
  expect(glass.radius).toBe("24px");
  // the inspector lives in the right column
  for (const id of ["inspector"]) {
    const b = (await page.getByTestId(id).boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(panels.x);
    expect(b.x + b.width).toBeLessThanOrEqual(panels.x + panels.width + 1);
  }
  // the page itself does not scroll
  expect(await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight)).toBeLessThanOrEqual(0);
});

test("the layer menu is closed by default, opens under the menu bar and closes with Escape and outside clicks", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByTestId("layer-menu")).toHaveCount(0);
  const menu = await openLayerMenu(page);
  const bar = (await page.getByTestId("topbar").boundingBox())!;
  const mb = (await menu.boundingBox())!;
  expect(mb.y).toBeGreaterThanOrEqual(bar.y + bar.height);
  expect(Math.abs(mb.width - 340)).toBeLessThanOrEqual(2);
  await expect(page.getByTestId("layer-item-relief")).toHaveCount(0);
  await expect(page.getByTestId("menu-link-smn")).toHaveAttribute("href", "https://www.smn.gob.ar/alertas");
  await expect(page.getByTestId("menu-link-aic")).toHaveAttribute("href", "https://www.aic.gob.ar");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("layer-menu")).toHaveCount(0);
  await openLayerMenu(page);
  await page.mouse.click(700, 500);
  await expect(page.getByTestId("layer-menu")).toHaveCount(0);
});

test("the panels handle resizes the column, the map keeps filling the window, and the width persists", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const col = page.getByTestId("panels-slot");
  const canvas = page.getByTestId("map-canvas");
  const w0 = (await col.boundingBox())!.width;
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
  expect(cb.width).toBe(1400);
  // deck.gl's canvas keeps matching its container
  const deckW = await page.evaluate(() => document.querySelector<HTMLCanvasElement>('[data-testid="map-canvas"] canvas')!.clientWidth);
  expect(Math.abs(deckW - cb.width)).toBeLessThanOrEqual(2);
  await page.reload();
  expect(Math.abs((await col.boundingBox())!.width - w1)).toBeLessThanOrEqual(1);
  await page.getByRole("separator", { name: "Ancho de los paneles" }).dblclick();
  expect(Math.abs((await col.boundingBox())!.width - w0)).toBeLessThanOrEqual(1);
});

test("dragging the panels handle past its minimum hides the column, and it survives a reload", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("panel-sizes"));
  await page.reload();
  const col = page.getByTestId("panels-slot");
  const canvas = page.getByTestId("map-canvas");
  const handle = page.getByRole("separator", { name: "Ancho de los paneles" });
  await expect(col).toBeVisible();
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
  expect(cb.width).toBe(1400);
  const deckW = await page.evaluate(() => document.querySelector<HTMLCanvasElement>('[data-testid="map-canvas"] canvas')!.clientWidth);
  expect(Math.abs(deckW - cb.width)).toBeLessThanOrEqual(2);

  await page.reload();
  await expect(col).toBeHidden();
  await expect(handle).toHaveAttribute("aria-valuenow", "0");

  // keyboard: Enter restores the default, Home collapses again
  await handle.focus();
  await page.keyboard.press("Enter");
  await expect(col).toBeVisible();
  expect(Math.abs((await col.boundingBox())!.width - 440)).toBeLessThanOrEqual(1);
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

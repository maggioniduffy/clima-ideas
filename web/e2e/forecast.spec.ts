import { expect, test } from "@playwright/test";

test("forecast outlook: prediction, state, history, notices and official links", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await page.getByTestId("layer-toggle-forecast-outlook").check();
  const panel = page.getByTestId("forecast-panel");
  await expect(panel).toBeVisible();

  // notices and the three official links, with their hrefs
  await expect(page.getByTestId("forecast-official")).toContainText("No es una alerta oficial");
  await expect(page.getByTestId("forecast-audience")).toContainText("usuarios técnicos");
  const links = page.getByTestId("forecast-notices").getByRole("link");
  await expect(links).toHaveCount(3);
  await expect(links.filter({ hasText: "SMN" })).toHaveAttribute("href", /^https:\/\/[^/]*smn\.gob\.ar/);
  await expect(links.filter({ hasText: "AIC" })).toHaveAttribute("href", /^https:\/\/[^/]*aic\.go[bv]\.ar/);
  await expect(links.filter({ hasText: "Defensa Civil" })).toHaveAttribute("href", /^https:\/\/[^/]*neuquen\.go[bv]\.ar/);
  for (const l of await links.all()) {
    await expect(l).toHaveAttribute("target", "_blank");
    await expect(l).toHaveAttribute("rel", /noopener/);
  }

  // header
  await expect(page.getByTestId("forecast-issued")).toHaveText(/^\d{2}\/\d{2}\/\d{4}$/);
  await expect(page.getByTestId("forecast-model")).not.toBeEmpty();
  await expect(page.getByTestId("forecast-inputs")).toContainText(/≈ \d+ (h|días)|< 1 h/);

  // a prediction, its state and its history
  const table = page.getByTestId("forecast-table");
  await expect(table.getByRole("row")).toHaveCount(11);
  await expect(page.getByTestId("forecast-p-1")).toContainText("%");
  await expect(page.getByTestId("forecast-estado-1")).toHaveText(/Experimental|Perspectiva de riesgo/);
  await expect(page.getByTestId("forecast-history-1")).toContainText("POD");
  await expect(page.getByTestId("forecast-history-1")).toContainText("FAR");
  await expect(page.getByTestId("forecast-hindcast-1")).toContainText("BSS");
  await expect(page.getByTestId("forecast-states")).toContainText("Perspectiva de riesgo");

  // formatted numbers, no doubled period, Estado column header visible in the normal panel
  await expect(page.getByTestId("forecast-panel")).not.toContainText(/\d\.\d{4,}/);
  await expect(page.getByTestId("forecast-source")).not.toContainText("..");
  const estado = table.getByRole("columnheader", { name: "Estado" });
  await expect(estado).toBeVisible();
  const wrapBox = (await page.getByTestId("forecast-table-wrap").boundingBox())!;
  const estadoBox = (await estado.boundingBox())!;
  expect(estadoBox.x + estadoBox.width).toBeLessThanOrEqual(wrapBox.x + wrapBox.width + 1);
  await page.getByTestId("forecast-row-10").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("forecast-row-10")).toBeVisible();

  // region selector
  await page.getByTestId("forecast-region-confluencia").click();
  await expect(panel).toHaveAttribute("data-region", "confluencia");

  // the page never scrolls horizontally, at desktop and at 360 px
  for (const width of [1280, 360]) {
    await page.setViewportSize({ width, height: 900 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(overflow, `page overflow at ${width}px`).toBe(false);
  }
  expect(errors).toEqual([]);
});

for (const [name, size] of [["desktop", { width: 1280, height: 800 }], ["phone", { width: 390, height: 800 }]] as const) {
  test(`right panel expands and collapses (${name})`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.goto("/");
    await page.getByTestId("layer-toggle-forecast-outlook").check().catch(async () => {
      await page.getByRole("button", { name: "Capas" }).click();
      await page.getByTestId("layer-toggle-forecast-outlook").check();
    });
    const btn = page.getByTestId("panel-expand");
    await expect(btn).toHaveAttribute("aria-label", "Expandir panel");
    await expect(btn).toHaveAttribute("aria-expanded", "false");
    await btn.focus();
    await page.keyboard.press("Enter");
    await expect(btn).toHaveAttribute("aria-label", "Contraer panel");
    await expect(btn).toHaveAttribute("aria-expanded", "true");
    const body = (await page.locator(".shell-body").boundingBox())!;
    const panels = (await page.getByTestId("panels-slot").boundingBox())!;
    expect(panels.width).toBeGreaterThanOrEqual(body.width - 20);
    await expect(page.getByRole("columnheader", { name: "Estado" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(btn).toHaveAttribute("aria-expanded", "false");
    const map = (await page.getByTestId("map-canvas").or(page.locator(".shell-canvas")).first().boundingBox())!;
    expect(map.width).toBeGreaterThan(200);
    await btn.click();
    await expect(btn).toHaveAttribute("aria-expanded", "true");
    await btn.click();
    await expect(btn).toHaveAttribute("aria-expanded", "false");
  });
}

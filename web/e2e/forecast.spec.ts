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

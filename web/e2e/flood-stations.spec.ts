import { expect, test } from "@playwright/test";

test("flood stations: pick a station, see the return-period curve and the top floods", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.getByTestId("layer-item-flood-stations")).toContainText("Crecidas: caudal y período de retorno");

  await page.getByTestId("layer-toggle-flood-stations").check();
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /^points-flood-stations(,|$)/);
  await expect(page.getByTestId("inspector-source")).toHaveText("Datos falsos de prueba");

  // the list names stations, not "Punto <id>"
  const list = page.getByTestId("feature-list");
  await expect(list).toContainText("Estación Falsa Natural");
  await expect(list).not.toContainText("Punto");

  await page.getByTestId("feature-1001").click();
  const chart = page.getByTestId("return-period-chart");
  await expect(chart).toBeVisible();
  await expect(page.getByTestId("detail-card").getByTestId("flood-station-panel")).toBeVisible();
  await expect(page.getByTestId("return-period-curve")).toBeVisible();
  await expect(page.getByTestId("return-period-band")).toBeVisible();
  await expect(page.getByTestId("flow-series-chart")).toBeVisible();
  const top = page.getByTestId("top-floods");
  await expect(top.locator("li")).toHaveCount(3);
  await expect(top.locator("li").first()).toContainText("01/03/2002");
  await expect(top.locator("li").first()).toContainText("520 m³/s");
  await expect(top.locator("li").first()).toContainText("T ≈ 22 años");
  await expect(page.getByTestId("flood-no-gev")).toHaveCount(0);

  // the regulated station has no GEV curve
  await page.getByTestId("feature-1002").click();
  await expect(page.getByTestId("flood-no-gev")).toHaveText("Río regulado aguas arriba: sin GEV");
  await expect(page.getByTestId("return-period-curve")).toHaveCount(0);
  await expect(page.getByTestId("top-floods").locator("li").first()).toContainText("140 m³/s");

  // no horizontal scroll in the inspector
  const overflow = await page
    .getByTestId("inspector")
    .evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
});

test("flood card: past event, LSTM forecast with band vs observed, issue day changes the forecast", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await page.getByTestId("layer-toggle-flood-stations").check();
  await page.getByTestId("feature-1001").click();

  const card = page.getByTestId("flood-event-card");
  await card.scrollIntoViewIfNeeded();
  await expect(card.getByRole("heading", { name: "Ficha de crecida" })).toBeVisible();

  // pick a past event
  await card.getByTestId("event-2002-03-01").click();
  await expect(card.getByTestId("event-2002-03-01")).toHaveAttribute("aria-selected", "true");
  await expect(card.getByTestId("event-2002-03-01")).toContainText("01/03/2002 · 520 m³/s");

  // observed line, 90 % band, forecast median, persistence and the caveat are all visible
  await expect(card.getByTestId("event-observed")).toBeVisible();
  await expect(card.getByTestId("event-band")).toBeVisible();
  await expect(card.getByTestId("event-median")).toBeVisible();
  // persistence is a flat dashed line (zero height), so check its path rather than its box
  await expect(card.getByTestId("event-persistence")).toHaveAttribute("d", /^M[\d. ]+L/);
  await expect(card.getByTestId("event-legend")).toContainText("Banda 90 %");
  await expect(card.getByTestId("event-caveat")).toBeVisible();
  await expect(card.getByTestId("event-caveat")).toHaveText(
    "Pronóstico retrospectivo con meteorología observada (ERA5), no pronóstico operativo. Experimental, no es una alerta.",
  );
  await expect(card).toContainText("ERA5 observada, no pronóstico");

  // the forecast follows the issue day
  await expect(card.getByTestId("event-issue-label")).toHaveText("Emitido el día del pico");
  const median0 = await card.getByTestId("event-median").getAttribute("d");
  const band0 = await card.getByTestId("event-band").getAttribute("d");
  await card.getByTestId("event-issue-slider").fill("0");
  await expect(card.getByTestId("event-issue-label")).toHaveText("Emitido 7 días antes del pico");
  await expect(card.getByTestId("event-median")).not.toHaveAttribute("d", median0!);
  await expect(card.getByTestId("event-band")).not.toHaveAttribute("d", band0!);

  // keyboard: arrow keys move the issue day
  await card.getByTestId("event-issue-slider").press("ArrowRight");
  await expect(card.getByTestId("event-issue-label")).toHaveText("Emitido 6 días antes del pico");

  // the station without hindcast has no card
  await page.getByTestId("feature-1002").click();
  await expect(page.getByTestId("flood-no-gev")).toBeVisible();
  await expect(page.getByTestId("flood-event-card")).toHaveCount(0);
  expect(errors).toEqual([]);
});

for (const width of [900, 1360]) {
  test(`flood panel fits its container at ${width} px and keeps text legible`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await page.getByTestId("layer-toggle-flood-stations").check();
    await page.getByTestId("feature-1001").click();
    const card = page.getByTestId("detail-card");
    const chart = page.getByTestId("event-chart");
    await chart.scrollIntoViewIfNeeded();
    await expect(chart).toBeVisible();
    const overflow = await card.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    const cardBox = (await card.boundingBox())!;
    for (const id of ["event-chart", "return-period-chart", "flow-series-chart"]) {
      const box = (await page.getByTestId(id).boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(cardBox.x - 0.5);
      expect(box.x + box.width).toBeLessThanOrEqual(cardBox.x + cardBox.width + 0.5);
    }
    // every tick label lies inside its svg, and the font is at least 12 px
    const bad = await page.locator("svg.flood-chart").evaluateAll((svgs) =>
      svgs.flatMap((svg) => {
        const s = svg.getBoundingClientRect();
        return [...svg.querySelectorAll("text.flood-tick")]
          .filter((t) => {
            const r = t.getBoundingClientRect();
            return r.left < s.left - 0.5 || r.right > s.right + 0.5 || parseFloat(getComputedStyle(t).fontSize) < 12;
          })
          .map((t) => t.textContent);
      }),
    );
    expect(bad).toEqual([]);
  });
}

import { expect, test } from "./fixtures/test";

test("debris: choose a catchment and inspect its panel", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await expect(page.getByTestId("layer-item-debris-catchments")).toHaveAttribute("title", "Aluviones: cuencas chicas");
  await page.getByTestId("layer-toggle-debris-catchments").check();
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /polygons-debris-catchments/);
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", /outlets-debris-catchments/);

  // ranked list, largest peak first; scenario label and legend
  const panel = page.getByTestId("debris-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("debris-scenario-label")).toHaveText("Escenarios de CN (TR-55), no medidos");
  await expect(page.locator('[data-testid^="debris-rank-"]')).toHaveCount(4);
  await expect(page.locator('[data-testid^="debris-rank-"]').first()).toContainText("1. RP5");
  await expect(page.getByTestId("debris-legend")).toBeVisible();
  await expect(page.getByTestId("debris-empty")).toBeVisible();

  // the laminar-flow front (no channel; D8 artifact) is hidden and unranked by default; the toggle shows it
  await expect(page.getByRole("heading", { name: "Mayores caudales pico: 4 de 4 cuencas con cauce" })).toBeVisible();
  const toggle = page.getByTestId("debris-planar-toggle");
  await expect(toggle).not.toBeChecked();
  await expect(page.getByText("Mostrar frentes de escurrimiento laminar (1 cuenca)")).toBeVisible();
  await expect(panel).toHaveAttribute("data-map-shown", "4"); // polygons and dots drawn on the map
  await toggle.check();
  await expect(panel).toHaveAttribute("data-map-shown", "5");
  await expect(page.locator('[data-testid^="debris-rank-"]')).toHaveCount(4); // shown but still unranked
  await toggle.uncheck();
  await expect(panel).toHaveAttribute("data-map-shown", "4");

  // changing T or CN reorders / rescales
  await page.getByTestId("debris-t-100").click();
  await expect(page.getByTestId("debris-t-100")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("debris-cn-hsg-d").click();
  await expect(page.getByTestId("debris-cn-hsg-d")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("debris-t-10").click();
  await page.getByTestId("debris-cn-hsg-c").click();

  // choose a catchment: its panel shows geometry, peaks per T with CN range, critical duration and caveats
  const canvas = page.getByTestId("map-canvas");
  const view = async () => ({
    zoom: Number(await canvas.getAttribute("data-view-zoom")),
    center: await canvas.getAttribute("data-view-center"),
  });
  const before = await view();
  await page.getByTestId("debris-rank-2").click();
  // the map flies to the chosen catchment (zoom in, centre moves)
  await expect.poll(async () => (await view()).zoom, { timeout: 8000 }).toBeGreaterThan(before.zoom + 2);
  expect((await view()).center).not.toBe(before.center);
  const detail = page.getByTestId("debris-detail");
  await expect(detail).toBeVisible();
  await expect(page.getByTestId("debris-target")).toHaveText("RP7");
  await expect(page.getByTestId("debris-area")).toContainText("4 km²");
  await expect(page.getByTestId("debris-slope")).toContainText("5°");
  await expect(page.getByTestId("debris-relief")).toContainText("120 m");
  await expect(page.getByTestId("debris-flowpath")).toContainText("4.200 m");
  await expect(page.getByTestId("debris-dinf-area")).toContainText("3,9 km²");
  await expect(page.getByTestId("debris-prominence")).toContainText("12,5 veces");
  await expect(page.getByTestId("debris-channel-note")).toContainText("criterio propio, sin verificar");
  await expect(page.locator('[data-testid^="debris-peak-row-"]')).toHaveCount(6);
  await expect(page.getByTestId("debris-peak-10")).toHaveText("3,45");
  await expect(page.getByTestId("debris-range-10")).toContainText("–");
  await expect(page.getByTestId("debris-crit-10")).toContainText("h");
  await expect(page.getByTestId("debris-peak-row-100")).toContainText("T 100†");
  await expect(page.getByTestId("debris-peak-row-10")).toHaveAttribute("data-current", "true");
  const caveats = page.getByTestId("debris-caveats");
  await expect(caveats).toContainText("piso de IMERG");
  await expect(caveats).toContainText("TR-55");
  await expect(caveats).toContainText("bardas patagónicas");
  await expect(caveats).toContainText("No es un sistema de alerta oficial");
  await expect(page.getByTestId("debris-source")).toContainText("2000/01–2024/25");
  await expect(page.getByTestId("debris-source")).toContainText("2021-01-01/2021-12-31");

  // another catchment replaces the panel content
  const second = await view();
  await page.getByTestId("debris-rank-0").click();
  await expect.poll(async () => (await view()).center, { timeout: 8000 }).not.toBe(second.center);
  await expect(page.getByTestId("debris-target")).toHaveText("RP5");
  await expect(page.getByTestId("debris-area")).toContainText("12 km²");

  const overflow = await page.getByTestId("detail-card").evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  // turning the layer off removes map layers and panel
  await page.getByTestId("layer-toggle-debris-catchments").uncheck();
  await expect(page.getByTestId("debris-panel")).toHaveCount(0);
  await expect(page.getByTestId("map-canvas")).not.toHaveAttribute("data-deck-layers", /debris-catchments/);
  expect(errors).toEqual([]);
});

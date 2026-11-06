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

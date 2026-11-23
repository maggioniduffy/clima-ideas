import { expect, test, setLayer, openLayerMenu, closeLayerMenu } from "./fixtures/test";

test("hindcast verification: choose model, event and lead; gate, analogs, notices and links", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await openLayerMenu(page);
  await expect(page.getByTestId("layer-item-hindcast-verification")).toHaveAttribute("title", "Verificación retrospectiva de pronósticos");
  await closeLayerMenu(page);
  await setLayer(page, "hindcast-verification", true);
  await expect(page.getByTestId("inspector-source")).toHaveText("GEFS, IFS y AIFS falsos de prueba; observado ERA5 falso de prueba");

  const panel = page.getByTestId("hindcast-panel");
  await expect(panel).toBeVisible();
  // always visible: source and period from the manifest, "Retrospectivo", not an official alert system, official links
  await expect(page.getByTestId("hindcast-source")).toContainText("falsos de prueba");
  await expect(page.getByTestId("hindcast-source")).toContainText("2001-05-02/2025-06-05");
  await expect(page.getByTestId("hindcast-retro")).toContainText("Retrospectivo");
  await expect(page.getByTestId("hindcast-not-alert")).toContainText("No es un sistema de alerta oficial");
  await expect(page.getByTestId("hindcast-link-smn")).toHaveAttribute("href", "https://www.smn.gob.ar/alertas");
  await expect(page.getByTestId("hindcast-link-aic")).toHaveAttribute("href", "https://www.aic.gob.ar");
  await expect(page.getByTestId("hindcast-link-civil")).toHaveAttribute("href", "https://www.neuquen.gov.ar/defensacivil/");
  await expect(page.getByTestId("hindcast-license")).toContainText("CC0");

  // default: GEFS, first event, lead 1
  await expect(panel).toHaveAttribute("data-model", "gefs-reforecast");
  await expect(panel).toHaveAttribute("data-event", "AR-2001-001");
  await expect(page.getByTestId("hindcast-fc-mean")).toHaveText("9,4 mm");
  await expect(page.getByTestId("hindcast-fc-range")).toHaveText("8,4 a 10,4 mm");
  await expect(page.getByTestId("hindcast-obs")).toHaveText("11,9 mm");
  await expect(page.getByTestId("hindcast-forecast-chart")).toBeVisible();
  await expect(page.getByTestId("hindcast-skill-chart")).toBeVisible();
  await expect(page.getByTestId("hindcast-skill-crpss")).toHaveText("0,80 (0,68 a 0,90)");

  // lead: values, markers and the gate table follow
  await page.getByTestId("hindcast-lead-7").click();
  await expect(panel).toHaveAttribute("data-lead", "7");
  await expect(page.getByTestId("hindcast-fc-mean")).toHaveText("5,6 mm");
  await expect(page.getByTestId("hindcast-forecast-marker")).toHaveAttribute("data-lead", "7");
  await expect(page.getByTestId("hindcast-skill-marker")).toHaveAttribute("data-lead", "7");
  await expect(page.getByTestId("hindcast-skill-crpss")).toHaveText("0,44 (0,26 a 0,54)");
  await expect(page.getByTestId("hindcast-gate-table")).toHaveAttribute("data-lead", "7");
  await expect(page.getByTestId("hindcast-gate-status-cordillera_norte")).toHaveText("Experimental");
  await expect(page.getByTestId("hindcast-gate-status-confluencia")).toHaveText("Experimental");
  await page.getByTestId("hindcast-lead-2").click();
  await expect(page.getByTestId("hindcast-gate-status-cordillera_norte")).toHaveText("pasa hindcast (espera la temporada prospectiva)");
  await expect(page.getByTestId("hindcast-gate-status-confluencia")).toHaveText("Experimental");
  await expect(page.getByTestId("hindcast-gate-bssClim-cordillera_norte")).toContainText("(");
  await expect(page.getByTestId("hindcast-gate-note")).toContainText("percentil 95");

  // event: forecast and observed change; an unpublished lead reads as such
  await page.getByTestId("hindcast-event").selectOption("AR-2015-002");
  await expect(panel).toHaveAttribute("data-event", "AR-2015-002");
  await expect(page.getByTestId("hindcast-obs")).toHaveText("20,3 mm");
  await expect(page.getByTestId("hindcast-valid")).toHaveText("10/04/2015");
  await page.getByTestId("hindcast-event").selectOption("AR-2007-003");
  await page.getByTestId("hindcast-lead-3").click();
  await expect(page.getByTestId("hindcast-fc-mean")).toHaveText("sin pronóstico publicado");
  await expect(page.getByTestId("hindcast-forecast-marker")).toHaveCount(0);

  // analogs: the 10 analogs of an event that has them; nothing for one that has not
  await page.getByTestId("hindcast-event").selectOption("AR-2001-001");
  await expect(page.getByTestId("hindcast-analogs").locator("tbody tr")).toHaveCount(10);
  await expect(page.getByTestId("hindcast-analog-ar-0")).toHaveText("Sí (AR-1985-001)");
  await expect(page.getByTestId("hindcast-analog-ar-1")).toHaveText("No");
  await expect(page.getByTestId("hindcast-analogs-note")).toContainText("3 de 10 fueron río atmosférico");
  await page.getByTestId("hindcast-event").selectOption("AR-2007-003");
  await expect(page.getByTestId("hindcast-analogs")).toHaveCount(0);

  // model: its own events, no ensemble range for a single member, its own skill
  await page.getByTestId("hindcast-model-aifs").click();
  await expect(panel).toHaveAttribute("data-model", "aifs");
  await expect(panel).toHaveAttribute("data-event", "AR-2024-002");
  await expect(page.getByTestId("hindcast-event").locator("option")).toHaveCount(2);
  await page.getByTestId("hindcast-lead-1").click();
  await expect(page.getByTestId("hindcast-fc-mean")).toHaveText("15,2 mm");
  await expect(page.getByTestId("hindcast-fc-range")).toHaveText("Un solo miembro: sin rango");
  await expect(page.getByTestId("hindcast-forecast-band")).toHaveCount(0);
  await expect(page.getByTestId("hindcast-skill-crpss")).toHaveText("0,50 (0,38 a 0,60)");
  await expect(page.getByTestId("hindcast-analogs")).toBeVisible(); // AR-2024-002 has analogs

  // AIFS against IFS, collapsed by default
  const aifs = page.getByTestId("hindcast-aifs");
  await expect(aifs).not.toHaveAttribute("open", "");
  await aifs.locator("summary").click();
  await expect(page.getByTestId("hindcast-aifs-table").locator("tbody tr")).toHaveCount(3);

  // no horizontal overflow of the page; no console errors
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
});

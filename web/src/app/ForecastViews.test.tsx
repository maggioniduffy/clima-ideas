import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import type { Highflow, Outlook, Seasonal } from "../layers/forecast";
import type { ForecastState } from "../layers/useForecastOutlook";
import { ForecastPanel } from "./ForecastPanel";
import { HighflowView } from "./HighflowView";
import { monthLabel, SeasonalView } from "./SeasonalView";

const fixture = JSON.parse(readFileSync("e2e/fixtures/processed/forecast-outlook/outlook.json", "utf8")) as Outlook;

const panel = (o: Outlook = fixture) =>
  render(<ForecastPanel state={{ status: "ready", outlook: o } as ForecastState} source="Fuente X" period="2026-01-01/2026-01-10" license="CC0" />);

test("view tabs: three tabs, risk day by default, arrow keys switch and move focus", () => {
  panel();
  const tabs = screen.getByRole("tablist");
  expect(within(tabs).getAllByRole("tab")).toHaveLength(3);
  expect(screen.getByTestId("forecast-view-riskday")).toHaveAttribute("aria-selected", "true");
  expect(screen.getByTestId("forecast-table")).toBeInTheDocument();
  const risk = screen.getByTestId("forecast-view-riskday");
  risk.focus();
  fireEvent.keyDown(risk, { key: "ArrowRight" });
  expect(screen.getByTestId("forecast-view-seasonal")).toHaveAttribute("aria-selected", "true");
  expect(screen.getByTestId("forecast-view-seasonal")).toHaveFocus();
  expect(screen.queryByTestId("forecast-table")).toBeNull();
  expect(screen.getByTestId("seasonal-view")).toBeInTheDocument();
  fireEvent.keyDown(screen.getByTestId("forecast-view-seasonal"), { key: "End" });
  expect(screen.getByTestId("highflow-view")).toBeInTheDocument();
  fireEvent.keyDown(screen.getByTestId("forecast-view-highflow"), { key: "ArrowRight" });
  expect(screen.getByTestId("forecast-table")).toBeInTheDocument();
  // notices with the official links stay on every view
  fireEvent.click(screen.getByTestId("forecast-view-seasonal"));
  expect(screen.getByTestId("forecast-notices")).toBeInTheDocument();
});

test("seasonal: header, month labels, terciles per model, edges, skill and reasons", () => {
  panel();
  fireEvent.click(screen.getByTestId("forecast-view-seasonal"));
  expect(screen.getByTestId("seasonal-estado")).toHaveTextContent("Experimental");
  expect(screen.getByTestId("seasonal-issued")).toHaveTextContent("01/01/2026");
  expect(screen.getByTestId("seasonal-model")).toHaveTextContent("seasonal-fixture");
  expect(screen.getByTestId("seasonal-period")).toHaveTextContent("2026-01-01/2026-02-01");
  expect(screen.getByTestId("seasonal-source")).not.toBeEmpty();
  expect(screen.getByTestId("seasonal-month-1")).toHaveTextContent("ene 2026");
  expect(screen.getByTestId("seasonal-p-1-analogos_enso")).toHaveTextContent("20 % / 30 % / 50 %");
  expect(screen.getByTestId("seasonal-interval-1-analogos_enso")).toHaveTextContent("30 % a 78 %");
  expect(screen.getByTestId("seasonal-edges-1")).toHaveTextContent("inferior ≤ 25,6 mm/mes, superior ≥ 37 mm/mes");
  expect(screen.getByTestId("seasonal-skill-1")).toHaveTextContent("supera a la climatología: no");
  expect(screen.getByTestId("seasonal-reason-1-logistica")).toHaveTextContent("No emitido: no supera a la climatología");
  expect(screen.queryByTestId("seasonal-p-1-logistica")).toBeNull();
  expect(screen.getByTestId("seasonal-note")).toHaveTextContent("Sin skill");
  // target selector; the logistic model appears where it was emitted
  fireEvent.click(screen.getByTestId("seasonal-target-flow12004"));
  expect(screen.getByTestId("seasonal-target")).toHaveAttribute("data-target", "flow12004");
  expect(screen.getByTestId("seasonal-p-1-logistica")).toHaveTextContent("5,0 % / 15 % / 80 %");
  expect(screen.getByTestId("seasonal-edges-1")).toHaveTextContent("m³/s");
  expect(screen.getByTestId("seasonal-skill-1")).toHaveTextContent("supera a la climatología: sí");
  expect(screen.getByTestId("seasonal-reason-2-logistica")).toBeInTheDocument();
});

test("seasonal: out-of-range note only where the list is non-empty; unknown shows nothing", () => {
  panel();
  fireEvent.click(screen.getByTestId("forecast-view-seasonal"));
  fireEvent.click(screen.getByTestId("seasonal-target-flow12004"));
  const note = screen.getByTestId("seasonal-oor-1-logistica");
  expect(note).toHaveTextContent(
    "Entradas fuera del rango entrenado: agua de suelo capa 1, cuenca 12004 (0,45 m³/m³; entrenamiento 0,12–0,38). El modelo extrapola: la probabilidad puede no ser confiable.",
  );
  expect(note.getAttribute("class") ?? "").not.toMatch(/warn|alert|error/);
  expect(screen.queryByTestId("seasonal-oor-2-logistica")).toBeNull(); // [] -> no note
  expect(screen.queryByTestId("seasonal-oor-3-logistica")).toBeNull(); // absent (older emission) -> no note
  expect(screen.getByTestId("seasonal-p-1-logistica")).toBeInTheDocument(); // probabilities untouched
});

test("seasonal: empty out-of-range list shows no note", () => {
  const o = structuredClone(fixture);
  const lead = o.seasonal!.targets!.find((x) => x.id === "flow12004")!.leads[0]!;
  lead.models.find((m) => m.name === "logistica")!.out_of_range = [];
  render(<SeasonalView seasonal={o.seasonal} />);
  fireEvent.click(screen.getByTestId("seasonal-target-flow12004"));
  expect(screen.getByTestId("seasonal-p-1-logistica")).toBeInTheDocument();
  expect(screen.queryByTestId("seasonal-oor-1-logistica")).toBeNull();
});

test("seasonal: available:false shows only the note; missing block shows a default", () => {
  const { unmount } = render(<SeasonalView seasonal={{ available: false, note: "Próxima emisión el 1 de diciembre" } as Seasonal} />);
  expect(screen.getByTestId("seasonal-unavailable-note")).toHaveTextContent("Próxima emisión el 1 de diciembre");
  expect(screen.queryByRole("table")).toBeNull();
  unmount();
  render(<SeasonalView seasonal={undefined} />);
  expect(screen.getByTestId("seasonal-unavailable-note")).toHaveTextContent("no disponible");
});

test("monthLabel", () => {
  expect(monthLabel("2026-12")).toBe("dic 2026");
  expect(monthLabel("raro")).toBe("raro");
});

test("seasonal view stays neutral: no value-keyed styling hooks", () => {
  panel();
  fireEvent.click(screen.getByTestId("forecast-view-seasonal"));
  const html = screen.getByTestId("seasonal-view").innerHTML;
  expect(html).not.toMatch(/style=|<svg|<meter|<progress/);
});

test("high flow: retrospective note, estado, years, variants, F6.7 and F6.9 tables", () => {
  panel();
  fireEvent.click(screen.getByTestId("forecast-view-highflow"));
  expect(screen.getByTestId("highflow-note")).toHaveTextContent("Prueba retrospectiva, no es un pronóstico");
  expect(screen.getByTestId("highflow-estado")).toHaveTextContent("Experimental");
  expect(screen.getByTestId("highflow-years")).toHaveTextContent("13 de 20 requeridos");
  expect(screen.getByTestId("f67-source")).not.toBeEmpty();
  expect(screen.getByTestId("f67-period")).toHaveTextContent("1980-01-01");
  const table = screen.getByTestId("f67-table-gr4j");
  expect(within(table).getAllByRole("row")).toHaveLength(11);
  expect(screen.getByTestId("f67-rises-gr4j-1")).toHaveTextContent("27/30");
  expect(screen.getByTestId("f67-coverage-gr4j-1")).toHaveTextContent("nominal 0,90");
  expect(screen.getByTestId("f67-bss-gr4j-1")).toHaveTextContent("[");
  expect(screen.getByTestId("f67-verdict-gr4j-1")).toHaveTextContent("no pasa");
  expect(screen.getByTestId("highflow-threshold-rule")).toHaveTextContent("mediana de los máximos anuales");
  fireEvent.click(screen.getByTestId("highflow-variant-thr_p95"));
  expect(screen.getByTestId("highflow-threshold-rule")).toHaveTextContent("p95 provisional");
  fireEvent.click(screen.getByTestId("highflow-variant-t_perfect"));
  expect(screen.getByTestId("highflow-threshold-rule")).toHaveTextContent("temperatura perfecta");
  // F6.9
  expect(within(screen.getByTestId("f69-era5-table")).getAllByRole("row")).toHaveLength(4);
  expect(screen.getByTestId("f69-era5-pooled")).toHaveTextContent("0,09");
  expect(screen.getByTestId("f69-era5-12004")).toHaveTextContent("Paso de Indios");
  expect(within(screen.getByTestId("f69-gefs-table")).getAllByRole("row")).toHaveLength(4);
});

test("high flow: unavailable blocks degrade gracefully, each on its own", () => {
  const hf: Highflow = { estado: "Experimental", note: "x", f67: { available: false }, f69: { available: false } };
  const { unmount } = render(<HighflowView highflow={hf} />);
  expect(screen.getByTestId("highflow-note")).toBeInTheDocument();
  expect(screen.getByTestId("f67-unavailable")).toBeInTheDocument();
  expect(screen.getByTestId("f69-unavailable")).toBeInTheDocument();
  expect(screen.queryByRole("table")).toBeNull();
  unmount();
  render(<HighflowView highflow={{ ...hf, f67: fixture.highflow!.f67 }} />);
  expect(screen.getByTestId("f67-table-gr4j")).toBeInTheDocument();
  expect(screen.getByTestId("f69-unavailable")).toBeInTheDocument();
});

test("older layers without seasonal/highflow blocks still render both views", () => {
  const old = { ...fixture, seasonal: undefined, highflow: undefined } as Outlook;
  panel(old);
  fireEvent.click(screen.getByTestId("forecast-view-seasonal"));
  expect(screen.getByTestId("seasonal-unavailable")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("forecast-view-highflow"));
  expect(screen.getByTestId("highflow-unavailable")).toBeInTheDocument();
});

test("a second model (LSTM) gets its own table", () => {
  const f67 = structuredClone(fixture.highflow!.f67!);
  f67.variants!.main!.models.lstm = f67.variants!.main!.models.gr4j!;
  render(<HighflowView highflow={{ f67 }} />);
  expect(screen.getByTestId("f67-table-lstm")).toBeInTheDocument();
  expect(screen.getByTestId("f67-table-gr4j")).toBeInTheDocument();
});

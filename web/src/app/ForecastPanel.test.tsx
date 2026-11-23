import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import type { Outlook } from "../layers/forecast";
import type { ForecastState } from "../layers/useForecastOutlook";
import { ForecastPanel } from "./ForecastPanel";

const fixture = JSON.parse(readFileSync("e2e/fixtures/processed/forecast-outlook/outlook.json", "utf8")) as Outlook;

const panel = (over: Partial<ForecastState> = {}, o: Outlook = fixture) =>
  render(
    <ForecastPanel state={{ status: "ready", outlook: o, ...over } as ForecastState} source="Fuente X" period="2026-11-22/2026-11-22" license="CC0" />,
  );

// Synthetic leads so the assertions do not depend on the fixture's numbers.
const lead = (n: number, over: object = {}) => ({
  ...fixture.regions[0]!.leads[0]!,
  lead: n,
  valid_date: "2026-11-23",
  p: 0.1,
  p_shown: 0.1,
  above_cap: false,
  prob_cap: 0.3,
  estado: "Experimental",
  history: { n: 40, n_events: 3, n_events_pooled: 4, skill: 0.12, ci: [-0.05, 0.3], pod: 0.5, far: 0.6, insufficient: false },
  ...over,
});
const synthetic = (leads: object[]): Outlook => ({ ...fixture, regions: [{ id: "r1", label: "Región uno", threshold_mm: 25, leads: leads as never }] });

test("loading and error states show a message and nothing else", () => {
  const { unmount } = panel({ status: "loading", outlook: null });
  expect(screen.getByText("Cargando la perspectiva…")).toBeInTheDocument();
  expect(screen.queryByTestId("forecast-panel")).toBeNull();
  unmount();
  panel({ status: "error", outlook: null });
  expect(screen.getByText("No se pudo cargar la capa de perspectiva")).toBeInTheDocument();
});

test("always shows the official notice, the audience line and the three official links as real external links", () => {
  panel();
  expect(screen.getByTestId("forecast-official")).toHaveTextContent(fixture.notices.official);
  expect(screen.getByTestId("forecast-audience")).toHaveTextContent(fixture.notices.audience);
  const notices = screen.getByTestId("forecast-notices");
  for (const l of fixture.official_links) {
    const a = within(notices).getByRole("link", { name: l.label });
    expect(a).toHaveAttribute("href", l.url);
    expect(a).toHaveAttribute("target", "_blank");
    expect(a).toHaveAttribute("rel", expect.stringContaining("noopener"));
  }
  expect(fixture.official_links).toHaveLength(3);
  // not dismissible: no buttons inside the notices
  expect(within(notices).queryByRole("button")).toBeNull();
});

test("header shows variable, issue date, GEFS init, model, training period and inputs with latency", () => {
  panel();
  expect(screen.getByTestId("forecast-variable")).toHaveTextContent(fixture.variable_label);
  const dmy = (iso: string) => iso.split("-").reverse().join("/");
  expect(screen.getByTestId("forecast-issued")).toHaveTextContent(dmy(fixture.issue_date));
  expect(screen.getByTestId("forecast-gefs")).toHaveTextContent(dmy(fixture.gefs_init_date));
  expect(screen.getByTestId("forecast-model")).toHaveTextContent(`${fixture.model.name} ${fixture.model.version}`);
  expect(screen.getByTestId("forecast-training")).toHaveTextContent(fixture.model.training_period);
  for (const i of fixture.inputs) expect(screen.getByTestId("forecast-inputs")).toHaveTextContent(i.name);
  expect(screen.getByTestId("forecast-inputs").textContent).toMatch(/(≈ \d+ (h|días))|< 1 h/);
});

test("table has headers and one row per lead; the region selector switches the table", () => {
  panel();
  const table = screen.getByRole("table");
  expect(within(table).getAllByRole("columnheader")).toHaveLength(7);
  expect(within(table).getAllByRole("row")).toHaveLength(1 + fixture.regions[0]!.leads.length);
  expect(screen.getByTestId("forecast-panel")).toHaveAttribute("data-region", fixture.regions[0]!.id);
  const second = fixture.regions[1]!;
  fireEvent.click(screen.getByTestId(`forecast-region-${second.id}`));
  expect(screen.getByTestId("forecast-panel")).toHaveAttribute("data-region", second.id);
  expect(screen.getByRole("table")).toHaveAccessibleName(`Perspectiva a 1–10 días, ${second.label}`);
});

test("above_cap shows '> cap'; otherwise the shown probability; estado is plain text", () => {
  panel({}, synthetic([lead(1, { above_cap: true, p: 0.6, p_shown: 0.3 }), lead(2, { p_shown: 0.1, estado: "Perspectiva de riesgo" })]));
  expect(screen.getByTestId("forecast-p-1")).toHaveTextContent("> 30 %");
  expect(screen.getByTestId("forecast-p-1")).not.toHaveTextContent("60");
  expect(screen.getByTestId("forecast-p-2")).toHaveTextContent("10 %");
  expect(screen.getByTestId("forecast-p-2").textContent).not.toContain(">");
  expect(screen.getByTestId("forecast-estado-1")).toHaveTextContent("Experimental");
  expect(screen.getByTestId("forecast-estado-2")).toHaveTextContent("Perspectiva de riesgo");
});

test("interval ends above the cap are not shown as numbers", () => {
  panel({}, synthetic([lead(1, { above_cap: true, p: 0.9, p_shown: 0.3, prob_cap: 0.3, p_low: 0.2, p_high: 0.95 })]));
  const cell = screen.getByTestId("forecast-interval-1");
  expect(cell).toHaveTextContent("20 %");
  expect(cell).toHaveTextContent("> 30 %");
  expect(cell).not.toHaveTextContent("95");
});

test("history shows n, events, skill [CI], POD and FAR, or the insufficient text", () => {
  panel(
    {},
    synthetic([
      lead(1),
      lead(2, { history: { n: 9, n_events: null, n_events_pooled: null, skill: null, ci: null, pod: null, far: null, insufficient: true } }),
    ]),
  );
  const h1 = screen.getByTestId("forecast-history-1");
  expect(h1).toHaveTextContent("n 40");
  expect(h1).toHaveTextContent("eventos 3");
  expect(h1).toHaveTextContent("skill 0,12 [-0,05 a 0,30]");
  expect(h1).toHaveTextContent("POD 50 %");
  expect(h1).toHaveTextContent("FAR 60 %");
  expect(screen.getByTestId("forecast-history-2")).toHaveTextContent("Historial insuficiente (n = 9)");
  expect(screen.getByTestId("forecast-history-2").textContent).not.toContain("POD");
});

test("explains each state and shows the history note and cap rule footnotes", () => {
  panel();
  for (const [k, v] of Object.entries(fixture.notices.states)) {
    const dt = screen.getByText(k, { selector: "dt" });
    expect(dt.parentElement).toHaveTextContent(v);
  }
  expect(screen.getByTestId("forecast-history-note")).toHaveTextContent(fixture.history_note);
  expect(screen.getByTestId("forecast-cap-rule")).toHaveTextContent(fixture.cap_rule);
});

test("no inline colour styles and no advice wording anywhere in the panel", () => {
  panel();
  const root = screen.getByTestId("forecast-panel");
  expect(root.querySelectorAll("[style]")).toHaveLength(0);
  expect(root.querySelectorAll("svg")).toHaveLength(0);
  expect(root.textContent).not.toMatch(/evacu|precauci|recomend|alerta roja|peligro/i);
});

test("latency hours render as hours below two days, as days from two days", () => {
  panel({}, { ...fixture, inputs: [{ name: "A", latency_hours: 6 }, { name: "B", latency_hours: 168 }] });
  expect(screen.getByTestId("forecast-inputs")).toHaveTextContent("A ≈ 6 h");
  expect(screen.getByTestId("forecast-inputs")).toHaveTextContent("B ≈ 7 días");
});

test("threshold and the source line are formatted: es-AR decimals, no unrounded float, no doubled period", () => {
  const o = synthetic([lead(1)]);
  o.regions[0]!.threshold_mm = 15.069199999999979;
  render(<ForecastPanel state={{ status: "ready", outlook: o } as ForecastState} source="Fuente X" period="P" license="CC0. No es una alerta oficial." />);
  expect(screen.getByText(/Umbral/)).toHaveTextContent("Umbral 15,1 mm");
  const src = screen.getByTestId("forecast-source");
  expect(src).toHaveTextContent("Licencia CC0. No es una alerta oficial.");
  expect(src.textContent).not.toMatch(/\.\./);
  expect(screen.getByTestId("forecast-panel").textContent).not.toMatch(/\d\.\d{4,}/);
});

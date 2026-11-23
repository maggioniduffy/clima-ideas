import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import type { AnalogsData, HindcastCases, HindcastSkill } from "../layers/hindcast";
import type { HindcastState } from "../layers/useHindcast";
import { HindcastPanel } from "./HindcastPanel";

const dir = "e2e/fixtures/processed/";
const read = <T,>(p: string) => JSON.parse(readFileSync(dir + p, "utf8")) as T;
const cases = read<HindcastCases>("hindcast-verification/cases.json");
const skill = read<HindcastSkill>("hindcast-verification/skill.json");
const analogs = read<AnalogsData>("hindcast-analogs/analogs.json");

const state = (over: Partial<HindcastState> = {}): HindcastState =>
  ({ status: "ready", cases, skill, analogs, ...over }) as HindcastState;
const panel = (over: Partial<HindcastState> = {}) =>
  render(<HindcastPanel state={state(over)} source="Fuente X" period="2001-05-02/2025-06-05" license="CC0" />);

test("loading and error states show a message and nothing else", () => {
  const { unmount } = panel({ status: "loading", cases: null, skill: null });
  expect(screen.getByText("Cargando la verificación…")).toBeInTheDocument();
  expect(screen.queryByTestId("hindcast-panel")).toBeNull();
  unmount();
  panel({ status: "error", cases: null, skill: null });
  expect(screen.getByText("No se pudo cargar la capa de verificación")).toBeInTheDocument();
});

test("always shows source, period, the retrospective tag, the not-official-alert line and the three links", () => {
  panel();
  expect(screen.getByTestId("hindcast-source")).toHaveTextContent("Fuente X");
  expect(screen.getByTestId("hindcast-source")).toHaveTextContent("2001-05-02/2025-06-05");
  expect(screen.getByTestId("hindcast-retro")).toHaveTextContent("Retrospectivo");
  expect(screen.getByTestId("hindcast-not-alert")).toHaveTextContent("No es un sistema de alerta oficial");
  expect(screen.getByTestId("hindcast-link-smn")).toHaveAttribute("href", "https://www.smn.gob.ar/alertas");
  expect(screen.getByTestId("hindcast-link-aic")).toHaveAttribute("href", "https://www.aic.gob.ar");
  expect(screen.getByTestId("hindcast-link-civil")).toHaveAttribute("href", "https://www.neuquen.gov.ar/defensacivil/");
  expect(screen.getByTestId("hindcast-license")).toHaveTextContent("CC0");
});

test("defaults to the first model, its first event and lead 1; the readout shows mean, range and observed", () => {
  panel();
  const root = screen.getByTestId("hindcast-panel");
  expect(root).toHaveAttribute("data-model", "gefs-reforecast");
  expect(root).toHaveAttribute("data-event", "AR-2001-001");
  expect(root).toHaveAttribute("data-lead", "1");
  expect(screen.getByTestId("hindcast-fc-mean")).toHaveTextContent("9,4 mm");
  expect(screen.getByTestId("hindcast-fc-range")).toHaveTextContent("8,4 a 10,4 mm");
  expect(screen.getByTestId("hindcast-obs")).toHaveTextContent("11,9 mm");
  expect(screen.getByTestId("hindcast-diff")).toHaveTextContent("-2,5 mm");
  expect(screen.getByTestId("hindcast-lead-1")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("hindcast-forecast-marker")).toHaveAttribute("data-lead", "1");
  expect(screen.getByTestId("hindcast-skill-marker")).toHaveAttribute("data-lead", "1");
});

test("choosing a lead moves the readouts, the markers and the gate table", () => {
  panel();
  fireEvent.click(screen.getByTestId("hindcast-lead-6"));
  expect(screen.getByTestId("hindcast-panel")).toHaveAttribute("data-lead", "6");
  expect(screen.getByTestId("hindcast-forecast-marker")).toHaveAttribute("data-lead", "6");
  expect(screen.getByTestId("hindcast-skill-marker")).toHaveAttribute("data-lead", "6");
  expect(screen.getByTestId("hindcast-skill-crpss")).toHaveTextContent("0,50 (0,33 a 0,60)");
  expect(screen.getByTestId("hindcast-gate-table")).toHaveAttribute("data-lead", "6");
  expect(screen.getByTestId("hindcast-gate-status-cordillera_norte")).toHaveTextContent("pasa hindcast (espera la temporada prospectiva)");
  expect(screen.getByTestId("hindcast-gate-status-cordillera_sur")).toHaveTextContent("Experimental");
  fireEvent.click(screen.getByTestId("hindcast-lead-1"));
  expect(screen.getByTestId("hindcast-gate-status-cordillera_sur")).toHaveTextContent("pasa hindcast");
});

test("choosing an event changes the forecast and the observed values", () => {
  panel();
  fireEvent.change(screen.getByTestId("hindcast-event"), { target: { value: "AR-2015-002" } });
  expect(screen.getByTestId("hindcast-panel")).toHaveAttribute("data-event", "AR-2015-002");
  expect(screen.getByTestId("hindcast-obs")).toHaveTextContent("20,3 mm");
  expect(screen.getByTestId("hindcast-valid")).toHaveTextContent("10/04/2015");
  expect(screen.getByTestId("hindcast-obs-line")).toHaveAttribute("data-value", "20.3");
});

test("an unpublished forecast reads 'sin pronóstico publicado' and draws no marker", () => {
  panel();
  fireEvent.change(screen.getByTestId("hindcast-event"), { target: { value: "AR-2007-003" } });
  fireEvent.click(screen.getByTestId("hindcast-lead-3"));
  expect(screen.getByTestId("hindcast-fc-mean")).toHaveTextContent("sin pronóstico publicado");
  expect(screen.getByTestId("hindcast-diff")).toHaveTextContent("s/d");
  expect(screen.queryByTestId("hindcast-forecast-marker")).toBeNull();
});

test("choosing another model swaps its events and skill; a single member has no band or range", () => {
  panel();
  expect(screen.getByTestId("hindcast-forecast-band")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("hindcast-model-ifs"));
  const root = screen.getByTestId("hindcast-panel");
  expect(root).toHaveAttribute("data-model", "ifs");
  expect(root).toHaveAttribute("data-event", "AR-2023-001"); // previous event is not in this model: first one
  expect(within(screen.getByTestId("hindcast-event")).getAllByRole("option")).toHaveLength(2);
  expect(screen.queryByTestId("hindcast-forecast-band")).toBeNull();
  expect(screen.getByTestId("hindcast-fc-range")).toHaveTextContent("Un solo miembro");
  expect(screen.getByTestId("hindcast-skill-crpss")).toHaveTextContent("0,60");
  expect(screen.getByTestId("hindcast-skill-n")).toHaveTextContent("23");
});

test("the analogs section lists the 10 analogs of the event and is omitted without data for it", () => {
  const { unmount } = panel();
  expect(screen.getAllByTestId(/^hindcast-analog-\d+$/)).toHaveLength(10);
  expect(screen.getByTestId("hindcast-analog-ar-0")).toHaveTextContent("Sí (AR-1985-001)");
  expect(screen.getByTestId("hindcast-analog-ar-1")).toHaveTextContent("No");
  expect(screen.getByTestId("hindcast-analogs-note")).toHaveTextContent("3 de 10 fueron río atmosférico");
  expect(screen.getByTestId("hindcast-analogs-table")).toHaveTextContent("s/d"); // IMERG before 2000
  fireEvent.change(screen.getByTestId("hindcast-event"), { target: { value: "AR-2007-003" } });
  expect(screen.queryByTestId("hindcast-analogs")).toBeNull();
  unmount();
  panel({ analogs: null });
  expect(screen.queryByTestId("hindcast-analogs")).toBeNull();
});

test("gate statuses are plain text: no alert colours, levels or advice", () => {
  panel();
  const table = screen.getByTestId("hindcast-gate-table");
  expect(table.querySelectorAll("[style]")).toHaveLength(0);
  expect(table).not.toHaveTextContent(/alerta|peligro|riesgo alto|evacu/i);
  expect(screen.getByTestId("hindcast-gate-bssClim-confluencia")).toHaveTextContent("(");
  expect(screen.getByTestId("hindcast-gate-note")).toHaveTextContent("percentil 95");
});

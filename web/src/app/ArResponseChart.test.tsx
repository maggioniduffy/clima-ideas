import { fireEvent, render, screen } from "@testing-library/react";
import type { ArEvent, ArResponses, ArStationResponse } from "../api/client";
import { es } from "../i18n/es";
import { ArResponseChart } from "./ArResponseChart";

const event = {
  event_id: "AR-2000-002", start: "2000-07-21T00:00:00Z", end: "2000-07-21T03:00:00Z", deg0l_max: 3100,
} as ArEvent;
const resp = (id: string, peak = 140): ArStationResponse => ({
  station_id: id, q_before: 33.8, q_peak: peak, peak_date: "2000-07-25", lag_days: 4, ratio: 4.14,
  daily: { start: "2000-07-18", q: [34, 34, 33.8, 33.6, 33, 33, 33, peak, 32, 32, 31, 31, 31, 31] },
});
const responses = (ids: string[]): ArResponses => ({
  source: "SNIH (SIPH)", period: "2000-01-01/2000-12-31", window_days_after: 10, context_days_before: 3,
  note: "Coincide con el evento; no prueba causa.",
  stations: ids.map((id) => ({ id, name: `Estación ${id}`, river: "Río Falso", regulated: id === "1002" })),
  events: { "AR-2000-002": ids.map((id) => resp(id)) },
});

test("shows a chart per station with window, peak text, regulated label, freezing level, note, source and period", () => {
  render(<ArResponseChart responses={responses(["1001", "1002"])} event={event} />);
  expect(screen.getByRole("heading", { name: es.events.responses.title })).toBeInTheDocument();
  expect(screen.getByTestId("ar-response-chart-1001")).toBeInTheDocument();
  expect(screen.getByTestId("ar-response-chart-1002")).toBeInTheDocument();
  expect(screen.getByTestId("ar-response-shade-1002")).toBeInTheDocument();
  expect(screen.getByTestId("ar-response-window-end-1002")).toBeInTheDocument();
  expect(screen.queryByTestId("ar-response-regulated-1001")).toBeNull();
  expect(screen.getByTestId("ar-response-regulated-1002")).toHaveTextContent("refleja la operación de represas");
  const values = screen.getByTestId("ar-response-values-1002");
  expect(values).toHaveTextContent("33,8 m³/s");
  expect(values).toHaveTextContent("140 m³/s");
  expect(values).toHaveTextContent("25/07/2000, 4 días después del inicio del evento");
  expect(screen.getByTestId("ar-response-deg0l")).toHaveTextContent("Isoterma 0 °C máx.");
  expect(screen.getByTestId("ar-response-deg0l")).toHaveTextContent("3100 m");
  expect(screen.getByTestId("ar-response-note")).toHaveTextContent("no prueba causa");
  expect(screen.getByTestId("ar-response-source")).toHaveTextContent("SNIH (SIPH)");
  expect(screen.getByTestId("ar-response-source")).toHaveTextContent("2000-01-01/2000-12-31");
});

test("a missing freezing level reads sin dato", () => {
  render(<ArResponseChart responses={responses(["1001"])} event={{ ...event, deg0l_max: null }} />);
  expect(screen.getByTestId("ar-response-deg0l")).toHaveTextContent("sin dato");
});

test("renders nothing for an event without flow data", () => {
  const { container } = render(
    <ArResponseChart responses={responses(["1001"])} event={{ ...event, event_id: "AR-2000-001" }} />,
  );
  expect(container).toBeEmptyDOMElement();
});

test("with more than three stations one chart is shown and a selector switches it", () => {
  render(<ArResponseChart responses={responses(["1", "2", "3", "4"])} event={event} />);
  expect(screen.getAllByTestId(/^ar-response-chart-/)).toHaveLength(1);
  expect(screen.getByTestId("ar-response-chart-1")).toBeInTheDocument();
  fireEvent.change(screen.getByTestId("ar-response-station-select"), { target: { value: "3" } });
  expect(screen.getByTestId("ar-response-chart-3")).toBeInTheDocument();
  expect(screen.queryByTestId("ar-response-chart-1")).toBeNull();
});

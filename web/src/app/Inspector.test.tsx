import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import type { LayerManifest } from "../api/client";
import { es } from "../i18n/es";
import { Inspector } from "./Inspector";

const layer: LayerManifest = {
  id: "a",
  title: "Capa A",
  kind: "points",
  source: "Fuente X",
  period: "2000-01-01/2000-12-31",
  license: "CC0",
  updated_at: "2026-01-01T00:00:00Z",
  files: ["p.json"],
};
const features = [{ id: "p1", lon: -69, lat: -38, value: 5.5 }];

test("empty state without a layer", () => {
  render(<Inspector layer={null} features={[]} selectedPointId={null} onSelectPoint={vi.fn()} />);
  expect(screen.getByText(es.inspector.empty)).toBeInTheDocument();
});

test("shows manifest source and period for the selected layer", () => {
  render(<Inspector layer={layer} features={[]} selectedPointId={null} onSelectPoint={vi.fn()} />);
  expect(screen.getByTestId("inspector-source")).toHaveTextContent("Fuente X");
  expect(screen.getByTestId("inspector-period")).toHaveTextContent("2000-01-01/2000-12-31");
});

test("lists features, reports selection and shows point values with source/period", () => {
  const onSelectPoint = vi.fn();
  const { rerender } = render(
    <Inspector layer={layer} features={features} selectedPointId={null} onSelectPoint={onSelectPoint} />,
  );
  fireEvent.click(screen.getByTestId("feature-p1"));
  expect(onSelectPoint).toHaveBeenCalledWith("p1");
  rerender(<Inspector layer={layer} features={features} selectedPointId="p1" onSelectPoint={onSelectPoint} />);
  expect(screen.getByTestId("inspector-point")).toHaveTextContent("5.5");
  expect(screen.getByTestId("inspector-source")).toHaveTextContent("Fuente X");
});

test("events layer: shows the selected event fields, source/period and the cell reading", () => {
  const evLayer: LayerManifest = { ...layer, id: "ar-events", kind: "events", title: "Ríos atmosféricos" };
  const selected = {
    event_id: "AR-2000-001", start: "2000-03-10T06:00:00Z", end: "2000-03-10T12:00:00Z", duration_h: 6,
    n_steps: 1, prob_max: 0.8, area_frac_max: 0.5, ivt_max: 612.4, ivt_max_time: "2000-03-10T09:00:00Z",
    ivt_max_lat: -38.5, ivt_max_lon: -70.5, deg0l_max: 3120, deg0l_mean: 2890, tp_sum_mm: 41.3, enso_phase: "nina",
  }; // fmt: skip
  const props = { layer: evLayer, features: [], selectedPointId: null, onSelectPoint: vi.fn() };
  const { rerender } = render(<Inspector {...props} />);
  expect(screen.getByText(es.events.hint)).toBeInTheDocument();
  expect(screen.getByTestId("events-help")).toHaveTextContent(es.events.help.title);
  expect(screen.getByTestId("events-help")).toHaveTextContent(es.events.help.ar);
  expect(screen.getByTestId("events-help")).toHaveTextContent(es.events.help.ivt);
  expect(screen.getByTestId("events-help")).toHaveTextContent(es.events.help.events);
  rerender(<Inspector {...props} event={{ selected, loadingFrames: false, reading: null }} />);
  const box = screen.getByTestId("inspector-event");
  for (const t of ["2000-03-10 06:00 UTC", "6 h", "612 kg m-1 s-1", "3120 m", "2890 m", "41.3 mm", "La Niña"])
    expect(box).toHaveTextContent(t);
  expect(screen.getByTestId("inspector-source")).toHaveTextContent("Fuente X");
  expect(screen.getByText(es.events.cellHint)).toBeInTheDocument();
  const reading = { lat: -38.5, lon: -70.5, value: 250, timeMs: Date.parse("2000-03-10T07:00:00Z"), kind: "hour" as const };
  rerender(<Inspector {...props} event={{ selected, loadingFrames: false, reading }} />);
  expect(screen.getByTestId("cell-value")).toHaveTextContent("250 kg m-1 s-1");
  expect(screen.getByTestId("cell-where")).toHaveTextContent("38.50 °S, 70.50 °O, 2000-03-10 07:00 UTC");
  rerender(<Inspector {...props} event={{ selected, loadingFrames: false, reading: { ...reading, value: null } }} />);
  expect(screen.getByTestId("cell-value")).toHaveTextContent(es.events.noData);
});

test("flood-stations layer lists station names (its charts live in the detail card); other layers keep Punto labels", () => {
  const floodLayer: LayerManifest = { ...layer, id: "flood-stations", title: "Crecidas" };
  const stations = [{ id: "1001", lon: -69, lat: -38, value: 5, name: "Paso Falso", river: "Río Falso" }];
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) })));
  const { rerender } = render(
    <Inspector layer={floodLayer} features={stations} selectedPointId={null} onSelectPoint={vi.fn()} />,
  );
  expect(screen.getByTestId("feature-1001")).toHaveTextContent("Paso Falso, Río Falso");
  expect(screen.getByTestId("feature-1001")).not.toHaveTextContent(es.inspector.point);
  expect(screen.queryByTestId("flood-station-panel")).toBeNull();
  rerender(<Inspector layer={floodLayer} features={features} selectedPointId="p1" onSelectPoint={vi.fn()} />);
  expect(screen.queryByTestId("inspector-point")).toBeNull();
  rerender(<Inspector layer={layer} features={features} selectedPointId={null} onSelectPoint={vi.fn()} />);
  expect(screen.getByTestId("feature-p1")).toHaveTextContent(`${es.inspector.point} p1`);
  vi.unstubAllGlobals();
});

test("the event view notes that the IVT core is moisture transport, not where most rain falls", () => {
  const events: LayerManifest = { ...layer, id: "ar-events", kind: "events" };
  const selected = { event_id: "AR-1", start: "2000-03-10T06:00:00Z", end: "2000-03-10T09:00:00Z", duration_h: 3 } as never;
  render(
    <Inspector layer={events} features={[]} selectedPointId={null} onSelectPoint={vi.fn()}
      event={{ selected, loadingFrames: false, reading: null }} />,
  );
  expect(screen.getByTestId("event-core-note")).toHaveTextContent(es.events.coreNote);
});

test("the footprint reading is labelled as the event maximum and shows only the place", () => {
  const events: LayerManifest = { ...layer, id: "ar-events", kind: "events" };
  const selected = { event_id: "AR-1", start: "2000-03-10T06:00:00Z", end: "2000-03-10T09:00:00Z", duration_h: 3 } as never;
  const reading = { lat: -38.5, lon: -70.5, value: 480, timeMs: 0, kind: "max" as const };
  render(
    <Inspector layer={events} features={[]} selectedPointId={null} onSelectPoint={vi.fn()}
      event={{ selected, loadingFrames: false, reading }} />,
  );
  expect(screen.getByTestId("inspector-cell")).toHaveTextContent(es.events.cellMax);
  expect(screen.getByTestId("cell-where")).not.toHaveTextContent("UTC");
});

test("event view shows the caudal section only when the selected event has responses", () => {
  const events: LayerManifest = { ...layer, id: "ar-events", kind: "events" };
  const selected = {
    event_id: "AR-1", start: "2000-07-21T00:00:00Z", end: "2000-07-21T03:00:00Z", duration_h: 3, deg0l_max: 3100,
  } as never;
  const q = [10, 10, 10, 50, 10, 10];
  const responses = {
    source: "SNIH", period: "2000/2000", window_days_after: 10, context_days_before: 3, note: "nota",
    stations: [{ id: "9", name: "Est", river: "R", regulated: true }],
    events: { "AR-1": [{ station_id: "9", q_before: 10, q_peak: 50, peak_date: "2000-07-21", lag_days: 0, ratio: 5, daily: { start: "2000-07-18", q } }] },
  };
  const props = { layer: events, features: [], selectedPointId: null, onSelectPoint: vi.fn() };
  const { rerender } = render(<Inspector {...props} event={{ selected, loadingFrames: false, reading: null, responses }} />);
  expect(screen.getByTestId("ar-response")).toBeInTheDocument();
  expect(screen.getByTestId("ar-response-regulated-9")).toBeInTheDocument();
  rerender(<Inspector {...props} event={{ selected, loadingFrames: false, reading: null, responses: null }} />);
  expect(screen.queryByTestId("ar-response")).toBeNull();
});

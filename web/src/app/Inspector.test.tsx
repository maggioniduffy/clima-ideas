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
  const reading = { lat: -38.5, lon: -70.5, value: 250, timeMs: Date.parse("2000-03-10T07:00:00Z") };
  rerender(<Inspector {...props} event={{ selected, loadingFrames: false, reading }} />);
  expect(screen.getByTestId("cell-value")).toHaveTextContent("250 kg m-1 s-1");
  expect(screen.getByTestId("cell-where")).toHaveTextContent("38.50 °S, 70.50 °O, 2000-03-10 07:00 UTC");
  rerender(<Inspector {...props} event={{ selected, loadingFrames: false, reading: { ...reading, value: null } }} />);
  expect(screen.getByTestId("cell-value")).toHaveTextContent(es.events.noData);
});

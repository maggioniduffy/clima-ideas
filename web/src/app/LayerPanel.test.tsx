import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import type { LayerManifest } from "../api/client";
import { es } from "../i18n/es";
import { LayerPanel } from "./LayerPanel";

const layer: LayerManifest = {
  id: "a",
  title: "Capa A",
  kind: "points",
  source: "S",
  period: "2000-01-01/2000-12-31",
  license: "CC0",
  updated_at: "2026-01-01T00:00:00Z",
  files: ["p.json"],
};

const base = { layers: [layer], status: "ready" as const, activeIds: new Set<string>(), selectedId: null };

test("lists layer titles and toggles activation", () => {
  const onToggle = vi.fn();
  render(<LayerPanel {...base} onToggle={onToggle} onSelect={vi.fn()} />);
  expect(screen.getByText("Capa A")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("layer-toggle-a"));
  expect(onToggle).toHaveBeenCalledWith("a");
});

test("marks active layers and selects on title click", () => {
  const onSelect = vi.fn();
  render(<LayerPanel {...base} activeIds={new Set(["a"])} onToggle={vi.fn()} onSelect={onSelect} />);
  expect(screen.getByTestId("layer-item-a")).toHaveAttribute("data-active", "true");
  expect(screen.getByTestId("layer-toggle-a")).toBeChecked();
  fireEvent.click(screen.getByText("Capa A"));
  expect(onSelect).toHaveBeenCalledWith("a");
});

test("shows empty, loading and error states", () => {
  const props = { ...base, layers: [], onToggle: vi.fn(), onSelect: vi.fn() };
  const { rerender } = render(<LayerPanel {...props} />);
  expect(screen.getByText(es.layers.empty)).toBeInTheDocument();
  rerender(<LayerPanel {...props} status="loading" />);
  expect(screen.getByText(es.layers.loading)).toBeInTheDocument();
  rerender(<LayerPanel {...props} status="error" />);
  expect(screen.getByText(es.layers.error)).toBeInTheDocument();
});

test("active events layer lists its events and reports selection", () => {
  const evLayer: LayerManifest = { ...layer, id: "ar-events", kind: "events", title: "Ríos" };
  const onSelectEvent = vi.fn();
  const items = [
    { event_id: "AR-2000-001", start: "2000-03-10T06:00:00Z", ivt_max: 350 },
    { event_id: "AR-2000-002", start: "2000-07-21T00:00:00Z", ivt_max: null },
  ] as never;
  const events = { layerId: "ar-events", status: "ready" as const, items, selectedEventId: "AR-2000-002", onSelectEvent };
  const props = { ...base, layers: [evLayer], onToggle: vi.fn(), onSelect: vi.fn(), events };
  const { rerender } = render(<LayerPanel {...props} />);
  expect(screen.queryByTestId("event-list")).toBeNull();
  rerender(<LayerPanel {...props} activeIds={new Set(["ar-events"])} />);
  expect(screen.getByTestId("event-AR-2000-001")).toHaveTextContent("2000-03-10");
  expect(screen.getByTestId("event-AR-2000-001")).toHaveTextContent("IVT 350");
  expect(screen.getByTestId("event-AR-2000-002")).toHaveTextContent(es.events.noData);
  expect(screen.getByTestId("event-AR-2000-002")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByTestId("event-AR-2000-001"));
  expect(onSelectEvent).toHaveBeenCalledWith("AR-2000-001");
});

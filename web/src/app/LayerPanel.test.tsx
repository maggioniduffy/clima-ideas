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

test("each layer is a row: a label around a visible checkbox", () => {
  render(<LayerPanel {...base} activeIds={new Set(["a"])} onToggle={vi.fn()} onSelect={vi.fn()} />);
  const pill = screen.getByTestId("layer-item-a");
  expect(pill.tagName).toBe("LABEL");
  expect(screen.getByTestId("layer-toggle-a")).not.toHaveStyle({ opacity: "0" });
  expect(pill).toContainElement(screen.getByTestId("layer-toggle-a"));
  expect(screen.getByTestId("layer-toggle-a")).toHaveAccessibleName(`${es.layers.toggle} Capa A`);
});

test("choosing a layer that is on but not selected selects it; the selected one toggles off", () => {
  const onToggle = vi.fn();
  const onSelect = vi.fn();
  const { rerender } = render(<LayerPanel {...base} activeIds={new Set(["a"])} selectedId="b" onToggle={onToggle} onSelect={onSelect} />);
  fireEvent.click(screen.getByTestId("layer-toggle-a"));
  expect(onSelect).toHaveBeenCalledWith("a");
  expect(onToggle).not.toHaveBeenCalled();
  rerender(<LayerPanel {...base} activeIds={new Set(["a"])} selectedId="a" onToggle={onToggle} onSelect={onSelect} />);
  fireEvent.click(screen.getByTestId("layer-toggle-a"));
  expect(onToggle).toHaveBeenCalledWith("a");
});

test("the rows are a navigation landmark named Capas, with no aside", () => {
  render(<LayerPanel {...base} onToggle={vi.fn()} onSelect={vi.fn()} />);
  expect(screen.getByRole("navigation", { name: es.drawers.layers })).toBe(screen.getByTestId("layer-panel"));
  expect(document.querySelector("aside")).toBeNull();
});

test("relief layers (a points layer with a .bin) are not listed in the menu", () => {
  const relief: LayerManifest = { ...layer, id: "relief", title: "Relieve", files: ["relief.bin", "relief.meta.json"] };
  render(<LayerPanel {...base} layers={[relief, layer]} activeIds={new Set(["relief"])} onToggle={vi.fn()} onSelect={vi.fn()} />);
  expect(screen.queryByTestId("layer-item-relief")).toBeNull();
  expect(screen.queryByText("Relieve")).toBeNull();
  expect(screen.getByTestId("layer-item-a")).toBeInTheDocument();
});

test("a menu with only a relief layer shows the empty state", () => {
  const relief: LayerManifest = { ...layer, id: "relief", title: "Relieve", files: ["relief.bin"] };
  render(<LayerPanel {...base} layers={[relief]} onToggle={vi.fn()} onSelect={vi.fn()} />);
  expect(screen.getByText(es.layers.empty)).toBeInTheDocument();
});

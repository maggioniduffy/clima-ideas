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

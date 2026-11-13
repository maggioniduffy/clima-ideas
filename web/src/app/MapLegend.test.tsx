import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { es } from "../i18n/es";
import { IVT_ALPHA_HIGH, IVT_SCALE_MAX } from "../layers/arEvents";
import { MapLegend } from "./MapLegend";

test("legend shows the Spanish title, the tick values and the outline source", () => {
  render(<MapLegend view="drape" onViewChange={() => {}} />);
  const legend = screen.getByTestId("map-legend");
  expect(legend).toHaveTextContent("IVT (kg m⁻¹ s⁻¹)");
  expect(legend).toHaveTextContent(es.map.outlineSource);
  const labels = [...screen.getByTestId("map-legend-ticks").children].map((n) => n.textContent);
  expect(labels).toEqual(["0", "300", "600", "900", "≥1200"]);
});

test("legend shows the transparency note and a fade-in segment up to the IVT_ALPHA_HIGH threshold", () => {
  render(<MapLegend view="drape" onViewChange={() => {}} />);
  expect(screen.getByTestId("map-legend")).toHaveTextContent(es.map.legendLow);
  const bar = screen.getByTestId("map-legend-bar");
  expect(bar.style.background).toContain("rgba(");
  expect(bar.style.background).toContain(`${((IVT_ALPHA_HIGH / IVT_SCALE_MAX) * 100).toFixed(2)}%`);
});

test("the legend has a two-way toggle with aria-pressed that reports the chosen view", () => {
  const onViewChange = vi.fn();
  const { rerender } = render(<MapLegend view="drape" onViewChange={onViewChange} />);
  const drape = screen.getByTestId("ivt-view-drape");
  const lines = screen.getByTestId("ivt-view-isolines");
  expect(drape).toHaveTextContent(es.map.viewDrape);
  expect(lines).toHaveTextContent(es.map.viewIsolines);
  expect(drape).toHaveAttribute("aria-pressed", "true");
  expect(lines).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(lines);
  expect(onViewChange).toHaveBeenCalledWith("isolines");
  rerender(<MapLegend view="isolines" onViewChange={onViewChange} />);
  expect(drape).toHaveAttribute("aria-pressed", "false");
  expect(lines).toHaveAttribute("aria-pressed", "true");
});

test("isolines view lists the four contour levels with their line width instead of the gradient", () => {
  render(<MapLegend view="isolines" onViewChange={() => {}} />);
  expect(screen.queryByTestId("map-legend-bar")).not.toBeInTheDocument();
  const levels = [...screen.getByTestId("map-legend-levels").children];
  expect(levels.map((n) => n.getAttribute("data-level"))).toEqual(["250", "500", "750", "1000"]);
  const widths = levels.map((n) => (n.querySelector("[data-testid=level-line]") as HTMLElement).style.height);
  expect(widths).toEqual(["1.5px", "2px", "2.5px", "3px"]);
  expect(screen.getByTestId("map-legend")).toHaveTextContent(es.map.outlineSource);
});

test("count map legend states what is counted, n events, the period and the source; no view toggle", () => {
  const count = { n: 12, max: 5, from: "2000-03-10", to: "2004-07-21" };
  render(<MapLegend view="drape" onViewChange={() => {}} count={count} />);
  const legend = screen.getByTestId("map-legend");
  expect(legend).toHaveTextContent(es.map.countTitle);
  expect(legend).toHaveTextContent(es.map.countEvents(12));
  expect(legend).toHaveTextContent(es.map.countPeriod("2000-03-10", "2004-07-21"));
  expect(legend).toHaveTextContent(es.map.countSource);
  expect(screen.getByTestId("map-legend-count-ticks")).toHaveTextContent("0" + "3" + "5");
  expect(screen.queryByTestId("ivt-view-drape")).not.toBeInTheDocument();
  expect(screen.queryByTestId("map-legend-ticks")).not.toBeInTheDocument();
});

test("count map legend with no events selected says so and has no period", () => {
  render(<MapLegend view="drape" onViewChange={() => {}} count={{ n: 0, max: 0, from: null, to: null }} />);
  expect(screen.getByTestId("map-legend")).toHaveTextContent(es.map.countEvents(0));
  expect(screen.queryByText(/Período/)).not.toBeInTheDocument();
});

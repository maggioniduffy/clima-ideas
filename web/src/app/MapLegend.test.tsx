import { render, screen } from "@testing-library/react";
import { es } from "../i18n/es";
import { IVT_ALPHA_HIGH, IVT_SCALE_MAX } from "../layers/arEvents";
import { MapLegend } from "./MapLegend";

test("legend shows the Spanish title, the tick values and the outline source", () => {
  render(<MapLegend />);
  const legend = screen.getByTestId("map-legend");
  expect(legend).toHaveTextContent("IVT (kg m⁻¹ s⁻¹)");
  expect(legend).toHaveTextContent(es.map.outlineSource);
  const labels = [...screen.getByTestId("map-legend-ticks").children].map((n) => n.textContent);
  expect(labels).toEqual(["0", "300", "600", "900", "≥1200"]);
});

test("legend shows the transparency note and a fade-in segment up to the IVT_ALPHA_HIGH threshold", () => {
  render(<MapLegend />);
  expect(screen.getByTestId("map-legend")).toHaveTextContent(es.map.legendLow);
  const bar = screen.getByTestId("map-legend-bar");
  expect(bar.style.background).toContain("rgba(");
  expect(bar.style.background).toContain(`${((IVT_ALPHA_HIGH / IVT_SCALE_MAX) * 100).toFixed(2)}%`);
});

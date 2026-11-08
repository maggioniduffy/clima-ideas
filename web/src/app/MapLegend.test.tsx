import { render, screen } from "@testing-library/react";
import { es } from "../i18n/es";
import { MapLegend } from "./MapLegend";

test("legend shows the Spanish title, the tick values and the outline source", () => {
  render(<MapLegend />);
  const legend = screen.getByTestId("map-legend");
  expect(legend).toHaveTextContent("IVT (kg m⁻¹ s⁻¹)");
  expect(legend).toHaveTextContent(es.map.outlineSource);
  const labels = [...screen.getByTestId("map-legend-ticks").children].map((n) => n.textContent);
  expect(labels).toEqual(["0", "300", "600", "900", "≥1200"]);
});

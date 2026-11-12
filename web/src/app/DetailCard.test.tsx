import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import type { FloodStationDetail } from "../api/client";
import { DetailCard } from "./DetailCard";

const detail = {
  id: "1001", name: "Paso Falso", river: "Río Falso", lon: -69, lat: -38, area_km2: 1, has_gev: false, regulated: false,
  source: "S", period: "2000-01-01/2000-12-31", fetched: "2026-11-09", daily: { start: "2000-01-01", q: [1, 2] },
  annual_maxima: [], top_floods: [], curve: [],
} as unknown as FloodStationDetail;
const enso = { status: "loading" as const, stats: null, source: "S", period: "P", onClose: vi.fn() };

test("renders nothing without a station or an open ENSO panel", () => {
  const { container } = render(<DetailCard />);
  expect(container).toBeEmptyDOMElement();
});

test("hosts the flood charts for a selected station", () => {
  render(<DetailCard flood={{ status: "ready", detail }} />);
  expect(screen.getByTestId("detail-card")).toContainElement(screen.getByTestId("flood-station-panel"));
  expect(screen.queryByTestId("enso-panel")).toBeNull();
});

test("hosts the ENSO panel, and it wins over the flood charts", () => {
  render(<DetailCard flood={{ status: "ready", detail }} enso={enso} />);
  expect(screen.getByTestId("detail-card")).toContainElement(screen.getByTestId("enso-panel"));
  expect(screen.queryByTestId("flood-station-panel")).toBeNull();
});

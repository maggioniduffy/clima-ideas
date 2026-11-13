import { vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { FloodStationDetail } from "../api/client";
import { es } from "../i18n/es";
import { FloodStationPanel } from "./FloodStationPanel";

const maxima = [
  { hydro_year: 2023, date: "2023-06-26", q: 11895.4, t_empirical: 81, t_gev: 133.8 },
  { hydro_year: 2006, date: "2007-07-12", q: 7845.5, t_empirical: 40.5, t_gev: 45.8 },
];
const curve = [1.1, 2, 10, 100, 200].map((t) => ({
  t,
  q: 1000 + 800 * Math.log(t),
  lo: t >= 2 && t <= 100 ? 500 + 400 * Math.log(t) : null,
  hi: t >= 2 && t <= 100 ? 2000 + 1200 * Math.log(t) : null,
}));
const base: FloodStationDetail = {
  id: "1001",
  name: "Paso Falso",
  river: "Río Falso",
  lon: -69,
  lat: -38,
  area_km2: 1000,
  has_gev: true,
  regulated: false,
  source: "SNIH (SIPH)",
  period: "1945-01-01/2026-03-31",
  fetched: "2026-11-09",
  daily: { start: "2000-01-01", q: [10, 12, null, 50, 11] },
  annual_maxima: maxima,
  top_floods: maxima,
  gev: { loc: 1, scale: 1, shape_xi: 0.3, n_years: 80, ks_p: 0.7, irregular: false },
  return_levels: [],
  curve,
};

test("GEV station renders the return-period chart, the series chart and the top floods", () => {
  render(<FloodStationPanel state={{ status: "ready", detail: base }} />);
  expect(screen.getByTestId("return-period-chart")).toBeInTheDocument();
  expect(screen.getByTestId("return-period-curve")).toBeInTheDocument();
  expect(screen.getByTestId("return-period-band")).toBeInTheDocument();
  expect(screen.getByTestId("flow-series-chart")).toBeInTheDocument();
  const rows = within(screen.getByTestId("top-floods")).getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("26/06/2023");
  expect(rows[0]).toHaveTextContent("11.895 m³/s");
  expect(rows[0]).toHaveTextContent("T ≈ 134 años");
  expect(screen.getByText(/SNIH \(SIPH\).*1945–2026.*IC 95 % bootstrap/)).toBeInTheDocument();
  expect(screen.getByTestId("return-period-chart")).toHaveTextContent("2");
  for (const t of ["2", "5", "10", "25", "50", "100", "200"])
    expect(within(screen.getByTestId("return-period-chart")).getAllByText(t).length).toBeGreaterThan(0);
  expect(screen.queryByTestId("flood-no-gev")).toBeNull();
  expect(screen.queryByTestId("flood-irregular")).toBeNull();
});

test("irregular fit shows the short-record warning", () => {
  const d = { ...base, gev: { ...base.gev!, irregular: true } };
  render(<FloodStationPanel state={{ status: "ready", detail: d }} />);
  expect(screen.getByTestId("flood-irregular")).toHaveTextContent(es.flood.irregular);
});

test("regulated station: no curve, no-GEV message, empirical T in the list", () => {
  const d: FloodStationDetail = {
    ...base,
    has_gev: false,
    regulated: true,
    gev: undefined,
    curve: undefined,
    return_levels: undefined,
    annual_maxima: [{ ...maxima[0]!, t_gev: null, t_empirical: 3 }],
    top_floods: [{ ...maxima[0]!, t_gev: null, t_empirical: 3 }],
  };
  render(<FloodStationPanel state={{ status: "ready", detail: d }} />);
  expect(screen.getByTestId("flood-no-gev")).toHaveTextContent(es.flood.noGev);
  expect(screen.queryByTestId("return-period-curve")).toBeNull();
  expect(screen.queryByTestId("return-period-band")).toBeNull();
  expect(screen.getByTestId("top-floods")).toHaveTextContent("T ≈ 3 años");
  expect(screen.getByTestId("flow-series-chart")).toBeInTheDocument();
});

test("loading and error states", () => {
  const { rerender } = render(<FloodStationPanel state={{ status: "loading", detail: null }} />);
  expect(screen.getByText(es.flood.loading)).toBeInTheDocument();
  rerender(<FloodStationPanel state={{ status: "error", detail: null }} />);
  expect(screen.getByText(es.flood.error)).toBeInTheDocument();
});

test("charts follow the panel width after a loading state", () => {
  const observed: Element[] = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe(el: Element) {
        observed.push(el);
      }
      disconnect() {}
    },
  );
  const { rerender } = render(<FloodStationPanel state={{ status: "loading", detail: null }} />);
  rerender(<FloodStationPanel state={{ status: "ready", detail: base }} />);
  expect(observed).toContain(screen.getByTestId("flood-station-panel"));
  vi.unstubAllGlobals();
});

test("the flood card only appears (and fetches) when the station has events", async () => {
  const f = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ events: [] }) }));
  vi.stubGlobal("fetch", f);
  const { rerender } = render(<FloodStationPanel state={{ status: "ready", detail: base }} />);
  expect(screen.queryByTestId("flood-event-card")).toBeNull();
  expect(f).not.toHaveBeenCalled();
  rerender(<FloodStationPanel state={{ status: "ready", detail: { ...base, has_events: true } as FloodStationDetail }} />);
  await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
  vi.unstubAllGlobals();
});

test("a top flood with AR events gets a 'Coincide con' tag that opens the event; no tag without the callback", () => {
  const withAr = {
    ...base,
    top_floods: [{ ...maxima[0]!, ar_events: ["AR-2023-001", "AR-2023-002"] }, maxima[1]!],
  };
  const onOpenArEvent = vi.fn();
  const { rerender } = render(
    <FloodStationPanel state={{ status: "ready", detail: withAr }} onOpenArEvent={onOpenArEvent} />,
  );
  expect(screen.getAllByTestId(/^flood-ar-tag-/)).toHaveLength(2);
  const tag = screen.getByTestId("flood-ar-tag-AR-2023-001");
  expect(tag).toHaveTextContent("Coincide con AR-2023-001");
  expect(tag.textContent).not.toMatch(/caus|provoc/i);
  fireEvent.click(tag);
  expect(onOpenArEvent).toHaveBeenCalledWith("AR-2023-001");
  rerender(<FloodStationPanel state={{ status: "ready", detail: withAr }} />);
  expect(screen.queryByTestId("flood-ar-tag-AR-2023-001")).toBeNull();
});

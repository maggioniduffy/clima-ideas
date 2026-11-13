import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { FloodEvent, FloodEventsFile } from "../layers/useFloodStation";
import { FloodEventCard } from "./FloodEventCard";

const CAVEAT =
  "Pronóstico retrospectivo con meteorología observada (ERA5), no pronóstico operativo. Experimental, no es una alerta.";

function makeEvent(peak: string, pq: number): FloodEvent {
  const base = Date.parse(peak);
  const iso = (k: number) => new Date(base + k * 86_400_000).toISOString().slice(0, 10);
  return {
    peak_date: peak,
    peak_q: pq,
    hydro_year: Number(peak.slice(0, 4)),
    obs: { start: iso(-14), q: Array.from({ length: 22 }, (_, i) => 100 + i * 10) },
    issues: Array.from({ length: 8 }, (_, i) => {
      const n = 7 - i;
      const med = Array.from({ length: 7 }, (_, l) => 100 + n * 5 + l * 20);
      return {
        issue_date: iso(-n),
        days_before_peak: n,
        persistence: 100 + n,
        median: med,
        lo: med.map((m) => m * 0.8),
        hi: med.map((m) => m * 1.3),
      };
    }),
  };
}

const file: FloodEventsFile = {
  station_id: "12004",
  meta: {
    run_name: "fc-default",
    mode: "forecast",
    split: "default",
    seeds: [0, 1, 2, 3, 4],
    test_years: [2014, 2025],
    leads: 7,
    forcing: "ERA5 observada, no pronóstico",
    caveat: CAVEAT,
    pretrain: "CAMELS-CL (PANGAEA), forzante CR2MET",
    area_km2: 2131,
    area_note: "área SNIH igual a la de Chos Malal, sin verificar",
    source: "SNIH (SIPH)",
    period: "1945-01-01/2026-03-31",
  },
  events: [makeEvent("2016-06-10", 3000), makeEvent("2023-06-26", 11895.4)],
};

afterEach(() => vi.unstubAllGlobals());

function stubFetch(body: unknown, ok = true) {
  const f = vi.fn(async () => ({ ok, status: ok ? 200 : 404, json: async () => body }));
  vi.stubGlobal("fetch", f);
  return f;
}

test("fetches events/<id>.json and renders chart, legend, caveat, source and model line", async () => {
  const f = stubFetch(file);
  render(<FloodEventCard stationId="12004" width={300} />);
  expect(await screen.findByTestId("flood-event-card")).toBeInTheDocument();
  expect((f.mock.calls as unknown as string[][])[0]![0]).toBe("/api/layers/flood-stations/data?file=events%2F12004.json");
  for (const id of ["event-chart", "event-observed", "event-band", "event-median", "event-persistence", "event-legend"])
    expect(screen.getByTestId(id)).toBeInTheDocument();
  expect(screen.getByTestId("event-caveat")).toHaveTextContent(CAVEAT);
  const card = screen.getByTestId("flood-event-card");
  expect(card).toHaveTextContent("SNIH (SIPH) · 1945–2026");
  expect(card).toHaveTextContent("ERA5 observada, no pronóstico");
  expect(card).toHaveTextContent("área SNIH igual a la de Chos Malal, sin verificar");
  expect(card).toHaveTextContent("CAMELS-CL (PANGAEA), forzante CR2MET");
});

test("event picker lists date and peak; the last event starts selected; picking one resets the issue day", async () => {
  stubFetch(file);
  render(<FloodEventCard stationId="12004" width={300} />);
  const tabs = await screen.findAllByRole("tab");
  expect(tabs).toHaveLength(2);
  expect(tabs[1]).toHaveTextContent("26/06/2023 · 11.895 m³/s");
  expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  expect(screen.getByTestId("event-issue-label")).toHaveTextContent("Emitido el día del pico");
  fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
  expect(screen.getByTestId("event-issue-label")).toHaveTextContent("Emitido 7 días antes del pico");
  fireEvent.click(tabs[0]!);
  expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  expect(screen.getByTestId("event-issue-label")).toHaveTextContent("Emitido el día del pico");
});

test("changing the issue day changes the forecast lines and exposes the label as the slider's value text", async () => {
  stubFetch(file);
  render(<FloodEventCard stationId="12004" width={300} />);
  const slider = await screen.findByRole("slider");
  const before = screen.getByTestId("event-median").getAttribute("d");
  fireEvent.change(slider, { target: { value: "2" } });
  expect(screen.getByTestId("event-median").getAttribute("d")).not.toBe(before);
  expect(slider).toHaveAttribute("aria-valuetext", "Emitido 5 días antes del pico");
});

test("no events or a failed request: nothing for the missing file, a message for errors", async () => {
  stubFetch({ ...file, events: [] });
  const { container, unmount } = render(<FloodEventCard stationId="1" width={300} />);
  await waitFor(() => expect(screen.queryByText(/Cargando/)).toBeNull());
  expect(container).toBeEmptyDOMElement();
  unmount();
  stubFetch({}, false);
  render(<FloodEventCard stationId="2" width={300} />);
  expect(await screen.findByText("No se pudieron cargar los pronósticos retrospectivos")).toBeInTheDocument();
});

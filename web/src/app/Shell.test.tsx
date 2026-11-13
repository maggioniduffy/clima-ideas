import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { vi } from "vitest";
import { es } from "../i18n/es";
import { Shell } from "./Shell";

vi.mock("@deck.gl/react", () => ({
  default: () => <div data-testid="deck-mock" />,
}));

const province = JSON.parse(readFileSync("public/geo/neuquen-province.geojson", "utf8"));

const manifest = {
  id: "a",
  title: "Capa A",
  kind: "points",
  source: "Fuente X",
  period: "2000-01-01/2000-12-31",
  license: "CC0",
  updated_at: "2026-01-01T00:00:00Z",
  files: ["p.json"],
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => {
        if (url.endsWith(".geojson")) return province;
        return url.endsWith("/data") ? [{ id: "p1", lon: -69, lat: -38, value: 5.5 }] : [manifest];
      },
    })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const regions = ["topbar", "layer-panel", "map-canvas", "inspector", "timeline"];

test("Shell renders the five regions", () => {
  render(<Shell />);
  for (const id of regions) expect(screen.getByTestId(id)).toBeInTheDocument();
  expect(screen.getByTestId("deck-mock")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: es.appTitle })).toBeInTheDocument();
});

test("theme toggle in the top bar flips data-theme", () => {
  render(<Shell />);
  const before = document.documentElement.dataset.theme;
  fireEvent.click(screen.getByRole("button", { name: es.theme.toggle }));
  expect(document.documentElement.dataset.theme).not.toBe(before);
  fireEvent.click(screen.getByRole("button", { name: es.theme.toggle }));
  expect(document.documentElement.dataset.theme).toBe(before);
});

test("activating a fetched layer adds the deck layer and shows manifest source/period", async () => {
  render(<Shell />);
  fireEvent.click(await screen.findByTestId("layer-toggle-a"));
  await waitFor(() => expect(screen.getByTestId("map-canvas")).toHaveAttribute("data-deck-layers", expect.stringMatching(/^points-a(,|$)/)));
  expect(screen.getByTestId("layer-item-a")).toHaveAttribute("data-active", "true");
  expect(screen.getByTestId("inspector-source")).toHaveTextContent("Fuente X");
  expect(screen.getByTestId("inspector-period")).toHaveTextContent("2000-01-01/2000-12-31");
  fireEvent.click(screen.getByTestId("feature-p1"));
  expect(screen.getByTestId("inspector-point")).toHaveTextContent("5.5");
  fireEvent.click(screen.getByTestId("layer-toggle-a"));
  expect(screen.getByTestId("map-canvas").getAttribute("data-deck-layers")).not.toContain("points-a");
});

test("province outline, city marker and label are always drawn, with no layer active", async () => {
  render(<Shell />);
  const canvas = screen.getByTestId("map-canvas");
  await waitFor(() => expect(canvas.getAttribute("data-deck-layers")).toContain("ref-province"));
  for (const id of ["ref-province-halo", "ref-city", "ref-labels"])
    expect(canvas.getAttribute("data-deck-layers")).toContain(id);
  fireEvent.click(await screen.findByTestId("layer-toggle-a"));
  fireEvent.click(screen.getByTestId("layer-toggle-a"));
  for (const id of ["ref-province", "ref-city", "ref-labels"])
    expect(canvas.getAttribute("data-deck-layers")).toContain(id);
  expect(canvas.getAttribute("data-deck-layers")).not.toContain("points-a");
});

test("the layers drawer toggle exposes aria-expanded/aria-controls; there is no inspector drawer", () => {
  render(<Shell />);
  const layers = screen.getByTestId("drawer-toggle-layers");
  expect(layers).toHaveAttribute("aria-controls", "layer-panel");
  expect(screen.queryByTestId("drawer-toggle-inspector")).not.toBeInTheDocument();
  expect(layers).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(layers);
  expect(layers).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByTestId("shell")).toHaveAttribute("data-drawer", "layers");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByTestId("shell")).not.toHaveAttribute("data-drawer");
});

test("the inspector is the first card of the card row", () => {
  render(<Shell />);
  expect(screen.getByTestId("cards-row")).toContainElement(screen.getByTestId("inspector"));
  expect(screen.getByTestId("inspector")).toHaveAttribute("id", "inspector-panel");
});

test("the topbar shows the logo mark and the wordmark next to the page h1", () => {
  render(<Shell />);
  const bar = screen.getByTestId("topbar");
  expect(bar).toHaveTextContent("Clima Ideas");
  expect(bar.querySelector("svg")).not.toBeNull();
  expect(screen.getByRole("heading", { name: es.appTitle })).toBeInTheDocument();
});

test("IVT view toggle: legend control only with the AR layer; isolines add contour layers and cell readings keep working", async () => {
  const arLayer = { ...manifest, id: "ar-events", kind: "events", files: ["events.json", "frames/index.json"] };
  const event = {
    event_id: "AR-1", start: "2000-03-10T06:00:00Z", end: "2000-03-10T07:00:00Z", duration_h: 2, n_steps: 1,
    prob_max: 0.8, area_frac_max: 0.5, ivt_max: 300, ivt_max_time: null, ivt_max_lat: null, ivt_max_lon: null,
    deg0l_max: null, deg0l_mean: null, tp_sum_mm: null, enso_phase: null,
  }; // fmt: skip
  const index = {
    units: "kg m-1 s-1",
    step_hours: 1,
    grid: { ny: 3, nx: 3, lat_min: -39, lat_max: -38, lon_min: -70, lon_max: -69 },
    events: { "AR-1": { start: event.start, n_frames: 1, vmin: 0, vmax: 900 } },
  };
  const frame = new Float32Array([0, 0, 0, 0, 900, 0, 0, 0, 0]).buffer; // a single peak in the middle
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => frame,
      json: async () => {
        if (url.endsWith(".geojson")) return province;
        if (url.includes("frames%2Findex.json")) return index;
        if (url.includes("events.json")) return [event];
        return [arLayer];
      },
    })),
  );
  render(<Shell />);
  const canvas = screen.getByTestId("map-canvas");
  expect(screen.queryByTestId("map-legend")).not.toBeInTheDocument();
  fireEvent.click(await screen.findByTestId("layer-toggle-ar-events"));
  expect(screen.getByTestId("ivt-view-drape")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(await screen.findByTestId("year-expand-2000")); // years start collapsed
  fireEvent.click(screen.getByTestId("month-expand-2000-03"));
  fireEvent.click(await screen.findByTestId("event-AR-1"));
  await waitFor(() => expect(canvas.getAttribute("data-deck-layers")).toContain("ivt-ar-events"));
  expect(canvas.getAttribute("data-deck-layers")).not.toContain("ivt-contours");

  fireEvent.click(screen.getByTestId("ivt-view-isolines"));
  expect(screen.getByTestId("ivt-view-isolines")).toHaveAttribute("aria-pressed", "true");
  expect(canvas.getAttribute("data-deck-layers")).toContain("ivt-contours-halo-ar-events,ivt-contours-ar-events");
  // outlines stay on top of the contours
  expect(canvas.getAttribute("data-deck-layers")).toMatch(/ivt-contours-ar-events,.*ref-province/);

  fireEvent.click(screen.getByTestId("ivt-view-drape"));
  expect(canvas.getAttribute("data-deck-layers")).not.toContain("ivt-contours");

  fireEvent.click(screen.getByTestId("layer-toggle-ar-events"));
  expect(screen.queryByTestId("ivt-view-drape")).not.toBeInTheDocument();
});

test("AR filter: year and month toggles and top N drive the event list and the timeline marks", async () => {
  const arLayer = { ...manifest, id: "ar-events", kind: "events", files: ["events.json", "frames/index.json"] };
  const mk = (id: string, start: string, ivt: number) => ({
    event_id: id, start, end: start.replace("T06", "T09"), duration_h: 3, n_steps: 1, prob_max: 0.8, area_frac_max: 0.5,
    ivt_max: ivt, ivt_max_time: null, ivt_max_lat: null, ivt_max_lon: null, deg0l_max: null, deg0l_mean: null,
    tp_sum_mm: null, enso_phase: null,
  }); // fmt: skip
  const evs = [mk("A", "2000-03-10T06:00:00Z", 300), mk("B", "2000-07-10T06:00:00Z", 900), mk("C", "2000-11-10T06:00:00Z", 600)];
  const index = {
    units: "", step_hours: 1, grid: { ny: 1, nx: 1, lat_min: 0, lat_max: 0, lon_min: 0, lon_max: 0 },
    events: Object.fromEntries(evs.map((e) => [e.event_id, { start: e.start, n_frames: 1, vmin: 0, vmax: 900 }])),
  }; // fmt: skip
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => new Float32Array([0]).buffer,
      json: async () => {
        if (url.endsWith(".geojson")) return province;
        if (url.includes("frames%2Findex.json")) return index;
        if (url.includes("events.json")) return evs;
        return [arLayer];
      },
    })),
  );
  render(<Shell />);
  fireEvent.click(await screen.findByTestId("layer-toggle-ar-events"));
  for (const id of ["A", "B", "C"]) expect(await screen.findByTestId(`timeline-event-${id}`)).toBeInTheDocument();

  // a month off removes just that event from the timeline
  fireEvent.click(screen.getByTestId("year-expand-2000"));
  fireEvent.click(screen.getByTestId("month-toggle-2000-07"));
  expect(screen.queryByTestId("timeline-event-B")).toBeNull();
  expect(screen.getByTestId("timeline-event-A")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("month-toggle-2000-07"));
  expect(screen.getByTestId("timeline-event-B")).toBeInTheDocument();

  // top N: the filtered set stays on the timeline, the peaks are enlarged and ranked in the card
  fireEvent.click(screen.getByTestId("top-toggle"));
  expect(screen.getByTestId("timeline-event-B")).toHaveAttribute("data-peak", "true"); // all three are within the top 10
  fireEvent.click(screen.getByTestId("top-toggle"));
  expect(screen.getByTestId("timeline-event-B")).not.toHaveAttribute("data-peak");

  // the picked event leaves the filter: the selection is kept and nothing breaks
  fireEvent.click(screen.getByTestId("timeline-event-A"));
  fireEvent.click(screen.getByTestId("year-toggle-2000"));
  expect(screen.queryByTestId("timeline-event-A")).toBeNull();
  expect(screen.getByTestId("event-count")).toHaveTextContent("0");
  expect(screen.getByTestId("replay-controls")).toBeInTheDocument();
});

test("ENSO panel: button only when the layer lists enso.json; opens in the detail card, closes with Esc and with the layer off", async () => {
  const enso = {
    meta: { period: "1980-01-01/2025-12-30", source: "ERA5 + ONI" },
    results: {
      n_perm: 10000, seed: 0, alpha: 0.05,
      rows: [{
        season: "SON", metric: "ivt_mean", phase_years: { nino: 14, neutral: 18, nina: 14 },
        groups: { nino: { n: 14, mean: 527, sd: 80 }, neutral: { n: 18, mean: 500, sd: 70 }, nina: { n: 14, mean: 435, sd: 60 } },
        diff_nino_nina: 92, p: 0.03, p_bh: 0.3, p_3group: 0.2, p_3group_bh: 0.4, f_3group: 1, sustained: true, sustained_bh: false,
      }],
    },
  }; // fmt: skip
  const arLayer = { ...manifest, id: "ar-events", kind: "events", files: ["events.json", "frames/index.json", "enso.json"] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => {
        if (url.endsWith(".geojson")) return province;
        if (url.includes("enso.json")) return enso;
        if (url.includes("frames%2Findex.json")) return { units: "", step_hours: 1, grid: { ny: 1, nx: 1, lat_min: 0, lat_max: 0, lon_min: 0, lon_max: 0 }, events: {} };
        if (url.includes("events.json")) return [];
        return [arLayer];
      },
    })),
  );
  render(<Shell />);
  await screen.findByTestId("layer-toggle-ar-events");
  expect(screen.queryByTestId("enso-open")).not.toBeInTheDocument();
  expect(screen.queryByTestId("detail-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("event-card")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("layer-toggle-ar-events"));
  expect(await screen.findByTestId("event-card")).toBeInTheDocument();
  expect(screen.queryByTestId("map-clock")).not.toBeInTheDocument();
  fireEvent.click(await screen.findByTestId("enso-open"));
  expect(await screen.findByTestId("enso-row-ivt_mean")).toHaveTextContent("527 ± 80 (n=14)");
  expect(screen.getByTestId("detail-card")).toContainElement(screen.getByTestId("enso-panel"));
  expect(screen.getByTestId("cards-row")).toContainElement(screen.getByTestId("detail-card"));
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByTestId("enso-panel")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("enso-open"));
  expect(screen.getByTestId("enso-panel")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("layer-toggle-ar-events"));
  expect(screen.queryByTestId("enso-panel")).not.toBeInTheDocument();
});

test("three resize separators exist and keyboard resizing updates the grid variables", () => {
  localStorage.clear();
  vi.stubGlobal("innerHeight", 1200); // jsdom's 768 px leaves no room above the 400 px map minimum
  render(<Shell />);
  expect(screen.getAllByRole("separator")).toHaveLength(3);
  expect(screen.getByTestId("resizer-layers")).toHaveAttribute("aria-orientation", "vertical");
  expect(screen.getByTestId("resizer-timeline")).toHaveAttribute("aria-orientation", "horizontal");
  const cards = screen.getByRole("separator", { name: "Alto del panel de detalle" });
  expect(cards).toBe(screen.getByTestId("resizer-cards"));
  expect(cards).toHaveAttribute("aria-orientation", "horizontal");
  fireEvent.keyDown(cards, { key: "ArrowUp" });
  expect(screen.getByTestId("shell").style.getPropertyValue("--cards-h")).toBe("276px");
  expect(JSON.parse(localStorage.getItem("panel-sizes")!).cards).toBe(276);
  fireEvent.doubleClick(cards);
  expect(screen.getByTestId("shell").style.getPropertyValue("--cards-h")).toBe("260px");
});

test("Home collapses a panel (hidden, handle stays at 0), Enter restores it, and the state persists", () => {
  localStorage.clear();
  render(<Shell />);
  const layers = screen.getByTestId("resizer-layers");
  expect(screen.getByTestId("layers-slot")).not.toHaveAttribute("hidden");
  fireEvent.keyDown(layers, { key: "Home" });
  expect(screen.getByTestId("layers-slot")).toHaveAttribute("hidden");
  expect(layers).toHaveAttribute("aria-valuenow", "0");
  expect(layers).toHaveAttribute("aria-valuemin", "0");
  expect(JSON.parse(localStorage.getItem("panel-sizes")!).layers).toBe(0);
  fireEvent.keyDown(layers, { key: "Enter" });
  expect(screen.getByTestId("layers-slot")).not.toHaveAttribute("hidden");
  expect(layers).toHaveAttribute("aria-valuenow", "240");
  for (const [id, slot] of [["cards", "cards-row"], ["timeline", "timeline-slot"]]) {
    fireEvent.keyDown(screen.getByTestId(`resizer-${id}`), { key: "Home" });
    expect(screen.getByTestId(slot)).toHaveAttribute("hidden");
  }
});

test("a stored collapsed state is applied on load", () => {
  localStorage.setItem("panel-sizes", JSON.stringify({ layers: 0, cards: 260, timeline: 136 }));
  render(<Shell />);
  expect(screen.getByTestId("layers-slot")).toHaveAttribute("hidden");
  localStorage.clear();
});

import { act, renderHook, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { countColor, ivtColor } from "./arEvents";
import { DEFAULT_TOGGLES } from "./arFilter";
import { parseRelief } from "./reliefLayer";
import { REPLAY_INTERVAL_MS, useArEvents } from "./useArEvents";

const layer = {
  id: "ar-events",
  title: "Ríos atmosféricos",
  kind: "events" as const,
  source: "S",
  period: "2000-01-01/2000-12-31",
  license: "CC0",
  updated_at: "2026-01-01T00:00:00Z",
  files: ["events.json", "frames/index.json"],
};
const event = {
  event_id: "AR-2000-001",
  start: "2000-03-10T06:00:00Z",
  end: "2000-03-10T09:00:00Z",
  duration_h: 3,
  n_steps: 1,
  prob_max: 0.8,
  area_frac_max: 0.5,
  ivt_max: 300,
  ivt_max_time: null,
  ivt_max_lat: null,
  ivt_max_lon: null,
  deg0l_max: null,
  deg0l_mean: null,
  tp_sum_mm: null,
  enso_phase: null,
}; // fmt: skip
const index = {
  units: "kg m-1 s-1",
  step_hours: 1,
  grid: { ny: 1, nx: 2, lat_min: -39, lat_max: -39, lon_min: -70, lon_max: -69 },
  events: { "AR-2000-001": { start: event.start, n_frames: 3, vmin: 100, vmax: 300 } },
};
const frames = new Float32Array([100, 110, 200, 210, 300, 310]).buffer;

function stubFetch() {
  const f = vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => (url.includes("frames%2Findex.json") ? index : [event]),
    arrayBuffer: async () => frames,
  }));
  vi.stubGlobal("fetch", f);
  return f;
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("loads events and index only when active, then frames on selection", async () => {
  const f = stubFetch();
  const { result, rerender } = renderHook(({ active }) => useArEvents(layer, active), {
    initialProps: { active: false },
  });
  expect(result.current.status).toBe("idle");
  expect(f).not.toHaveBeenCalled();
  rerender({ active: true });
  await waitFor(() => expect(result.current.status).toBe("ready"));
  expect(result.current.events).toHaveLength(1);
  expect(result.current.deckLayers).toEqual([]);
  act(() => result.current.select("AR-2000-001"));
  await waitFor(() => expect(result.current.deckLayers.map((l) => l.id)).toEqual(["ivt-ar-events"]));
  expect(f).toHaveBeenCalledWith("/api/layers/ar-events/frames/AR-2000-001");
  expect(result.current.nFrames).toBe(3);
  expect(result.current.cursorMs).toBe(Date.parse("2000-03-10T06:00:00Z"));
  rerender({ active: false });
  expect(result.current.selectedEventId).toBeNull();
  expect(result.current.deckLayers).toEqual([]);
});

test("draws every cell of the frames grid, with no province clipping", async () => {
  const f = stubFetch();
  const { result } = renderHook(() => useArEvents(layer, true));
  await waitFor(() => expect(result.current.status).toBe("ready"));
  act(() => result.current.select("AR-2000-001"));
  await waitFor(() => expect(result.current.deckLayers).toHaveLength(1));
  const { ny, nx } = index.grid;
  expect((result.current.deckLayers[0]!.props as unknown as { data: unknown[] }).data).toHaveLength(ny * nx);
  expect(f.mock.calls.some(([url]) => String(url).includes("/geo/"))).toBe(false);
});

test("steps, seeks within bounds, plays and stops on the last frame", async () => {
  stubFetch();
  const { result } = renderHook(() => useArEvents(layer, true));
  await waitFor(() => expect(result.current.status).toBe("ready"));
  act(() => result.current.select("AR-2000-001"));
  await waitFor(() => expect(result.current.deckLayers).toHaveLength(1));
  act(() => result.current.step(1));
  expect(result.current.frame).toBe(1);
  act(() => result.current.seek(99));
  expect(result.current.frame).toBe(2);
  act(() => result.current.seek(-5));
  expect(result.current.frame).toBe(0);

  vi.useFakeTimers();
  act(() => result.current.toggle());
  expect(result.current.playing).toBe(true);
  act(() => void vi.advanceTimersByTime(REPLAY_INTERVAL_MS));
  expect(result.current.frame).toBe(1);
  expect(result.current.cursorMs).toBe(Date.parse("2000-03-10T07:00:00Z"));
  act(() => void vi.advanceTimersByTime(REPLAY_INTERVAL_MS * 3));
  expect(result.current.frame).toBe(2);
  expect(result.current.playing).toBe(false);
  // play from the last frame restarts
  act(() => result.current.toggle());
  expect(result.current.frame).toBe(0);
  expect(result.current.playing).toBe(true);
});

const relief = parseRelief(new Float32Array([-70, -39, 500, -69.5, -39, 900, -69, -39, 700]).buffer);

async function selected(opts: Parameters<typeof useArEvents>[2]) {
  stubFetch();
  const hook = renderHook((o) => useArEvents(layer, true, o), { initialProps: opts });
  await waitFor(() => expect(hook.result.current.status).toBe("ready"));
  act(() => hook.result.current.select("AR-2000-001"));
  await waitFor(() => expect(hook.result.current.deckLayers.length).toBeGreaterThan(0));
  return hook;
}

test("drape view with relief: colors for the relief points, invisible but pickable cells, no contours", async () => {
  const { result } = await selected({ relief, view: "drape" });
  expect(result.current.drapeColors).toHaveLength(relief.length * 4);
  expect(result.current.deckLayers.map((l) => l.id)).toEqual(["ivt-ar-events"]);
  const raster = result.current.deckLayers[0]!.props as unknown as { pickable: boolean; getFillColor: (c: unknown) => number[] };
  expect(raster.pickable).toBe(true);
  expect(raster.getFillColor({ row: 0, col: 1 })).toEqual([0, 0, 0, 0]);
});

test("drape colors follow the frame", async () => {
  const { result } = await selected({ relief, view: "drape" });
  const f0 = Array.from(result.current.drapeColors!);
  act(() => result.current.seek(2)); // frames 100/110 -> 300/310: more IVT, different colors
  expect(Array.from(result.current.drapeColors!)).not.toEqual(f0);
});

test("drape view without relief keeps the colored cell raster and no drape colors", async () => {
  const { result } = await selected({ relief: null, view: "drape" });
  expect(result.current.drapeColors).toBeNull();
  expect(result.current.deckLayers.map((l) => l.id)).toEqual(["ivt-ar-events"]);
  act(() => result.current.seek(2)); // frame 2, cell (0, 0) = 300
  const raster = result.current.deckLayers[0]!.props as unknown as { getFillColor: (c: unknown) => number[] };
  expect(raster.getFillColor({ row: 0, col: 0 })).toEqual(ivtColor(300, "light", true));
});

test("isolines view: contour layers added, no drape, cells still give readings; switching back removes them", async () => {
  const { result, rerender } = await selected({ relief, view: "isolines" });
  expect(result.current.drapeColors).toBeNull();
  expect(result.current.deckLayers.map((l) => l.id)).toEqual([
    "ivt-ar-events",
    "ivt-contours-halo-ar-events",
    "ivt-contours-ar-events",
  ]);
  const raster = result.current.deckLayers[0]!.props as unknown as {
    pickable: boolean;
    getFillColor: (c: unknown) => number[];
    onHover: (i: { object: { row: number; col: number } }) => void;
  };
  expect(raster.pickable).toBe(true);
  expect(raster.getFillColor({ row: 0, col: 0 })).toEqual([0, 0, 0, 0]);
  act(() => raster.onHover({ object: { row: 0, col: 1 } }));
  expect(result.current.reading?.value).toBe(110);
  rerender({ relief, view: "drape" });
  expect(result.current.deckLayers.map((l) => l.id)).toEqual(["ivt-ar-events"]);
  expect(result.current.drapeColors).not.toBeNull();
});

// ---- footprints: count map without a selection, footprint + core + peak at the start of a replay ----

const eventA = { ...event, ivt_max_lat: -39, ivt_max_lon: -70 };
const eventB = { ...event, event_id: "AR-2000-002", start: "2000-07-21T00:00:00Z", end: "2000-07-21T03:00:00Z" };
const fpIndex = {
  ...index,
  events: { ...index.events, "AR-2000-002": { start: eventB.start, n_frames: 3, vmin: 100, vmax: 300 } },
  footprints: { file: "frames/footprints.bin", events: ["AR-2000-001", "AR-2000-002"], shape: [2, 1, 2] },
};
const fpLayer = { ...layer, files: [...layer.files, "frames/footprints.bin"] };
// A: [300, 100]; B: [600, 300]  ->  reaching 250: [2, 1]
const footprintBytes = new Float32Array([300, 100, 600, 300]).buffer;

function stubFootprintFetch() {
  const f = vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => (url.includes("frames%2Findex.json") ? fpIndex : [eventA, eventB]),
    arrayBuffer: async () => (url.includes("footprints") ? footprintBytes : frames),
  }));
  vi.stubGlobal("fetch", f);
  return f;
}
const ids = (r: { current: { deckLayers: { id: string }[] } }) => r.current.deckLayers.map((l) => l.id);

async function ready(opts: Parameters<typeof useArEvents>[2]) {
  const f = stubFootprintFetch();
  const hook = renderHook((o) => useArEvents(fpLayer, true, o), { initialProps: opts });
  await waitFor(() => expect(hook.result.current.status).toBe("ready"));
  return { ...hook, f };
}

test("no event selected: the count map of the filtered events, updating with the toggles", async () => {
  const { result, rerender, f } = await ready({ toggles: DEFAULT_TOGGLES });
  expect(f).toHaveBeenCalledWith("/api/layers/ar-events/data?file=frames%2Ffootprints.bin");
  await waitFor(() => expect(ids(result)).toEqual(["ar-count-ar-events"]));
  const cells = () => (result.current.deckLayers[0]!.props as unknown as { data: { row: number; col: number }[] }).data;
  expect(cells().map((c) => c.col)).toEqual([0, 1]);
  const fill = (result.current.deckLayers[0]!.props as unknown as { getFillColor: unknown }).getFillColor as unknown as (c: { row: number; col: number }) => number[];
  expect(fill({ row: 0, col: 0 })).toEqual(countColor(2, 2, "light"));
  expect(fill({ row: 0, col: 1 })).toEqual(countColor(1, 2, "light"));
  expect(result.current.count).toEqual({ n: 2, max: 2, from: "2000-03-10", to: "2000-07-21" });

  rerender({ toggles: { offYears: new Set(), offMonths: new Set(["2000-7"]) } }); // July off: only event A
  await waitFor(() => expect(result.current.count?.n).toBe(1));
  expect(cells().map((c) => c.col)).toEqual([0]);
  expect(result.current.count).toEqual({ n: 1, max: 1, from: "2000-03-10", to: "2000-03-10" });

  rerender({ toggles: { offYears: new Set([2000]), offMonths: new Set() } }); // everything off
  expect(result.current.count).toEqual({ n: 0, max: 0, from: null, to: null });
  expect(cells()).toEqual([]);
});

test("an index without footprints keeps the old behavior: no count map, hourly frames from the start", async () => {
  stubFetch();
  const { result } = renderHook(() => useArEvents(layer, true, { toggles: DEFAULT_TOGGLES }));
  await waitFor(() => expect(result.current.status).toBe("ready"));
  expect(result.current.count).toBeNull();
  expect(result.current.deckLayers).toEqual([]);
  act(() => result.current.select("AR-2000-001"));
  await waitFor(() => expect(ids(result)).toEqual(["ivt-ar-events"]));
});

test("selecting an event swaps the count map for its footprint, core outline and peak marker", async () => {
  const { result } = await ready({ toggles: DEFAULT_TOGGLES });
  await waitFor(() => expect(result.current.count).not.toBeNull());
  act(() => result.current.select("AR-2000-001"));
  await waitFor(() => expect(result.current.deckLayers.length).toBeGreaterThan(1));
  expect(result.current.count).toBeNull();
  expect(ids(result)).toEqual([
    "ivt-ar-events",
    "ivt-contours-halo-ar-events-core",
    "ivt-contours-ar-events-core",
    "ar-peak-ar-events",
  ]);
  const raster = result.current.deckLayers[0]!.props as unknown as { getFillColor: (c: unknown) => number[] };
  expect(raster.getFillColor({ row: 0, col: 0 })).toEqual(ivtColor(300, "light", true)); // footprint, not hour 0 (100)
  const core = result.current.deckLayers[2]!.props.data as { level: number }[];
  expect(core.every((d) => d.level === 250)).toBe(true); // footprint max 300 -> 250
  const peak = result.current.deckLayers[3]!.props.data as { position: number[] }[];
  expect(peak).toEqual([{ position: [-70, -39] }]);
});

test("playing or scrubbing shows the hourly frames again, keeping the peak marker", async () => {
  const { result } = await ready({ toggles: DEFAULT_TOGGLES });
  act(() => result.current.select("AR-2000-001"));
  await waitFor(() => expect(result.current.deckLayers.length).toBeGreaterThan(1));
  act(() => result.current.seek(1));
  expect(ids(result)).toEqual(["ivt-ar-events", "ar-peak-ar-events"]);
  const raster = result.current.deckLayers[0]!.props as unknown as { getFillColor: (c: unknown) => number[] };
  expect(raster.getFillColor({ row: 0, col: 0 })).toEqual(ivtColor(200, "light", true)); // frame 1
  act(() => result.current.seek(0));
  expect(ids(result)).toContain("ivt-contours-ar-events-core"); // back at the start: footprint again
  act(() => result.current.toggle()); // play
  expect(ids(result)).toEqual(["ivt-ar-events", "ar-peak-ar-events"]);
});

test("the reading in the footprint state is the event maximum of the cell", async () => {
  const { result } = await ready({ toggles: DEFAULT_TOGGLES });
  act(() => result.current.select("AR-2000-001"));
  await waitFor(() => expect(result.current.deckLayers.length).toBeGreaterThan(1));
  const raster = result.current.deckLayers[0]!.props as unknown as {
    onHover: (i: { object: { row: number; col: number } }) => void;
  };
  act(() => raster.onHover({ object: { row: 0, col: 1 } }));
  expect(result.current.reading).toMatchObject({ value: 100, kind: "max" });
  act(() => result.current.seek(1));
  expect(result.current.reading).toMatchObject({ value: 210, kind: "hour" });
});

test("turning the layer off empties deckLayers even though events, index and footprints stay loaded", async () => {
  stubFootprintFetch();
  const { result, rerender } = renderHook(({ active }) => useArEvents(fpLayer, active), { initialProps: { active: true } });
  await waitFor(() => expect(ids(result)).toEqual(["ar-count-ar-events"]));
  rerender({ active: false });
  expect(result.current.deckLayers).toEqual([]);
  rerender({ active: true });
  expect(ids(result)).toEqual(["ar-count-ar-events"]);
});

import { act, renderHook, waitFor } from "@testing-library/react";
import { vi } from "vitest";
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
  event_id: "AR-2000-001", start: "2000-03-10T06:00:00Z", end: "2000-03-10T09:00:00Z", duration_h: 3,
  n_steps: 1, prob_max: 0.8, area_frac_max: 0.5, ivt_max: 300, ivt_max_time: null, ivt_max_lat: null,
  ivt_max_lon: null, deg0l_max: null, deg0l_mean: null, tp_sum_mm: null, enso_phase: null,
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
  const { result, rerender } = renderHook(({ active }) => useArEvents(layer, active), { initialProps: { active: false } });
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
  expect((result.current.deckLayers[0]!.props as { data: unknown[] }).data).toHaveLength(ny * nx);
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

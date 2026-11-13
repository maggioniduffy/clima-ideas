import { renderHook, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { useFloodEvents, useFloodStation } from "./useFloodStation";

afterEach(() => vi.unstubAllGlobals());

test("idle without a station; loads stations/<id>.json when one is selected", async () => {
  const f = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ id: "1001", name: "A" }) }));
  vi.stubGlobal("fetch", f);
  const { result, rerender } = renderHook(({ id }) => useFloodStation("flood-stations", id), {
    initialProps: { id: null as string | null },
  });
  expect(result.current.status).toBe("idle");
  expect(f).not.toHaveBeenCalled();
  rerender({ id: "1001" });
  expect(result.current.status).toBe("loading");
  await waitFor(() => expect(result.current.status).toBe("ready"));
  expect(result.current.detail?.name).toBe("A");
  expect((f.mock.calls as unknown as string[][])[0]![0]).toBe("/api/layers/flood-stations/data?file=stations%2F1001.json");
  rerender({ id: "1001" });
  expect(f).toHaveBeenCalledTimes(1);
});

test("a failed request reports an error", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
  const { result } = renderHook(() => useFloodStation("flood-stations", "9"));
  await waitFor(() => expect(result.current.status).toBe("error"));
  expect(result.current.detail).toBeNull();
});

test("events are fetched lazily, only when enabled, once per station", async () => {
  const f = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ station_id: "1001", events: [] }) }));
  vi.stubGlobal("fetch", f);
  const { result, rerender } = renderHook(({ on }) => useFloodEvents("flood-stations", "1001", on), {
    initialProps: { on: false },
  });
  expect(result.current.status).toBe("idle");
  expect(f).not.toHaveBeenCalled();
  rerender({ on: true });
  await waitFor(() => expect(result.current.status).toBe("ready"));
  expect((f.mock.calls as unknown as string[][])[0]![0]).toBe("/api/layers/flood-stations/data?file=events%2F1001.json");
  rerender({ on: true });
  expect(f).toHaveBeenCalledTimes(1);
});

test("a missing events file reports an error", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
  const { result } = renderHook(() => useFloodEvents("flood-stations", "9", true));
  await waitFor(() => expect(result.current.status).toBe("error"));
});

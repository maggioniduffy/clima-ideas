import { vi } from "vitest";
import { fetchLayer, fetchLayerBinary, fetchLayerData, fetchLayers } from "./client";

function mockFetch(body: unknown, ok = true) {
  const f = vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 404, json: async () => body });
  vi.stubGlobal("fetch", f);
  return f;
}
afterEach(() => vi.unstubAllGlobals());

test("fetchLayers hits /api/layers", async () => {
  const f = mockFetch([{ id: "a" }]);
  expect(await fetchLayers()).toEqual([{ id: "a" }]);
  expect(f).toHaveBeenCalledWith("/api/layers");
});

test("fetchLayer hits /api/layers/{id}", async () => {
  const f = mockFetch({ id: "a" });
  await fetchLayer("a");
  expect(f).toHaveBeenCalledWith("/api/layers/a");
});

test("fetchLayerData hits /data with optional file", async () => {
  const f = mockFetch([]);
  await fetchLayerData("a");
  expect(f).toHaveBeenLastCalledWith("/api/layers/a/data");
  await fetchLayerData("a", "x y.json");
  expect(f).toHaveBeenLastCalledWith("/api/layers/a/data?file=x%20y.json");
});

test("non-ok responses reject", async () => {
  mockFetch({}, false);
  await expect(fetchLayers()).rejects.toThrow("404");
});

test("fetchLayerBinary returns the ArrayBuffer of a data file", async () => {
  const buf = new ArrayBuffer(12);
  const f = vi.fn().mockResolvedValue({ ok: true, status: 200, arrayBuffer: async () => buf });
  vi.stubGlobal("fetch", f);
  expect(await fetchLayerBinary("relief", "relief.bin")).toBe(buf);
  expect(f).toHaveBeenCalledWith("/api/layers/relief/data?file=relief.bin");
});

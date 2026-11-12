import { vi } from "vitest";
import {
  fetchFrames,
  fetchLayer,
  fetchLayerBinary,
  fetchLayerData,
  fetchLayers,
  resetLayerIndexCache,
  staticUrl,
} from "./client";

function mockFetch(body: unknown, ok = true) {
  const f = vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 404, json: async () => body });
  vi.stubGlobal("fetch", f);
  return f;
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  resetLayerIndexCache();
});

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

test("API mode keeps the frames URL", async () => {
  const f = vi.fn().mockResolvedValue({ ok: true, status: 200, arrayBuffer: async () => new ArrayBuffer(1) });
  vi.stubGlobal("fetch", f);
  await fetchFrames("ar", "e1/0");
  expect(f).toHaveBeenCalledWith("/api/layers/ar/frames/e1%2F0");
});

test("an empty VITE_DATA_URL stays in API mode", async () => {
  vi.stubEnv("VITE_DATA_URL", "");
  const f = mockFetch([]);
  await fetchLayers();
  expect(f).toHaveBeenCalledWith("/api/layers");
});

test("staticUrl encodes segments, keeps slashes and trims the base", () => {
  expect(staticUrl("https://h/", "a b", "frames/index.json")).toBe("https://h/a%20b/frames/index.json");
  expect(staticUrl("https://h", "a")).toBe("https://h/a");
});

describe("static mode", () => {
  const index = [{ id: "a", files: ["a.json", "b.json"] }];
  function routed(map: Record<string, unknown>) {
    const f = vi.fn(async (url: string) =>
      url in map
        ? { ok: true, status: 200, json: async () => map[url], arrayBuffer: async () => new ArrayBuffer(2) }
        : { ok: false, status: 404 },
    );
    vi.stubGlobal("fetch", f);
    return f;
  }
  beforeEach(() => vi.stubEnv("VITE_DATA_URL", "https://h/"));

  test("layers, manifest and explicit files", async () => {
    const f = routed({
      "https://h/layers.json": index,
      "https://h/a/manifest.json": { id: "a" },
      "https://h/a/frames/index.json": { units: "x" },
      "https://h/a/r.bin": null,
      "https://h/a/frames/e1.bin": null,
    });
    expect(await fetchLayers()).toEqual(index);
    expect(await fetchLayer("a")).toEqual({ id: "a" });
    expect(await fetchLayerData("a", "frames/index.json")).toEqual({ units: "x" });
    expect(f).toHaveBeenLastCalledWith("https://h/a/frames/index.json");
    await fetchLayerBinary("a", "r.bin");
    expect(f).toHaveBeenLastCalledWith("https://h/a/r.bin");
    await fetchFrames("a", "e1");
    expect(f).toHaveBeenLastCalledWith("https://h/a/frames/e1.bin");
  });

  test("default file comes from layers.json, fetched once", async () => {
    const f = routed({ "https://h/layers.json": index, "https://h/a/a.json": [] });
    await fetchLayerData("a");
    await fetchLayerData("a");
    expect(f.mock.calls.filter(([u]) => u === "https://h/layers.json")).toHaveLength(1);
    expect(f).toHaveBeenLastCalledWith("https://h/a/a.json");
  });

  test("default file falls back to the manifest when the id is not indexed", async () => {
    const f = routed({
      "https://h/layers.json": [],
      "https://h/z/manifest.json": { id: "z", files: ["z.json"] },
      "https://h/z/z.json": [],
    });
    await fetchLayerData("z");
    expect(f).toHaveBeenLastCalledWith("https://h/z/z.json");
  });
});

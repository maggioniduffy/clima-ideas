import { renderHook, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { isReliefLayer, useLayers } from "./useLayers";

const relief = {
  id: "relief",
  title: "Relieve",
  kind: "points",
  source: "DEM",
  period: "2021",
  license: "x",
  updated_at: "2026-01-01T00:00:00Z",
  files: ["relief.bin", "relief.meta.json"],
};

afterEach(() => vi.unstubAllGlobals());

test("relief layers turn on by themselves, load their .bin and yield a PointCloudLayer", async () => {
  const bin = new Float32Array([-70, -38, 100, -69, -37, 4000]).buffer;
  const f = vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => [relief],
    arrayBuffer: async () => bin,
    url,
  }));
  vi.stubGlobal("fetch", f);
  const { result } = renderHook(() => useLayers());
  await waitFor(() => expect(result.current.status).toBe("ready"));
  await waitFor(() => expect(result.current.deckLayers.map((l) => l.id)).toEqual(["relief-relief"]));
  expect(result.current.activeIds.has("relief")).toBe(true);
  expect(result.current.selectedId).toBeNull(); // turned on without selecting it
  expect(result.current.activeRelief?.layerId).toBe("relief");
  expect(f).toHaveBeenCalledWith("/api/layers/relief/data?file=relief.bin");
  expect(result.current.selectedFeatures).toEqual([]);
});

test("isReliefLayer picks the .bin points layers only", () => {
  expect(isReliefLayer(relief as never)).toBe(true);
  expect(isReliefLayer({ ...relief, files: ["p.json"] } as never)).toBe(false);
  expect(isReliefLayer({ ...relief, kind: "events" } as never)).toBe(false);
});

import { renderHook, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { LayerManifest } from "../api/client";
import { useConvectionIdf } from "./useConvectionIdf";

afterEach(() => vi.unstubAllGlobals());

const layer = { id: "convection-idf", files: ["idf.json", "replay.json", "frames/index.json"] } as unknown as LayerManifest;

test("a failed load is retried when the layer is switched off and on again", async () => {
  const f = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }));
  vi.stubGlobal("fetch", f);
  const { result, rerender } = renderHook(({ on }) => useConvectionIdf(layer, on), { initialProps: { on: true } });
  await waitFor(() => expect(result.current.status).toBe("error"));
  const first = f.mock.calls.length;
  expect(first).toBeGreaterThan(0);
  rerender({ on: true });
  expect(f).toHaveBeenCalledTimes(first); // still failed while active: no retry loop
  rerender({ on: false });
  rerender({ on: true });
  await waitFor(() => expect(f.mock.calls.length).toBeGreaterThan(first));
});

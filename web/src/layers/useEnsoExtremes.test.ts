import { renderHook, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { useEnsoExtremes } from "./useEnsoExtremes";

const base = {
  id: "ar-events",
  title: "Ríos atmosféricos",
  kind: "events" as const,
  source: "S",
  period: "2000-01-01/2000-12-31",
  license: "CC0",
  updated_at: "2026-01-01T00:00:00Z",
};
const withExt = { ...base, files: ["events.json", "frames/index.json", "enso-extremes.json"] };
const withoutExt = { ...base, files: ["events.json", "frames/index.json"] };
const payload = { meta: {}, variants: {}, robust: {} };

afterEach(() => vi.unstubAllGlobals());

test("layer without enso-extremes.json: status none and no request", () => {
  const f = vi.fn();
  vi.stubGlobal("fetch", f);
  const { result } = renderHook(() => useEnsoExtremes(withoutExt, true));
  expect(result.current.status).toBe("none");
  expect(f).not.toHaveBeenCalled();
});

test("fetches enso-extremes.json only once the layer is active", async () => {
  const f = vi.fn(async () => ({ ok: true, status: 200, json: async () => payload }));
  vi.stubGlobal("fetch", f);
  const { result, rerender } = renderHook(({ active }) => useEnsoExtremes(withExt, active), {
    initialProps: { active: false },
  });
  expect(result.current.status).toBe("loading");
  expect(f).not.toHaveBeenCalled();
  rerender({ active: true });
  await waitFor(() => expect(result.current.status).toBe("ready"));
  expect(f).toHaveBeenCalledWith("/api/layers/ar-events/data?file=enso-extremes.json");
  expect(result.current.data).toEqual(payload);
});

test("a failed request reads error", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })));
  const { result } = renderHook(() => useEnsoExtremes(withExt, true));
  await waitFor(() => expect(result.current.status).toBe("error"));
  expect(result.current.data).toBeNull();
});

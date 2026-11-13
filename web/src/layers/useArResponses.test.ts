import { renderHook, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { useArResponses } from "./useArResponses";

const base = {
  id: "ar-events",
  title: "Ríos atmosféricos",
  kind: "events" as const,
  source: "S",
  period: "2000-01-01/2000-12-31",
  license: "CC0",
  updated_at: "2026-01-01T00:00:00Z",
};
const withFile = { ...base, files: ["events.json", "responses.json"] };
const withoutFile = { ...base, files: ["events.json"] };
const payload = { source: "S", period: "P", window_days_after: 10, context_days_before: 3, note: "n", stations: [], events: {} };

afterEach(() => vi.unstubAllGlobals());

test("layer without responses.json: null data and no request", () => {
  const f = vi.fn();
  vi.stubGlobal("fetch", f);
  const { result } = renderHook(() => useArResponses(withoutFile, true));
  expect(result.current.data).toBeNull();
  expect(f).not.toHaveBeenCalled();
});

test("fetches responses.json only once the layer is active", async () => {
  const f = vi.fn(async () => ({ ok: true, status: 200, json: async () => payload }));
  vi.stubGlobal("fetch", f);
  const { result, rerender } = renderHook(({ active }) => useArResponses(withFile, active), {
    initialProps: { active: false },
  });
  expect(f).not.toHaveBeenCalled();
  rerender({ active: true });
  await waitFor(() => expect(result.current.data).toEqual(payload));
  expect(f).toHaveBeenCalledWith("/api/layers/ar-events/data?file=responses.json");
});

test("a failed request leaves null data and does not retry", async () => {
  const f = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }));
  vi.stubGlobal("fetch", f);
  const { result } = renderHook(() => useArResponses(withFile, true));
  await waitFor(() => expect(f).toHaveBeenCalled());
  expect(result.current.data).toBeNull();
  await new Promise((r) => setTimeout(r, 20));
  expect(f).toHaveBeenCalledTimes(1);
});

import { vi } from "vitest";
import {
  clampAll,
  clampSize,
  DEFAULT_SIZES,
  limitsFor,
  loadSizes,
  saveSizes,
  STORAGE_KEY,
  stepSize,
} from "./panelSizes";

const big = { width: 1920, height: 1080 };

beforeEach(() => localStorage.clear());

test("clamps each panel to its limits", () => {
  expect(clampSize("panels", 10, DEFAULT_SIZES, big)).toBe(320);
  expect(clampSize("panels", 9999, DEFAULT_SIZES, big)).toBe(640);
  expect(clampSize("timeline", 10, DEFAULT_SIZES, big)).toBe(80);
  expect(clampSize("timeline", 9999, DEFAULT_SIZES, big)).toBe(480);
  expect(clampSize("panels", NaN, DEFAULT_SIZES, big)).toBe(440);
  expect(clampSize("panels", 0, DEFAULT_SIZES, big)).toBe(0);
});

test("the map keeps at least 320 px wide and 400 px tall", () => {
  expect(limitsFor("panels", DEFAULT_SIZES, { width: 1000, height: 900 }).max).toBe(640);
  expect(limitsFor("panels", DEFAULT_SIZES, { width: 800, height: 900 }).max).toBe(800 - 16 - 8 - 320);
  // 700 - 56 header - 16 padding - 8 handle - 400 map
  expect(limitsFor("timeline", DEFAULT_SIZES, { width: 1000, height: 700 }).max).toBe(220);
});

test("min wins when the window is too small", () => {
  expect(limitsFor("panels", DEFAULT_SIZES, { width: 400, height: 300 })).toEqual({ min: 320, max: 320 });
  expect(limitsFor("timeline", DEFAULT_SIZES, { width: 400, height: 300 })).toEqual({ min: 80, max: 80 });
});

test("clampAll re-clamps after the window shrinks and keeps collapsed panels at 0", () => {
  const out = clampAll({ panels: 640, timeline: 480 }, { width: 900, height: 700 });
  expect(out.panels).toBeLessThanOrEqual(900 - 16 - 8 - 320);
  expect(out.timeline).toBeLessThanOrEqual(700 - 56 - 16 - 8 - 400);
  expect(clampAll({ panels: 0, timeline: 0 }, { width: 1100, height: 900 })).toEqual({ panels: 0, timeline: 0 });
});

test("keyboard step: 16 px, direction-aware, Home collapses, End maximizes, Enter restores the default", () => {
  expect(stepSize("ArrowRight", "vertical", 1, 200, 160, 480, 240)).toBe(216);
  expect(stepSize("ArrowLeft", "vertical", -1, 440, 320, 640, 440)).toBe(456);
  expect(stepSize("ArrowLeft", "vertical", -1, 260, 220, 720, 260)).toBe(276);
  expect(stepSize("ArrowUp", "horizontal", -1, 136, 80, 480, 136)).toBe(152);
  expect(stepSize("ArrowLeft", "vertical", 1, 165, 160, 480, 240)).toBe(160);
  expect(stepSize("ArrowRight", "vertical", 1, 0, 160, 480, 240)).toBe(160);
  expect(stepSize("ArrowLeft", "vertical", 1, 0, 160, 480, 240)).toBe(0);
  expect(stepSize("Home", "vertical", 1, 200, 160, 480, 240)).toBe(0);
  expect(stepSize("End", "vertical", 1, 200, 160, 480, 240)).toBe(480);
  expect(stepSize("Enter", "vertical", 1, 0, 160, 480, 240)).toBe(240);
  expect(stepSize("a", "vertical", 1, 200, 160, 480, 240)).toBeNull();
  expect(stepSize("ArrowUp", "vertical", 1, 200, 160, 480, 240)).toBeNull();
});

test("persistence round-trips, including a collapsed panel, and invalid storage falls back to defaults", () => {
  saveSizes({ panels: 500, timeline: 200 });
  expect(loadSizes()).toEqual({ panels: 500, timeline: 200 });
  saveSizes({ panels: 0, timeline: 200 });
  expect(loadSizes()).toEqual({ panels: 0, timeline: 200 });
  localStorage.setItem(STORAGE_KEY, "{not json");
  expect(loadSizes()).toEqual(DEFAULT_SIZES);
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ panels: "x", timeline: 100 }));
  expect(loadSizes()).toEqual({ ...DEFAULT_SIZES, timeline: 100 });
  // sizes between 0 and the minimum are not a state the handles produce
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ panels: 50, timeline: 100 }));
  expect(loadSizes()).toEqual({ ...DEFAULT_SIZES, timeline: 100 });
});

test("older stored shapes (inspector width; layers / cards) fall back to the defaults", () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ layers: 300, inspector: 500, timeline: 200 }));
  expect(loadSizes()).toEqual(DEFAULT_SIZES);
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ layers: 300, cards: 200, timeline: 200 }));
  expect(loadSizes()).toEqual(DEFAULT_SIZES);
});

test("storage that throws does not break load or save", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("denied");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("denied");
  });
  expect(loadSizes()).toEqual(DEFAULT_SIZES);
  expect(() => saveSizes(DEFAULT_SIZES)).not.toThrow();
  vi.restoreAllMocks();
});

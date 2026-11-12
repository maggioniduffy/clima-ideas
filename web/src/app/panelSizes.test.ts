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
  expect(clampSize("layers", 10, DEFAULT_SIZES, big)).toBe(160);
  expect(clampSize("layers", 9999, DEFAULT_SIZES, big)).toBe(480);
  expect(clampSize("cards", 10, DEFAULT_SIZES, big)).toBe(160);
  expect(clampSize("cards", 9999, DEFAULT_SIZES, big)).toBe(456); // 1080 - 56 - 16 - 16 - 400 - 136
  expect(clampSize("timeline", 10, DEFAULT_SIZES, big)).toBe(80);
  expect(clampSize("timeline", 9999, DEFAULT_SIZES, big)).toBe(332); // 592 - 260
  expect(clampSize("layers", NaN, DEFAULT_SIZES, big)).toBe(240);
  expect(clampSize("layers", 0, DEFAULT_SIZES, big)).toBe(0);
});

test("the map keeps at least 320 px wide and 400 px tall", () => {
  const vp = { width: 1000, height: 900 };
  expect(limitsFor("layers", DEFAULT_SIZES, vp).max).toBe(480);
  expect(limitsFor("layers", DEFAULT_SIZES, { width: 700, height: 900 }).max).toBe(700 - 16 - 8 - 320);
  // 900 - 56 header - 16 padding - 16 handles - 400 map - 136 timeline
  expect(limitsFor("cards", DEFAULT_SIZES, vp).max).toBe(276);
  expect(limitsFor("timeline", { ...DEFAULT_SIZES, cards: 0 }, vp).max).toBe(412);
});

test("min wins when the window is too small", () => {
  expect(limitsFor("layers", DEFAULT_SIZES, { width: 400, height: 300 })).toEqual({ min: 160, max: 160 });
  expect(limitsFor("cards", DEFAULT_SIZES, { width: 400, height: 300 })).toEqual({ min: 160, max: 160 });
});

test("clampAll re-clamps after the window shrinks and keeps collapsed panels at 0", () => {
  const out = clampAll({ layers: 480, cards: 520, timeline: 480 }, { width: 1100, height: 900 });
  expect(out.layers).toBeLessThanOrEqual(1100 - 16 - 8 - 320);
  expect(out.cards + out.timeline).toBeLessThanOrEqual(900 - 56 - 16 - 16 - 400);
  expect(clampAll({ layers: 0, cards: 0, timeline: 0 }, { width: 1100, height: 900 })).toEqual({ layers: 0, cards: 0, timeline: 0 });
});

test("keyboard step: 16 px, direction-aware, Home collapses, End maximizes, Enter restores the default", () => {
  expect(stepSize("ArrowRight", "vertical", 1, 200, 160, 480, 240)).toBe(216);
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
  saveSizes({ layers: 300, cards: 200, timeline: 200 });
  expect(loadSizes()).toEqual({ layers: 300, cards: 200, timeline: 200 });
  saveSizes({ layers: 0, cards: 0, timeline: 200 });
  expect(loadSizes()).toEqual({ layers: 0, cards: 0, timeline: 200 });
  localStorage.setItem(STORAGE_KEY, "{not json");
  expect(loadSizes()).toEqual(DEFAULT_SIZES);
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ layers: "x", cards: 99999, timeline: 100 }));
  expect(loadSizes()).toEqual({ ...DEFAULT_SIZES, timeline: 100 });
  // sizes between 0 and the minimum are not a state the handles produce
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ layers: 50, cards: -5, timeline: 100 }));
  expect(loadSizes()).toEqual({ ...DEFAULT_SIZES, timeline: 100 });
});

test("the old stored shape (with an inspector width) falls back to the defaults", () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ layers: 300, inspector: 500, timeline: 200 }));
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

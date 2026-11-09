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
  expect(clampSize("inspector", 10, DEFAULT_SIZES, big)).toBe(220);
  expect(clampSize("inspector", 9999, DEFAULT_SIZES, big)).toBe(720);
  expect(clampSize("timeline", 10, DEFAULT_SIZES, big)).toBe(80);
  expect(clampSize("timeline", 9999, DEFAULT_SIZES, big)).toBe(480);
  expect(clampSize("layers", NaN, DEFAULT_SIZES, big)).toBe(200);
});

test("the map keeps at least 320 px wide and 200 px tall", () => {
  const vp = { width: 1000, height: 500 };
  expect(limitsFor("layers", { ...DEFAULT_SIZES, inspector: 400 }, vp).max).toBe(280);
  expect(limitsFor("inspector", { ...DEFAULT_SIZES, layers: 300 }, vp).max).toBe(380);
  expect(limitsFor("timeline", DEFAULT_SIZES, vp).max).toBe(252);
});

test("min wins when the window is too small", () => {
  expect(limitsFor("layers", DEFAULT_SIZES, { width: 400, height: 300 })).toEqual({ min: 160, max: 160 });
});

test("clampAll re-clamps after the window shrinks", () => {
  const out = clampAll({ layers: 480, inspector: 720, timeline: 480 }, { width: 1100, height: 600 });
  expect(out.layers + out.inspector).toBeLessThanOrEqual(1100 - 320);
  expect(out.timeline).toBeLessThanOrEqual(600 - 48 - 200);
});

test("keyboard step: 16 px, direction-aware, Home/End, other keys ignored", () => {
  expect(stepSize("ArrowRight", "vertical", 1, 200, 160, 480)).toBe(216);
  expect(stepSize("ArrowLeft", "vertical", -1, 260, 220, 720)).toBe(276);
  expect(stepSize("ArrowUp", "horizontal", -1, 136, 80, 480)).toBe(152);
  expect(stepSize("ArrowLeft", "vertical", 1, 165, 160, 480)).toBe(160);
  expect(stepSize("Home", "vertical", 1, 200, 160, 480)).toBe(160);
  expect(stepSize("End", "vertical", 1, 200, 160, 480)).toBe(480);
  expect(stepSize("a", "vertical", 1, 200, 160, 480)).toBeNull();
  expect(stepSize("ArrowUp", "vertical", 1, 200, 160, 480)).toBeNull();
});

test("persistence round-trips and invalid storage falls back to defaults", () => {
  saveSizes({ layers: 300, inspector: 500, timeline: 200 });
  expect(loadSizes()).toEqual({ layers: 300, inspector: 500, timeline: 200 });
  localStorage.setItem(STORAGE_KEY, "{not json");
  expect(loadSizes()).toEqual(DEFAULT_SIZES);
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ layers: "x", inspector: 99999, timeline: 100 }));
  expect(loadSizes()).toEqual({ ...DEFAULT_SIZES, timeline: 100 });
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

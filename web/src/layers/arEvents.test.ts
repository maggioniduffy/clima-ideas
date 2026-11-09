import type { ArEvent, FrameGrid } from "../api/client";
import {
  eventSpans,
  formatUtc,
  fractionOf,
  frameTime,
  frameValue,
  gridCells,
  ivtColor,
  IVT_ALPHA_HIGH,
  IVT_ALPHA_LOW,
  IVT_ALPHA_MAX,
  IVT_SCALE_MAX,
  legendTicks,
  parseFrames,
  periodDomain,
  rgbCss,
} from "./arEvents";
import { tokens } from "../theme/tokens";

const grid: FrameGrid = { ny: 2, nx: 3, lat_min: -40, lat_max: -39, lon_min: -71, lon_max: -69 };

const ev = (id: string, start: string, end: string, ivt: number | null): ArEvent => ({
  event_id: id,
  start,
  end,
  duration_h: 6,
  n_steps: 1,
  prob_max: 0.8,
  area_frac_max: 0.5,
  ivt_max: ivt,
  ivt_max_time: null,
  ivt_max_lat: null,
  ivt_max_lon: null,
  deg0l_max: null,
  deg0l_mean: null,
  tp_sum_mm: null,
  enso_phase: null,
});

test("parseFrames decodes Float32 [n, ny, nx] and rejects wrong sizes", () => {
  const raw = new Float32Array(2 * 2 * 3).map((_, i) => i);
  const frames = parseFrames(raw.buffer, grid, 2);
  expect(frames.length).toBe(12);
  expect(() => parseFrames(raw.buffer, grid, 3)).toThrow();
  expect(() => parseFrames(new ArrayBuffer(7), grid, 1)).toThrow();
});

test("frameValue indexes by frame, row (south first) and column; NaN and out of range are null", () => {
  const raw = new Float32Array(12).map((_, i) => i);
  raw[5] = NaN;
  expect(frameValue(raw, grid, 0, 0, 0)).toBe(0);
  expect(frameValue(raw, grid, 0, 1, 2)).toBeNull();
  expect(frameValue(raw, grid, 1, 0, 1)).toBe(7);
  expect(frameValue(raw, grid, 1, 1, 2)).toBe(11);
  expect(frameValue(raw, grid, 0, 2, 0)).toBeNull();
  expect(frameValue(raw, grid, 0, 0, 3)).toBeNull();
});

const rgb = (c: number[]) => c.slice(0, 3);
const hexRgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const luma = ([r, g, b]: number[]) => 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;

test.each(["light", "dark"] as const)("ivtColor (%s) follows the token ramp and saturates at IVT_SCALE_MAX", (theme) => {
  const stops = tokens.ivtRamp[theme];
  expect(IVT_SCALE_MAX).toBe(1200);
  expect(rgb(ivtColor(0, theme))).toEqual(hexRgb(stops[0]!));
  expect(rgb(ivtColor(IVT_SCALE_MAX, theme))).toEqual(hexRgb(stops[5]!));
  expect(rgb(ivtColor(IVT_SCALE_MAX / 5, theme))).toEqual(hexRgb(stops[1]!)); // stops are evenly spaced
  expect(ivtColor(IVT_SCALE_MAX * 5, theme)).toEqual(ivtColor(IVT_SCALE_MAX, theme));
  expect(ivtColor(-50, theme)).toEqual(ivtColor(0, theme));
  expect(ivtColor(1000, theme)).not.toEqual(ivtColor(IVT_SCALE_MAX, theme)); // strong events stay distinguishable
  // midpoint between two stops is the channel-wise average
  const mid = ivtColor(IVT_SCALE_MAX * 0.1, theme);
  expect(Math.abs(mid[0]! - (hexRgb(stops[0]!)[0]! + hexRgb(stops[1]!)[0]!) / 2)).toBeLessThanOrEqual(1);
});

test.each(["light", "dark"] as const)("ivtColor (%s) is monotonic in lightness and separates non-AR from AR values", (theme) => {
  const l = (v: number) => luma(ivtColor(v, theme));
  const sign = theme === "light" ? -1 : 1; // light: deeper = stronger; dark: brighter = stronger
  for (let v = 0; v < IVT_SCALE_MAX; v += 100) expect(sign * (l(v + 100) - l(v))).toBeGreaterThan(0);
  // low (non-AR, < 250) is clearly lower-key than a typical AR band value
  expect(sign * (l(600) - l(100))).toBeGreaterThan(40);
});

test("ivtColor: missing values are transparent; opaque swatches stay fully opaque", () => {
  expect(ivtColor(null, "light")[3]).toBe(0);
  expect(ivtColor(NaN, "dark")[3]).toBe(0);
  expect(ivtColor(undefined, "dark")[3]).toBe(0);
  for (const theme of ["light", "dark"] as const) {
    expect(ivtColor(0, theme)[3]).toBe(255);
    expect(ivtColor(500, theme)[3]).toBe(255);
  }
});

test.each(["light", "dark"] as const)("ivtColor (%s) translucent alpha fades to ~0 below IVT_ALPHA_LOW and saturates at IVT_ALPHA_HIGH", (theme) => {
  expect(IVT_ALPHA_LOW).toBe(150);
  expect(IVT_ALPHA_HIGH).toBe(400);
  const a = (v: number) => ivtColor(v, theme, true)[3];
  expect(a(0)).toBe(0);
  expect(a(100)).toBe(0);
  expect(a(IVT_ALPHA_LOW)).toBe(0);
  expect(a(IVT_ALPHA_HIGH)).toBe(Math.round(255 * IVT_ALPHA_MAX));
  expect(a(IVT_SCALE_MAX)).toBe(Math.round(255 * IVT_ALPHA_MAX));
  for (let v = 0; v < IVT_ALPHA_HIGH + 50; v += 10) expect(a(v + 10)).toBeGreaterThanOrEqual(a(v));
  expect(a(275)).toBeGreaterThan(0);
  expect(a(275)).toBeLessThan(a(IVT_ALPHA_HIGH));
  // color channels are unaffected by the alpha ramp
  expect(ivtColor(600, theme, true).slice(0, 3)).toEqual(ivtColor(600, theme).slice(0, 3));
});

test("legendTicks spans 0..IVT_SCALE_MAX and labels the saturation value '≥1200'", () => {
  const ticks = legendTicks();
  expect(ticks.map((t) => t.value)).toEqual([0, 300, 600, 900, 1200]);
  expect(ticks.map((t) => t.fraction)).toEqual([0, 0.25, 0.5, 0.75, 1]);
  expect(ticks.map((t) => t.label)).toEqual(["0", "300", "600", "900", "≥1200"]);
  expect(legendTicks(2).map((t) => t.label)).toEqual(["0", "600", "≥1200"]);
});

test("gridCells covers the grid with half-step rectangles centered on each point", () => {
  const cells = gridCells(grid);
  expect(cells).toHaveLength(6);
  expect(cells[0]).toMatchObject({ row: 0, col: 0, lon: -71, lat: -40 });
  expect(cells[0]!.polygon).toEqual([
    [-71.5, -40.5],
    [-70.5, -40.5],
    [-70.5, -39.5],
    [-71.5, -39.5],
  ]);
  expect(cells[5]).toMatchObject({ row: 1, col: 2, lon: -69, lat: -39 });
});

test("periodDomain parses the manifest period with the last day inclusive", () => {
  const d = periodDomain("2000-01-01/2000-01-02")!;
  expect(d[0]).toBe(Date.parse("2000-01-01T00:00:00Z"));
  expect(d[1]).toBe(Date.parse("2000-01-03T00:00:00Z"));
  expect(periodDomain("bad")).toBeNull();
  expect(periodDomain("2001-01-01/2000-01-01")).toBeNull();
});

test("eventSpans maps events to fractions of the domain with IVT-max colors", () => {
  const domain = periodDomain("2000-01-01/2000-01-03")!; // 3 days (last day inclusive)
  const spans = eventSpans(
    [ev("a", "2000-01-02T00:00:00Z", "2000-01-02T12:00:00Z", 0), ev("b", "1999-12-01T00:00:00Z", "2000-01-01T06:00:00Z", null)],
    domain,
    "light",
  );
  expect(spans[0]!.left).toBeCloseTo(1 / 3);
  expect(spans[0]!.width).toBeCloseTo(0.5 / 3);
  expect(spans[0]!.color).toBe(rgbCss(ivtColor(0, "light")));
  expect(spans[1]).toMatchObject({ id: "b", left: 0 });
  expect(spans[1]!.width).toBeCloseTo(0.25 / 3);
});

test("frameTime and fractionOf locate the replay cursor", () => {
  const t = frameTime("2000-01-01T06:00:00Z", 3);
  expect(formatUtc(t)).toBe("2000-01-01 09:00 UTC");
  const d: [number, number] = [Date.parse("2000-01-01T06:00:00Z"), Date.parse("2000-01-01T12:00:00Z")];
  expect(fractionOf(t, d)).toBeCloseTo(0.5);
  expect(fractionOf(d[0] - 1000, d)).toBe(0);
  expect(fractionOf(d[1] + 1000, d)).toBe(1);
});

import type { ArEvent, FrameGrid } from "../api/client";
import {
  eventSpans,
  formatUtc,
  fractionOf,
  frameTime,
  frameValue,
  gridCells,
  ivtColor,
  IVT_SCALE_MAX,
  parseFrames,
  periodDomain,
} from "./arEvents";

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

test("ivtColor ramps secondary to accent, saturates, and hides missing values", () => {
  expect(ivtColor(0)).toEqual([0xa4, 0xaf, 0x69, 255]);
  expect(ivtColor(IVT_SCALE_MAX)).toEqual([0x8e, 0xb8, 0xe5, 255]);
  expect(ivtColor(IVT_SCALE_MAX * 5)).toEqual(ivtColor(IVT_SCALE_MAX));
  expect(ivtColor(null)[3]).toBe(0);
  expect(ivtColor(NaN)[3]).toBe(0);
  expect(ivtColor(0, true)[3]).toBeLessThan(ivtColor(IVT_SCALE_MAX, true)[3]);
  expect(ivtColor(IVT_SCALE_MAX, true)[3]).toBeLessThan(256);
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
  );
  expect(spans[0]!.left).toBeCloseTo(1 / 3);
  expect(spans[0]!.width).toBeCloseTo(0.5 / 3);
  expect(spans[0]!.color).toBe("rgb(164, 175, 105)");
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

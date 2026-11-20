import { expect, test } from "vitest";
import { cumulativeAt, curveFor, rainAlpha, rainColor, type IdfRow } from "./convectionIdf";
import { tokens } from "../theme/tokens";

const row = (d: number, t: number): IdfRow => ({
  d, t, depth_mm: 1, intensity_mm_h: 1, depth_lo: 1, depth_hi: 1, intensity_lo: 1, intensity_hi: 1, extrapolated: false,
}); // fmt: skip

test("curveFor selects one return period sorted by duration", () => {
  expect(curveFor([row(24, 2), row(1, 5), row(1, 2)], 2).map((r) => r.d)).toEqual([1, 24]);
});

test("rain color: dry and missing are transparent, ramp ends match the tokens, alpha rises", () => {
  expect(rainColor(null, "light")[3]).toBe(0);
  expect(rainColor(0.05, "light")[3]).toBe(0);
  const hex = tokens.rainRamp.light[4]!;
  expect(rainColor(50, "light").slice(0, 3)).toEqual([parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]);
  expect(rainColor(50, "light")[3]).toBe(Math.round(255 * 0.9));
  expect(rainAlpha(0.3)).toBeGreaterThan(0);
  expect(rainAlpha(0.3)).toBeLessThan(rainAlpha(0.5));
});

test("cumulativeAt interpolates and is null outside the series", () => {
  const c = { start: "2014-04-06T12:00:00Z", step_minutes: 30, mm: [0, 10, 30] };
  expect(cumulativeAt(c, Date.parse("2014-04-06T11:30:00Z"))).toBeNull();
  expect(cumulativeAt(c, Date.parse("2014-04-06T12:30:00Z"))).toBe(10);
  expect(cumulativeAt(c, Date.parse("2014-04-06T12:45:00Z"))).toBe(20);
  expect(cumulativeAt(c, Date.parse("2014-04-06T13:30:00Z"))).toBeNull();
});

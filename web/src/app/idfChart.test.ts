import { expect, test } from "vitest";
import { durationLabel, logDomain, logTicks, spreadLabels, utcTickLabel } from "./idfChart";

test("duration labels", () => {
  expect(durationLabel(0.5)).toBe("30 min");
  expect(durationLabel(1)).toBe("1 h");
  expect(durationLabel(24)).toBe("24 h");
});

test("log ticks are 1, 2 and 5 per decade inside the range", () => {
  expect(logTicks(1, 100)).toEqual([1, 2, 5, 10, 20, 50, 100]);
  expect(logTicks(1.4, 7)).toEqual([2, 5]);
  expect(logTicks(0.1, 1)).toEqual([0.1, 0.2, 0.5, 1]);
});

test("log domain extends outward to the nearest ticks", () => {
  expect(logDomain(1.49, 44.9)).toEqual([1, 50]);
  expect(logDomain(2, 5)).toEqual([2, 5]);
  expect(logDomain(0.3, 0.9)).toEqual([0.2, 1]);
});

test("UTC tick label", () => {
  expect(utcTickLabel(Date.parse("2014-04-07T12:00:00Z"))).toBe("7/4 12Z");
  expect(utcTickLabel(Date.parse("2014-04-08T00:00:00Z"))).toBe("8/4 00Z");
});

test("end-of-curve labels keep a minimum gap and stay above the x tick labels", () => {
  const bottom = 200 - 3; // plot bottom minus margin: x tick labels start below it
  const out = spreadLabels([150, 170, 185, 190, 191, 192], 14, 8, bottom);
  for (let i = 1; i < out.length; i++) expect(out[i]! - out[i - 1]!).toBeGreaterThanOrEqual(14 - 1e-9);
  expect(Math.max(...out)).toBeLessThanOrEqual(bottom);
  expect(Math.min(...out)).toBeGreaterThanOrEqual(8);
  expect(spreadLabels([50, 120], 14, 8, bottom)).toEqual([50, 120]);
  expect(spreadLabels([], 14, 8, bottom)).toEqual([]);
  // too many for the range: the gap shrinks but order and bounds hold
  const tight = spreadLabels([10, 11, 12, 13], 14, 8, 30);
  expect(tight[0]).toBeGreaterThanOrEqual(8);
  expect(tight[3]).toBeLessThanOrEqual(30);
  expect([...tight].sort((a, b) => a - b)).toEqual(tight);
});

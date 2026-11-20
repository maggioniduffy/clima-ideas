import { expect, test } from "vitest";
import { durationLabel, logDomain, logTicks, utcTickLabel } from "./idfChart";

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

import {
  bandPath,
  dayOffset,
  downsampleMax,
  formatDateEs,
  isoAddDays,
  linearScale,
  linearTicks,
  linePath,
  logScale,
  niceMax,
  RETURN_TICKS,
  yearTicks,
} from "./floodCharts";

test("linear scale maps the domain onto the range (inverted ranges too)", () => {
  const y = linearScale(0, 100, 50, 10);
  expect(y(0)).toBe(50);
  expect(y(100)).toBe(10);
  expect(y(50)).toBe(30);
});

test("log scale puts equal ratios at equal distances", () => {
  const x = logScale(1, 100, 0, 200);
  expect(x(1)).toBeCloseTo(0);
  expect(x(10)).toBeCloseTo(100);
  expect(x(100)).toBeCloseTo(200);
  expect(RETURN_TICKS).toEqual([2, 5, 10, 25, 50, 100, 200]);
});

test("niceMax rounds up to 1, 2, 2.5, 5 or 10 times a power of ten", () => {
  expect(niceMax(0)).toBe(1);
  expect(niceMax(928)).toBe(1000);
  expect(niceMax(10649)).toBe(20000);
  expect(niceMax(2100)).toBe(2500);
  expect(niceMax(4200)).toBe(5000);
  expect(niceMax(1000)).toBe(1000);
  expect(linearTicks(1000, 4)).toEqual([0, 250, 500, 750, 1000]);
});

test("day and date helpers", () => {
  expect(dayOffset("2000-04-01", "2000-04-11")).toBe(10);
  expect(dayOffset("2000-02-28", "2000-03-01")).toBe(2); // leap year
  expect(isoAddDays("2000-04-01", 10)).toBe("2000-04-11");
  expect(formatDateEs("2023-06-26")).toBe("26/06/2023");
});

test("downsampleMax keeps the peak of every bucket and respects the limit", () => {
  const v = Array.from({ length: 10_000 }, (_, i) => (i === 4321 ? 999 : 1));
  const out = downsampleMax(v, 2000);
  expect(out.length).toBeLessThanOrEqual(2000);
  expect(out.find((b) => b.value === 999)?.index).toBe(4321);
  const short = downsampleMax([1, null, 3], 2000);
  expect(short).toEqual([
    { index: 0, value: 1 },
    { index: 1, value: null },
    { index: 2, value: 3 },
  ]);
});

test("downsampleMax marks an all-gap bucket as null", () => {
  const out = downsampleMax([null, null, 5, 6], 2);
  expect(out).toEqual([
    { index: 0, value: null },
    { index: 3, value: 6 },
  ]);
});

test("linePath breaks at nulls", () => {
  expect(linePath([{ x: 0, y: 1 }, { x: 1, y: 2 }, null, { x: 3, y: 4 }])).toBe("M0 1L1 2M3 4");
  expect(linePath([null, null])).toBe("");
});

test("bandPath closes upper edge then reversed lower edge", () => {
  const up = [{ x: 0, y: 0 }, { x: 10, y: 0 }];
  const lo = [{ x: 0, y: 5 }, { x: 10, y: 5 }];
  expect(bandPath(up, lo)).toBe("M0 0L10 0L10 5L0 5Z");
  expect(bandPath([], lo)).toBe("");
});

test("yearTicks returns January 1st marks inside the range", () => {
  const t = yearTicks("1945-01-01", "2026-03-31", 4);
  expect(t.length).toBeGreaterThan(1);
  expect(t.every((k) => k.iso >= "1945-01-01" && k.iso <= "2026-03-31")).toBe(true);
  expect(yearTicks("2000-04-01", "2000-09-01")).toEqual([]);
});

import { eventYMax, forecastBandPath, forecastPoints, issueLabel, persistencePoints } from "./floodCharts";
import type { FloodEvent, FloodEventIssue } from "../layers/useFloodStation";

const issue = (over: Partial<FloodEventIssue> = {}): FloodEventIssue => ({
  issue_date: "2023-06-23",
  days_before_peak: 3,
  persistence: 100,
  median: [110, 150, 200],
  lo: [90, 100, 120],
  hi: [130, 200, 300],
  ...over,
});

test("forecast points: lead k lands k days after the issue day on the event axis", () => {
  const pts = forecastPoints("2023-06-12", issue());
  expect(pts.map((p) => p.day)).toEqual([12, 13, 14]); // issue on day 11 (23 Jun - 12 Jun)
  expect(pts[1]).toEqual({ day: 13, median: 150, lo: 100, hi: 200 });
});

test("persistence holds the issue-day flow flat over the leads; none when the flow is a gap", () => {
  const p = persistencePoints("2023-06-12", issue());
  expect(p.map((q) => q.x)).toEqual([11, 12, 13, 14]);
  expect(new Set(p.map((q) => q.y))).toEqual(new Set([100]));
  expect(persistencePoints("2023-06-12", issue({ persistence: null }))).toEqual([]);
});

test("forecast band polygon needs two leads with both edges", () => {
  const x = (d: number) => d * 10;
  const y = (v: number) => 1000 - v;
  const pts = forecastPoints("2023-06-12", issue());
  expect(forecastBandPath(pts, x, y)).toBe("M120 870L130 800L140 700L140 880L130 900L120 910Z");
  expect(forecastBandPath(pts.slice(0, 1), x, y)).toBe("");
  const gaps = forecastPoints("2023-06-12", issue({ lo: [null, null, 120] }));
  expect(forecastBandPath(gaps, x, y)).toBe("");
});

test("event y max covers the observed flow and every issue's band, so the axis is fixed", () => {
  const ev: FloodEvent = {
    peak_date: "2023-06-26",
    peak_q: 480,
    hydro_year: 2023,
    obs: { start: "2023-06-12", q: [10, null, 480] },
    issues: [issue({ hi: [130, 200, 900] }), issue()],
  };
  expect(eventYMax(ev)).toBe(1000);
});

test("issue label in Spanish", () => {
  expect(issueLabel(7)).toBe("Emitido 7 días antes del pico");
  expect(issueLabel(1)).toBe("Emitido 1 día antes del pico");
  expect(issueLabel(0)).toBe("Emitido el día del pico");
});

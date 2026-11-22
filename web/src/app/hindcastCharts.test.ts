import { bandBetween, forecastDomain, makeScales, niceTicks, seriesPoints, skillByLead, skillDomain } from "./hindcastCharts";
import type { HindcastEvent, SkillPoint } from "../layers/hindcast";

const ev = (over: Partial<HindcastEvent> = {}): HindcastEvent => ({
  event_id: "E",
  date: "2001-05-02",
  obs_mm: 11.9,
  mean: [7, 6, null],
  min: [6, 5, null],
  max: [8, 22.3, null],
  ...over,
});

test("niceTicks covers the range with 1/2/2.5/5 steps", () => {
  expect(niceTicks(0, 22.3)).toEqual({ lo: 0, hi: 25, ticks: [0, 5, 10, 15, 20, 25] });
  expect(niceTicks(-0.3, 1)).toEqual({ lo: -0.5, hi: 1, ticks: [-0.5, 0, 0.5, 1] });
  expect(niceTicks(0, 0).ticks.length).toBeGreaterThan(1); // degenerate range still has an axis
});

test("forecastDomain starts at 0 and holds the ensemble maximum and the observed value", () => {
  expect(forecastDomain(ev()).hi).toBe(25);
  expect(forecastDomain(ev({ max: [1, 1, null], mean: [1, 1, null], obs_mm: 30 })).hi).toBeGreaterThanOrEqual(30);
  expect(forecastDomain(ev()).lo).toBe(0);
});

test("skillDomain tops out at 1 and includes negative interval ends", () => {
  const pts: SkillPoint[] = [
    { lead: 1, value: 0.8, lo: 0.7, hi: 0.9 },
    { lead: 2, value: 0.1, lo: -0.4, hi: 0.5 },
  ];
  const d = skillDomain(pts);
  expect(d.hi).toBe(1);
  expect(d.lo).toBeLessThanOrEqual(-0.4);
  expect(skillDomain([{ lead: 1, value: 0.5, lo: 0.4, hi: 0.6 }]).lo).toBe(0); // 0 stays on the axis
});

test("scales map leads and values into the plot; missing values leave gaps", () => {
  const dom = niceTicks(0, 10);
  const s = makeScales([1, 2, 3], dom, 300, 200, { l: 40, r: 10, t: 20, b: 30 });
  expect(s.x(1)).toBe(40);
  expect(s.x(3)).toBe(290);
  expect(s.y(dom.lo)).toBe(170);
  expect(s.y(dom.hi)).toBe(20);
  const pts = seriesPoints([1, 2, 3], [5, null, 10], s);
  expect(pts[1]).toBeNull();
  expect(pts[2]).toEqual({ x: 290, y: 20 });
});

test("bandBetween skips leads without both ends and is empty without data", () => {
  const dom = niceTicks(0, 10);
  const s = makeScales([1, 2, 3], dom, 300, 200, { l: 40, r: 10, t: 20, b: 30 });
  expect(bandBetween([1, 2, 3], [1, null, 2], [3, 4, 5], s)).toMatch(/^M.*Z$/);
  expect(bandBetween([1, 2, 3], [null, null, null], [3, 4, 5], s)).toBe("");
});

test("skillByLead aligns records to the leads", () => {
  const pts: SkillPoint[] = [{ lead: 2, value: 0.5, lo: 0.1, hi: 0.9 }];
  expect(skillByLead(pts, [1, 2, 3], "value")).toEqual([null, 0.5, null]);
  expect(skillByLead(pts, [1, 2, 3], "lo")).toEqual([null, 0.1, null]);
});

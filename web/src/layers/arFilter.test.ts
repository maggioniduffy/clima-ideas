import type { ArEvent } from "../api/client";
import {
  DEFAULT_TOGGLES,
  TOP_N,
  filterEvents,
  groupByYearMonth,
  isMonthOn,
  isYearOn,
  rankEvents,
  responseRatios,
  revealEvent,
  toggleMonth,
  toggleYear,
  visibleEvents,
} from "./arFilter";

const ev = (id: string, start: string, o: Partial<ArEvent> = {}): ArEvent => ({
  event_id: id, start, end: start, duration_h: 6, n_steps: 1, prob_max: 0.8, area_frac_max: 0.5, ivt_max: 300,
  ivt_max_time: null, ivt_max_lat: null, ivt_max_lon: null, deg0l_max: null, deg0l_mean: null, tp_sum_mm: 10,
  enso_phase: null, ...o,
}); // fmt: skip

const events = [
  ev("c", "2001-01-05T00:00:00Z", { ivt_max: 500, tp_sum_mm: 5, duration_h: 30 }),
  ev("a", "2000-03-10T06:00:00Z", { ivt_max: 900, tp_sum_mm: 40, duration_h: 12 }),
  ev("b", "2000-03-20T06:00:00Z", { ivt_max: null, tp_sum_mm: null, duration_h: 48 }),
  ev("d", "2000-07-01T00:00:00Z", { ivt_max: 700, tp_sum_mm: 90, duration_h: 6 }),
];

test("groups by year then month, ascending, with only the months that have events", () => {
  const g = groupByYearMonth(events);
  expect(g.map((y) => [y.year, y.events.length])).toEqual([[2000, 3], [2001, 1]]);
  expect(g[0].months.map((m) => [m.month, m.events.map((e) => e.event_id)])).toEqual([[3, ["a", "b"]], [7, ["d"]]]);
  expect(g[1].months.map((m) => m.month)).toEqual([1]);
});

test("everything is on by default", () => {
  expect(filterEvents(events, DEFAULT_TOGGLES)).toHaveLength(4);
  expect(isYearOn(DEFAULT_TOGGLES, 2000)).toBe(true);
  expect(isMonthOn(DEFAULT_TOGGLES, 2000, 3)).toBe(true);
});

test("toggling a year off removes all of its events, and back on restores them", () => {
  const off = toggleYear(DEFAULT_TOGGLES, 2000);
  expect(isYearOn(off, 2000)).toBe(false);
  expect(filterEvents(events, off).map((e) => e.event_id)).toEqual(["c"]);
  expect(filterEvents(events, toggleYear(off, 2000))).toHaveLength(4);
});

test("toggling a month off removes only that month of that year", () => {
  const off = toggleMonth(DEFAULT_TOGGLES, 2000, 3);
  expect(isMonthOn(off, 2000, 3)).toBe(false);
  expect(isMonthOn(off, 2001, 3)).toBe(true);
  expect(filterEvents(events, off).map((e) => e.event_id)).toEqual(["c", "d"]);
});

test("toggling does not mutate the previous state", () => {
  toggleYear(DEFAULT_TOGGLES, 2000);
  toggleMonth(DEFAULT_TOGGLES, 2000, 3);
  expect(isYearOn(DEFAULT_TOGGLES, 2000)).toBe(true);
  expect(isMonthOn(DEFAULT_TOGGLES, 2000, 3)).toBe(true);
});

test("ranks by each key, highest first, with missing values last", () => {
  expect(rankEvents(events, "ivt_max").map((e) => e.event_id)).toEqual(["a", "d", "c", "b"]);
  expect(rankEvents(events, "tp_sum_mm").map((e) => e.event_id)).toEqual(["d", "a", "c", "b"]);
  expect(rankEvents(events, "duration_h").map((e) => e.event_id)).toEqual(["b", "c", "a", "d"]);
});

test("visibleEvents without top N keeps the filtered set in order", () => {
  const v = visibleEvents(events, toggleYear(DEFAULT_TOGGLES, 2001), "ivt_max", false);
  expect(v.events.map((e) => e.event_id)).toEqual(["a", "b", "d"]);
  expect(v.peakIds.size).toBe(0);
});

test("top N takes the N highest of the filtered set by the chosen key, ranked", () => {
  expect(TOP_N).toBe(10);
  const v = visibleEvents(events, toggleYear(DEFAULT_TOGGLES, 2001), "tp_sum_mm", true, 2);
  expect(v.events.map((e) => e.event_id)).toEqual(["d", "a"]);
  expect([...v.peakIds].sort()).toEqual(["a", "d"]);
  expect(v.filtered.map((e) => e.event_id)).toEqual(["a", "b", "d"]); // the timeline still draws the whole filtered set
});

test("top N ignores events that are toggled off, even if they rank first", () => {
  const v = visibleEvents(events, toggleMonth(DEFAULT_TOGGLES, 2000, 7), "tp_sum_mm", true, 1);
  expect(v.events.map((e) => e.event_id)).toEqual(["a"]);
});

const responses = (events: Record<string, (number | null)[]>) =>
  ({
    source: "S", period: "P", window_days_after: 10, context_days_before: 3, note: "n", stations: [],
    events: Object.fromEntries(
      Object.entries(events).map(([id, ratios]) => [
        id,
        ratios.map((ratio, i) => ({
          station_id: String(i), q_before: 1, q_peak: 2, peak_date: "2000-01-01", lag_days: 0, ratio,
          daily: { start: "2000-01-01", q: [] },
        })),
      ]),
    ),
  }) as import("../api/client").ArResponses; // fmt: skip

test("responseRatios takes the largest ratio per event and skips events without one", () => {
  const r = responseRatios(responses({ a: [1.2, 4.5], b: [null], c: [] }));
  expect([...r]).toEqual([["a", 4.5]]);
  expect(responseRatios(null).size).toBe(0);
});

test("q_response ranks by the largest ratio and puts events without a response last", () => {
  const ratios = responseRatios(responses({ d: [2], c: [9] }));
  expect(rankEvents(events, "q_response", ratios).map((e) => e.event_id)).toEqual(["c", "d", "a", "b"]);
  // without ratios nothing has a response: the order is unchanged
  expect(rankEvents(events, "q_response").map((e) => e.event_id)).toEqual(["c", "a", "b", "d"]);
});

test("visibleEvents ranks the top N by response when given the ratios", () => {
  const ratios = responseRatios(responses({ d: [2], a: [7] }));
  const v = visibleEvents(events, DEFAULT_TOGGLES, "q_response", true, 2, ratios);
  expect(v.events.map((e) => e.event_id)).toEqual(["a", "d"]);
  expect([...v.peakIds].sort()).toEqual(["a", "d"]);
});

test("revealEvent switches the event's year and month back on and leaves the rest", () => {
  const off = toggleMonth(toggleMonth(toggleYear(DEFAULT_TOGGLES, 2000), 2000, 3), 2000, 7);
  const t = revealEvent(off, events[1]!); // a: 2000-03
  expect(isYearOn(t, 2000)).toBe(true);
  expect(isMonthOn(t, 2000, 3)).toBe(true);
  expect(isMonthOn(t, 2000, 7)).toBe(false);
  expect(revealEvent(DEFAULT_TOGGLES, events[1]!)).toBe(DEFAULT_TOGGLES);
});

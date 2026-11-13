import type { ArEvent } from "../api/client";

/** Number of events the "top N" switch keeps. */
export const TOP_N = 10;

/** Keys the peaks can be ranked by; a later task adds the largest caudal response. */
export type SortKey = "ivt_max" | "tp_sum_mm" | "duration_h";
export const SORT_KEYS: readonly SortKey[] = ["ivt_max", "tp_sum_mm", "duration_h"];

/** Everything starts on, so the state only records what is off: years, and months as "YYYY-M". */
export interface ArToggles {
  offYears: ReadonlySet<number>;
  offMonths: ReadonlySet<string>;
}
export const DEFAULT_TOGGLES: ArToggles = { offYears: new Set(), offMonths: new Set() };

export interface MonthGroup {
  month: number; // 1-12
  events: ArEvent[];
}
export interface YearGroup {
  year: number;
  events: ArEvent[];
  months: MonthGroup[];
}

const yearOf = (e: ArEvent) => Number(e.start.slice(0, 4));
const monthOf = (e: ArEvent) => Number(e.start.slice(5, 7));
const monthKey = (year: number, month: number) => `${year}-${month}`;

/** Events grouped by year, then month (UTC, from `start`); only months that have events. Ascending. */
export function groupByYearMonth(events: ArEvent[]): YearGroup[] {
  const years = new Map<number, Map<number, ArEvent[]>>();
  for (const e of [...events].sort((a, b) => a.start.localeCompare(b.start))) {
    const months = years.get(yearOf(e)) ?? new Map<number, ArEvent[]>();
    months.set(monthOf(e), [...(months.get(monthOf(e)) ?? []), e]);
    years.set(yearOf(e), months);
  }
  return [...years]
    .sort(([a], [b]) => a - b)
    .map(([year, months]) => {
      const ms = [...months].sort(([a], [b]) => a - b).map(([month, evs]) => ({ month, events: evs }));
      return { year, events: ms.flatMap((m) => m.events), months: ms };
    });
}

export const isYearOn = (t: ArToggles, year: number) => !t.offYears.has(year);
export const isMonthOn = (t: ArToggles, year: number, month: number) => !t.offMonths.has(monthKey(year, month));

const flip = <T>(s: ReadonlySet<T>, v: T): Set<T> => {
  const next = new Set(s);
  if (!next.delete(v)) next.add(v);
  return next;
};
export const toggleYear = (t: ArToggles, year: number): ArToggles => ({ ...t, offYears: flip(t.offYears, year) });
export const toggleMonth = (t: ArToggles, year: number, month: number): ArToggles => ({
  ...t,
  offMonths: flip(t.offMonths, monthKey(year, month)),
});

/** Events whose year and month are both on. */
export const filterEvents = (events: ArEvent[], t: ArToggles) =>
  events.filter((e) => isYearOn(t, yearOf(e)) && isMonthOn(t, yearOf(e), monthOf(e)));

/** Highest first by `key`; events without a value go last. Stable otherwise. */
export function rankEvents(events: ArEvent[], key: SortKey): ArEvent[] {
  const v = (e: ArEvent) => e[key] ?? Number.NEGATIVE_INFINITY;
  return [...events].sort((a, b) => v(b) - v(a));
}

export interface VisibleEvents {
  /** Every event whose year and month are on: what the timeline draws. */
  filtered: ArEvent[];
  /** What the list shows: the filtered set, or the ranked top N of it. */
  events: ArEvent[];
  /** Ids drawn larger on the timeline; empty unless top N is on. */
  peakIds: ReadonlySet<string>;
}

export function visibleEvents(
  events: ArEvent[],
  toggles: ArToggles,
  key: SortKey,
  topOn: boolean,
  n: number = TOP_N,
): VisibleEvents {
  const filtered = filterEvents(events, toggles);
  if (!topOn) return { filtered, events: filtered, peakIds: new Set() };
  const top = rankEvents(filtered, key).slice(0, n);
  return { filtered, events: top, peakIds: new Set(top.map((e) => e.event_id)) };
}

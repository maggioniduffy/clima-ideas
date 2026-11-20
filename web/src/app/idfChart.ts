/** Pure chart math for the IDF panel: log ticks and labels. Scales and paths come from floodCharts. */

/** "30 min" for half an hour, otherwise "N h" (decimal comma). */
export const durationLabel = (h: number): string =>
  h < 1 ? `${Math.round(h * 60)} min` : `${String(h).replace(".", ",")} h`;

/** Ticks 1, 2 and 5 times a power of ten inside [lo, hi] (lo > 0). */
export function logTicks(lo: number, hi: number): number[] {
  const out: number[] = [];
  for (let p = Math.floor(Math.log10(lo)); p <= Math.ceil(Math.log10(hi)); p++) {
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** p;
      if (v >= lo * (1 - 1e-9) && v <= hi * (1 + 1e-9)) out.push(Number(v.toPrecision(6)));
    }
  }
  return out;
}

/** Smallest log tick (1/2/5 x 10^k) >= v and largest <= v: the domain edges of a log axis that holds [min, max]. */
export function logDomain(min: number, max: number): [number, number] {
  const all = logTicks(min / 10, max * 10);
  const lo = [...all].reverse().find((v) => v <= min * (1 + 1e-9)) ?? min;
  const hi = all.find((v) => v >= max * (1 - 1e-9)) ?? max;
  return [lo, hi];
}

/** "d/m hhZ" (UTC) of a time in ms, for the comparison chart's axis. */
export const utcTickLabel = (ms: number): string => {
  const d = new Date(ms);
  return `${d.getUTCDate()}/${d.getUTCMonth() + 1} ${String(d.getUTCHours()).padStart(2, "0")}Z`;
};

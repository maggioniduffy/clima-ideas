import { describe, expect, test } from "vitest";
import { buildStrip, jitter, phaseMeans, STRIP_PHASES } from "./ensoChart";

const sy = (year: number, phase: string, v: number | null) => ({ year, phase, value: v });

describe("jitter", () => {
  test("is deterministic and stays within +-1", () => {
    for (let y = 1980; y <= 2025; y++) {
      expect(jitter(y)).toBe(jitter(y));
      expect(Math.abs(jitter(y))).toBeLessThanOrEqual(1);
    }
    expect(new Set([1980, 1981, 1982, 1983].map(jitter)).size).toBeGreaterThan(1);
  });
});

describe("phaseMeans", () => {
  test("averages the non-null values of each phase and gives null for an empty phase", () => {
    const m = phaseMeans([sy(1, "nino", 2), sy(2, "nino", 4), sy(3, "nino", null), sy(4, "nina", 1)]);
    expect(m).toEqual({ nino: 3, neutral: null, nina: 1 });
  });
});

describe("buildStrip", () => {
  const size = { width: 300, height: 200, margin: { top: 10, right: 10, bottom: 30, left: 40 } };

  test("skips null values and unknown phases, one dot per remaining season-year", () => {
    const s = buildStrip([sy(1, "nino", 1), sy(2, "nino", null), sy(3, "neutral", 2), sy(4, "x", 3)], size);
    expect(s.dots.map((d) => d.year)).toEqual([1, 3]);
  });

  test("columns follow the phase order and dots stay inside their column and the plot", () => {
    const data = [sy(1980, "nino", 5), sy(1981, "neutral", 0), sy(1982, "nina", 10)];
    const s = buildStrip(data, size);
    expect(s.columns.map((c) => c.phase)).toEqual([...STRIP_PHASES]);
    for (const d of s.dots) {
      const c = s.columns.find((c) => c.phase === d.phase)!;
      expect(Math.abs(d.x - c.cx)).toBeLessThanOrEqual(c.halfWidth);
      expect(d.y).toBeGreaterThanOrEqual(size.margin.top);
      expect(d.y).toBeLessThanOrEqual(size.height - size.margin.bottom);
    }
  });

  test("y axis starts at 0 with a nice max covering the data, larger value is higher on screen", () => {
    const s = buildStrip([sy(1, "nino", 3), sy(2, "nina", 7)], size);
    expect(s.ticks[0].value).toBe(0);
    expect(s.ticks[s.ticks.length - 1].value).toBeGreaterThanOrEqual(7);
    const hi = s.dots.find((d) => d.value === 7)!;
    const lo = s.dots.find((d) => d.value === 3)!;
    expect(hi.y).toBeLessThan(lo.y);
  });

  test("mean ticks sit at the phase mean; no data gives a valid empty axis", () => {
    const s = buildStrip([sy(1, "nino", 2), sy(2, "nino", 4)], size);
    const m = s.means.find((m) => m.phase === "nino")!;
    expect(m.value).toBe(3);
    expect(s.means.find((m) => m.phase === "nina")).toBeUndefined();
    const e = buildStrip([], size);
    expect(e.dots).toEqual([]);
    expect(e.ticks.length).toBeGreaterThan(1);
  });
});

import { readFileSync } from "node:fs";
import {
  colorDomain,
  criticalDuration,
  debrisColor,
  fmtQ,
  logFraction,
  peakAt,
  peakRange,
  rankCatchments,
  visibleFeatures,
  isRanked,
  type CatchmentCollection,
  type DebrisPeaks,
} from "./debrisCatchments";
import { tokens } from "../theme/tokens";

const dir = "e2e/fixtures/processed/debris-catchments/";
const geo = JSON.parse(readFileSync(dir + "catchments.geojson", "utf8")) as CatchmentCollection;
const peaks = JSON.parse(readFileSync(dir + "peaks.json", "utf8")) as DebrisPeaks;

test("ranking orders by peak for the chosen T and CN, ties by id", () => {
  const r = rankCatchments(geo.features, peaks, "hsg-c", 10);
  expect(r.map((x) => x.id)).toEqual([0, 2, 3, 1]);
  expect(r.map((x) => x.rank)).toEqual([1, 2, 3, 4]);
  expect(rankCatchments(geo.features, peaks, "hsg-c", 10, 2)).toHaveLength(2);
  expect(rankCatchments(geo.features, peaks, "nope", 10)).toEqual([]);
});

test("range across CN scenarios brackets the central value; critical duration is read per T", () => {
  const range = peakRange(peaks, 0, 25)!;
  expect(range.central).toBe(peakAt(peaks, 0, "hsg-c", 25));
  expect(range.lo).toBe(peakAt(peaks, 0, "hsg-b", 25));
  expect(range.hi).toBe(peakAt(peaks, 0, "hsg-d", 25));
  expect(range.lo).toBeLessThan(range.central);
  expect(criticalDuration(peaks, 0, "hsg-c", 25)).toBeGreaterThan(0);
  expect(peakAt(peaks, 0, "hsg-c", 7)).toBeNull();
});

test("color scale is logarithmic, neutral (token ramp) and handles degenerate input", () => {
  expect(colorDomain([0, -1, 2, 8])).toEqual([2, 8]);
  expect(colorDomain([0])).toBeNull();
  expect(logFraction(4, [1, 16])).toBeCloseTo(0.5);
  expect(logFraction(0, [1, 16])).toBe(0);
  expect(logFraction(5, [3, 3])).toBe(0.5);
  const lo = debrisColor(0, "light");
  const hi = debrisColor(1, "light");
  expect(lo.slice(0, 3)).toEqual([0xec, 0xe8, 0xee]);
  expect(hi.slice(0, 3)).toEqual([0x4b, 0x3b, 0x78]);
  // no red/amber/green anywhere on the ramp: blue channel never below red and green
  for (const theme of ["light", "dark"] as const)
    for (const c of tokens.debrisRamp[theme]) {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
      expect(b!).toBeGreaterThanOrEqual(Math.max(r!, g!));
    }
});

test("discharge uses three significant digits with a decimal comma", () => {
  expect(fmtQ(0.0173)).toBe("0,0173");
  expect(fmtQ(12.352)).toBe("12,4");
});

test("planar-flow and overlapping catchments are left out of the ranking but planar ones can be shown on the map", () => {
  expect(geo.features.map((f) => f.properties.id)).toContain(4);
  expect(geo.features.find((f) => f.properties.id === 4)!.properties.planar_flow).toBe(true);
  const ids = rankCatchments(geo.features, peaks, "hsg-c", 10).map((x) => x.id);
  expect(ids).toEqual([0, 2, 3, 1]); // the planar strip 4 has a large peak but is not ranked
  expect(peakAt(peaks, 4, "hsg-c", 10)).toBeGreaterThan(0);
  expect(visibleFeatures(geo.features, false).map((f) => f.properties.id)).toEqual([0, 1, 2, 3]);
  expect(visibleFeatures(geo.features, true)).toHaveLength(5);
  const overlapping = { ...geo.features[1]!, properties: { ...geo.features[1]!.properties, overlaps_id: 0 } };
  expect(isRanked(overlapping.properties)).toBe(false);
  expect(rankCatchments([geo.features[0]!, overlapping], peaks, "hsg-c", 10).map((x) => x.id)).toEqual([0]);
  expect(isRanked({ ...geo.features[0]!.properties, planar_flow: undefined, overlaps_id: undefined })).toBe(true);
});

import { PointCloudLayer } from "@deck.gl/layers";
import {
  buildReliefLayer,
  hillshade,
  parseRelief,
  pointInRing,
  RELIEF_EXAGGERATION,
  RELIEF_STEP,
  RELIEF_STOPS_M,
  reliefColor,
  reliefColors,
} from "./reliefLayer";
import { tokens } from "../theme/tokens";

const buffer = (vals: number[]) => new Float32Array(vals).buffer;

/** Regular grid of `nx` x `ny` points (south-west first, rows ascending in lat) with elevation f(ix, iy). */
function grid(nx: number, ny: number, f: (ix: number, iy: number) => number, lon0 = -70, lat0 = -38) {
  const v: number[] = [];
  for (let iy = 0; iy < ny; iy++)
    for (let ix = 0; ix < nx; ix++) v.push(lon0 + ix * RELIEF_STEP, lat0 + iy * RELIEF_STEP, f(ix, iy));
  return buffer(v);
}

const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

test("parseRelief reads interleaved lon/lat/elev and exaggerates z", () => {
  const r = parseRelief(buffer([-70, -38, 100, -69, -37, 4000]));
  expect(r.length).toBe(2);
  expect(Array.from(r.positions)).toEqual([-70, -38, 100 * RELIEF_EXAGGERATION, -69, -37, 4000 * RELIEF_EXAGGERATION]);
  expect(Array.from(r.elevation)).toEqual([100, 4000]);
  expect(reliefColors(r, "light").length).toBe(2 * 4);
});

test.each(["light", "dark"] as const)("%s hypsometric ramp hits each token at its elevation stop", (theme) => {
  tokens.reliefRamp[theme].forEach((t, i) => expect(reliefColor(RELIEF_STOPS_M[i]!, theme)).toEqual(hex(t)));
  expect(reliefColor(-20, theme)).toEqual(hex(tokens.reliefRamp[theme][0]!));
  expect(reliefColor(6000, theme)).toEqual(hex(tokens.reliefRamp[theme][5]!));
  // midway between stops 0 and 1 is the average of both tokens
  const mid = reliefColor(RELIEF_STOPS_M[1]! / 2, theme);
  const [a, b] = [hex(tokens.reliefRamp[theme][0]!), hex(tokens.reliefRamp[theme][1]!)];
  mid.forEach((c, k) => expect(Math.abs(c - (a[k]! + b[k]!) / 2)).toBeLessThanOrEqual(1));
});

test("hypsometric ramp goes green lowland to brown mountains to pale peaks", () => {
  const [lr, lg, lb] = reliefColor(0, "light");
  expect(lg).toBeGreaterThan(lb);
  const [pr, pg, pb] = reliefColor(4600, "light");
  expect(Math.min(pr, pg, pb)).toBeGreaterThan(200);
  expect(reliefColor(2000, "light")[0]).toBeGreaterThan(reliefColor(2000, "light")[2]); // warm brown
  expect(lr).toBeGreaterThan(0);
});

test("hillshade: flat is 1, NW-facing slopes are lit, SE-facing slopes are dark", () => {
  expect(hillshade(0, 0)).toBeCloseTo(1, 5);
  // terrain rising to the SE (z grows east and south) faces NW, toward the sun
  expect(hillshade(0.3, -0.3)).toBeGreaterThan(1);
  // terrain rising to the NW faces SE, away from the sun
  expect(hillshade(-0.3, 0.3)).toBeLessThan(0.7);
});

test("parseRelief shades a ramp using grid neighbours, independent of point order", () => {
  // elevation rises to the east: east-sloping ground faces west, so it is lit more than flat (NW sun azimuth 315)
  const ordered = parseRelief(grid(4, 4, (ix) => 1000 + ix * 100));
  const flat = parseRelief(grid(4, 4, () => 1000));
  expect(flat.shade[5]).toBeCloseTo(1, 5);
  // rising east: normal tilts west, toward the sun's x component (negative): lit > flat
  expect(ordered.shade[5]).toBeGreaterThan(1);
  // slope facing away: rising to the west
  const away = parseRelief(grid(4, 4, (ix) => 1000 - ix * 100));
  expect(away.shade[5]).toBeLessThan(1);
  // shuffled points produce the same shade per location
  const buf = new Float32Array(grid(4, 4, (ix) => 1000 + ix * 100));
  const pts = Array.from({ length: 16 }, (_, i) => Array.from(buf.slice(i * 3, i * 3 + 3))).reverse();
  const rev = parseRelief(buffer(pts.flat()));
  expect(rev.shade[16 - 1 - 5]).toBeCloseTo(ordered.shade[5]!, 5);
});

test("pointInRing ray-casts a concave ring", () => {
  const ring: [number, number][] = [[0, 0], [4, 0], [4, 4], [2, 1], [0, 4]];
  expect(pointInRing(1, 1, ring)).toBe(true);
  expect(pointInRing(2, 3, ring)).toBe(false); // in the notch
  expect(pointInRing(5, 1, ring)).toBe(false);
});

test("parseRelief drops points outside the province but shades them from the full grid first", () => {
  const province: [number, number][] = [
    [-70 + 1.5 * RELIEF_STEP, -38 - 1],
    [-70 + 10, -38 - 1],
    [-70 + 10, -38 + 1],
    [-70 + 1.5 * RELIEF_STEP, -38 + 1],
    [-70 + 1.5 * RELIEF_STEP, -38 - 1],
  ];
  const data = grid(4, 4, (ix) => 1000 + ix * 100);
  const all = parseRelief(data);
  const clipped = parseRelief(data, province);
  expect(all.length).toBe(16);
  expect(clipped.length).toBe(8); // columns 2 and 3 only
  expect(Array.from(clipped.elevation)).toEqual([1200, 1300, 1200, 1300, 1200, 1300, 1200, 1300]);
  // point at column 2 keeps the shade computed with its dropped column-1 neighbour (not an edge fallback)
  expect(clipped.shade[0]).toBeCloseTo(all.shade[2]!, 6);
});

test("parseRelief rejects a buffer that is not a multiple of the stride", () => {
  expect(() => parseRelief(new ArrayBuffer(10))).toThrow();
});

test("colors are tint x hillshade, cached per theme, and differ between themes", () => {
  const r = parseRelief(grid(3, 3, () => 2000));
  const light = reliefColors(r, "light");
  expect(Array.from(light.slice(0, 3))).toEqual(reliefColor(2000, "light"));
  expect(reliefColors(r, "light")).toBe(light);
  expect(Array.from(reliefColors(r, "dark").slice(0, 3))).not.toEqual(Array.from(light.slice(0, 3)));
});

test("buildReliefLayer returns a PointCloudLayer with binary attributes", () => {
  const layer = buildReliefLayer("relief", parseRelief(buffer([-70, -38, 100])), "dark");
  expect(layer).toBeInstanceOf(PointCloudLayer);
  expect(layer.id).toBe("relief-relief");
});

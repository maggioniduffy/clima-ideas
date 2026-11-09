import { PointCloudLayer } from "@deck.gl/layers";
import {
  buildDrapeSampler,
  buildReliefLayer,
  DRAPE_NEUTRAL,
  drapeColor,
  drapeColors,
  hillshade,
  parseRelief,
  RELIEF_EXAGGERATION,
  RELIEF_STEP,
  RELIEF_STOPS_M,
  reliefColor,
  reliefColors,
  sampleIvt,
} from "./reliefLayer";
import { ivtColor } from "./arEvents";
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

test.each(["light", "dark"] as const)("%s slate ramp hits each token at its elevation stop", (theme) => {
  tokens.reliefRamp[theme].forEach((t, i) => expect(reliefColor(RELIEF_STOPS_M[i]!, theme)).toEqual(hex(t)));
  expect(reliefColor(-20, theme)).toEqual(hex(tokens.reliefRamp[theme][0]!));
  expect(reliefColor(6000, theme)).toEqual(hex(tokens.reliefRamp[theme][3]!));
  // midway between stops 0 and 1 is the average of both tokens
  const mid = reliefColor(RELIEF_STOPS_M[1]! / 2, theme);
  const [a, b] = [hex(tokens.reliefRamp[theme][0]!), hex(tokens.reliefRamp[theme][1]!)];
  mid.forEach((c, k) => expect(Math.abs(c - (a[k]! + b[k]!) / 2)).toBeLessThanOrEqual(1));
});

test("slate ramp is monochrome: light theme darkens with height, dark theme lightens", () => {
  const lum = (c: number[]) => c[0]! + c[1]! + c[2]!;
  const ls = [0, 800, 1800, 3000].map((m) => lum(reliefColor(m, "light")));
  const ds = [0, 800, 1800, 3000].map((m) => lum(reliefColor(m, "dark")));
  for (let i = 1; i < 4; i++) {
    expect(ls[i]!).toBeLessThan(ls[i - 1]!);
    expect(ds[i]!).toBeGreaterThan(ds[i - 1]!);
  }
  const [r, g, b] = reliefColor(1500, "light");
  expect(Math.abs(r - b)).toBeLessThan(40); // slate, not green/brown
  expect(g).toBeGreaterThan(0);
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

test("parseRelief keeps every point and shades by the grid step", () => {
  const r = parseRelief(
    grid(4, 4, (ix) => 1000 + ix * 100),
    RELIEF_STEP,
  );
  expect(r.length).toBe(16);
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

// --- IVT drape ---------------------------------------------------------------------------------------------------

const gray = (shade: number) => Math.min(1, Math.max(0, 0.35 + 0.75 * shade));

test("drapeColor: no IVT is the theme neutral x shade, with no ramp hue", () => {
  for (const theme of ["light", "dark"] as const) {
    const [r, g, b] = drapeColor(0, 1, theme);
    [r, g, b].forEach((v, c) => expect(v).toBeCloseTo(255 * DRAPE_NEUTRAL[theme][c]! * gray(1), -0.5));
    expect(drapeColor(null, 1, theme)).toEqual([r, g, b]);
    expect(drapeColor(100, 1, theme)).toEqual([r, g, b]); // below IVT_ALPHA_LOW
  }
});

test("drapeColor: IVT >= 400 is the ramp color x gray; shade modulates brightness; theme switches the ramp", () => {
  for (const theme of ["light", "dark"] as const) {
    const ramp = ivtColor(800, theme);
    const lit = drapeColor(800, 1, theme);
    [0, 1, 2].forEach((c) => expect(Math.abs(lit[c]! - ramp[c]! * gray(1))).toBeLessThanOrEqual(1));
    expect(drapeColor(500, 1, theme)).toEqual(drapeColor(500, 1, theme));
    const dark = drapeColor(800, 0.25, theme);
    expect(dark[0] + dark[1] + dark[2]).toBeLessThan(lit[0] + lit[1] + lit[2]);
  }
  expect(drapeColor(800, 1, "light")).not.toEqual(drapeColor(800, 1, "dark"));
  // between the thresholds the color sits between the neutral gray and the ramp color
  const mid = drapeColor(275, 1, "light");
  expect(mid).not.toEqual(drapeColor(0, 1, "light"));
  expect(mid).not.toEqual(drapeColor(400, 1, "light"));
});

const g2 = {
  ny: 2,
  nx: 2,
  lat_min: -39,
  lat_max: -38,
  lon_min: -70,
  lon_max: -69,
};
const f2 = new Float32Array([100, 200, 300, 500]); // row 0 (south): 100, 200; row 1: 300, 500

test("bilinear sampling: grid nodes return the node value, midpoints the average", () => {
  const relief = parseRelief(
    buffer([-70, -39, 0, -69, -39, 0, -70, -38, 0, -69, -38, 0, -69.5, -38.5, 0, -69.5, -39, 0]),
  );
  const sampler = buildDrapeSampler(relief, g2);
  const at = (i: number) => sampleIvt(sampler, f2, 0, i);
  expect(at(0)).toBeCloseTo(100, 3);
  expect(at(1)).toBeCloseTo(200, 3);
  expect(at(2)).toBeCloseTo(300, 3);
  expect(at(3)).toBeCloseTo(500, 3);
  expect(at(4)).toBeCloseTo(275, 3); // center: mean of the 4 nodes
  expect(at(5)).toBeCloseTo(150, 3); // south edge midpoint
});

test("bilinear sampling reads the requested frame and clamps points outside the grid", () => {
  const relief = parseRelief(buffer([-71, -40, 0, -69, -38, 0]));
  const sampler = buildDrapeSampler(relief, g2);
  const two = new Float32Array([...f2, 1, 2, 3, 4]);
  expect(sampleIvt(sampler, two, 1, 0)).toBeCloseTo(1, 3); // clamped to the SW node
  expect(sampleIvt(sampler, two, 1, 1)).toBeCloseTo(4, 3);
});

test("drapeColors paints every point like drapeColor on the sampled IVT and shade", () => {
  const relief = parseRelief(
    grid(5, 4, (ix, iy) => 500 + ix * 40 + iy * 25),
    RELIEF_STEP,
  );
  const g = {
    ny: 2,
    nx: 2,
    lat_min: -38,
    lat_max: -37.97,
    lon_min: -70,
    lon_max: -69.97,
  };
  const sampler = buildDrapeSampler(relief, g);
  const frames = new Float32Array([0, 0, 0, 0, 900, 700, 500, 300]);
  const out = drapeColors(relief, sampler, frames, 1, "dark");
  expect(out.length).toBe(relief.length * 4);
  for (const i of [0, 7, relief.length - 1]) {
    const exp = drapeColor(sampleIvt(sampler, frames, 1, i), relief.shade[i]!, "dark");
    [0, 1, 2].forEach((c) => expect(Math.abs(out[i * 4 + c]! - exp[c]!)).toBeLessThanOrEqual(1));
    expect(out[i * 4 + 3]).toBe(255);
  }
  // an event frame of zeros is the plain gray-shaded relief
  const calm = drapeColors(relief, sampler, frames, 0, "dark");
  expect(Array.from(calm.slice(0, 3))).toEqual(drapeColor(0, relief.shade[0]!, "dark"));
});

test("buildReliefLayer accepts a color override (drape) in place of the slate colors", () => {
  const r = parseRelief(buffer([-70, -38, 100]));
  const colors = new Uint8Array([1, 2, 3, 255]);
  const layer = buildReliefLayer("relief", r, "light", colors);
  const attrs = (layer.props.data as unknown as { attributes: { getColor: { value: Uint8Array } } }).attributes;
  expect(attrs.getColor.value).toBe(colors);
  expect(r.colorCache.light).toBeUndefined();
});

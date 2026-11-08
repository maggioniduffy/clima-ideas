import { readFileSync } from "node:fs";
import { gridCells } from "./arEvents";
import { clipCells, clipRingToRect } from "./provinceClip";
import { parseRelief, pointInRing, RELIEF_STEP } from "./reliefLayer";
import { parseRing } from "./referenceLayers";

const load = (f: string) => parseRing(JSON.parse(readFileSync(`public/geo/${f}`, "utf8")))!;
const province = load("neuquen-province.geojson");
const band = load("neuquen-province-buffer-10km.geojson");

const KM_LAT = 1 / 110.574;

test("buffered outline: border point inside, 5 km outside kept, 20 km outside dropped", () => {
  // northern tip of the province, due north of a vertex on the border: lat -36.129 at lon -70.431
  const [lon, lat] = [-70.431, -36.129];
  expect(pointInRing(lon, lat, band)).toBe(true);
  expect(pointInRing(lon, lat + 5 * KM_LAT, province)).toBe(false);
  expect(pointInRing(lon, lat + 5 * KM_LAT, band)).toBe(true);
  expect(pointInRing(lon, lat + 20 * KM_LAT, band)).toBe(false);
  // far from the province
  expect(pointInRing(-60, -30, band)).toBe(false);
});

test("buffered outline contains the province and is ~10 km wider", () => {
  for (const [lon, lat] of province) expect(pointInRing(lon, lat, band)).toBe(true);
  const lats = (r: number[][]) => [Math.min(...r.map((p) => p[1]!)), Math.max(...r.map((p) => p[1]!))];
  const [s0, n0] = lats(province);
  const [s1, n1] = lats(band);
  expect((n1! - n0!) / KM_LAT).toBeGreaterThan(9);
  expect((n1! - n0!) / KM_LAT).toBeLessThan(11);
  expect((s0! - s1!) / KM_LAT).toBeGreaterThan(9);
});

test("clipRingToRect cuts a triangle and drops what is fully outside", () => {
  const tri: [number, number][] = [
    [0, 0],
    [3, 0],
    [0, 3],
  ];
  expect(clipRingToRect(tri, 5, 6, 0, 1)).toEqual([]);
  const part = clipRingToRect(tri, 0, 2, 0, 2);
  const area = part.reduce((a, p, i) => {
    const q = part[(i + 1) % part.length]!;
    return a + (p[0] * q[1] - q[0] * p[1]) / 2;
  }, 0);
  expect(Math.abs(area)).toBeCloseTo(3.5, 6); // 2x2 square minus the corner beyond x + y = 3
});

test("clipCells: edge cell is cut to the band, outside cells are removed, row/col are kept", () => {
  const nx = 6;
  const ny = 6;
  const grid = { nx, ny, lon_min: -71, lon_max: -69.75, lat_min: -36.75, lat_max: -35.5, step: 0.25 } as never;
  const cells = gridCells(grid);
  const clipped = clipCells(cells, band);
  expect(clipped.length).toBeGreaterThan(0);
  expect(clipped.length).toBeLessThan(cells.length);
  for (const c of clipped) expect(c.row * nx + c.col).toBe(cells.indexOf(cells[c.row * nx + c.col]!));
  // cells away from the border are untouched (4 vertices); at least one border cell was cut to a different shape
  expect(clipped.some((c) => c.polygon.length === 4)).toBe(true);
  expect(clipped.some((c) => c.polygon.length !== 4)).toBe(true);
  // the clipped area is smaller than the full cells it came from
  const area = (poly: [number, number][]) =>
    Math.abs(poly.reduce((a, p, i) => a + (p[0] * poly[(i + 1) % poly.length]![1] - poly[(i + 1) % poly.length]![0] * p[1]) / 2, 0));
  const full = clipped.reduce((a, c) => a + area(cells[c.row * nx + c.col]!.polygon), 0);
  expect(clipped.reduce((a, c) => a + area(c.polygon), 0)).toBeLessThan(full);
});

test("parseRelief with the band keeps a point 5 km outside the province and drops one 20 km outside", () => {
  const [lon, lat] = [-70.431, -36.129];
  const pts = [lon, lat, 100, lon, lat + 5 * KM_LAT, 100, lon, lat + 20 * KM_LAT, 100];
  const r = parseRelief(new Float32Array(pts).buffer, band, RELIEF_STEP);
  expect(r.length).toBe(2);
  const clippedToProvince = parseRelief(new Float32Array(pts).buffer, province, RELIEF_STEP);
  expect(clippedToProvince.length).toBe(1);
});

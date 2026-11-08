import { readFileSync } from "node:fs";
import { buildReferenceLayers, parseProvinceRing } from "./referenceLayers";

const province = JSON.parse(readFileSync("public/geo/neuquen-province.geojson", "utf8"));

const backendGeo = "../backend/src/clima_nqn/stages/ar/geo";

test("web geo files are identical to the backend copies", () => {
  for (const f of ["neuquen-province.geojson"])
    expect(readFileSync(`public/geo/${f}`, "utf8")).toBe(readFileSync(`${backendGeo}/${f}`, "utf8"));
});

test("the bundled province outline is a small, sourced Neuquén polygon", () => {
  expect(readFileSync("public/geo/neuquen-province.geojson").length).toBeLessThan(50_000);
  expect(province.properties.license).toMatch(/public domain/i);
  expect(province.properties.source).toMatch(/Natural Earth/);
  const ring = parseProvinceRing(province)!;
  expect(ring.length).toBeGreaterThan(100);
  const lons = ring.map((p) => p[0]);
  const lats = ring.map((p) => p[1]);
  expect(Math.min(...lons)).toBeGreaterThan(-72.5);
  expect(Math.max(...lons)).toBeLessThan(-68);
  expect(Math.min(...lats)).toBeGreaterThan(-41.5);
  expect(Math.max(...lats)).toBeLessThan(-36);
});

test("parseProvinceRing rejects unexpected shapes", () => {
  expect(parseProvinceRing(null)).toBeNull();
  expect(parseProvinceRing([{ id: "a" }])).toBeNull();
  expect(parseProvinceRing({ features: [{ geometry: { type: "Point", coordinates: [0, 0] } }] })).toBeNull();
});

test.each(["light", "dark"] as const)("buildReferenceLayers (%s): province outline once loaded, city and labels", (theme) => {
  const ring = parseProvinceRing(province)!;
  const ids = (p: typeof ring | null) => buildReferenceLayers({ theme, province: p }).map((l) => l.id);
  expect(ids(null)).toEqual(["ref-city", "ref-labels"]);
  expect(ids(ring)).toEqual(["ref-province-halo", "ref-province", "ref-city", "ref-labels"]);
});

import { readFileSync } from "node:fs";
import { buildReferenceLayers, closeRing, parseProvinceRing, parseRing } from "./referenceLayers";

const province = JSON.parse(readFileSync("public/geo/neuquen-province.geojson", "utf8"));

const cordilleraJson = JSON.parse(readFileSync("public/geo/cordillera.geojson", "utf8"));
const backendGeo = "../backend/src/clima_nqn/stages/ar/geo";

test("web geo files are identical to the backend copies", () => {
  for (const f of ["cordillera.geojson", "neuquen-province.geojson"])
    expect(readFileSync(`public/geo/${f}`, "utf8")).toBe(readFileSync(`${backendGeo}/${f}`, "utf8"));
});

test("cordillera polygon is the sourced Neuquén clip west of 70° O (lon, lat)", () => {
  expect(cordilleraJson.properties.method).toBe("provincia de Neuquén (Natural Earth 1:10m) ∩ lon ≤ -70.0");
  expect(cordilleraJson.properties.source).toMatch(/Natural Earth/);
  expect(cordilleraJson.properties.license).toMatch(/public domain/i);
  const ring = parseRing(cordilleraJson)!;
  expect(ring.length).toBeGreaterThan(100);
  expect(Math.max(...ring.map((p) => p[0]))).toBeLessThanOrEqual(-70.0 + 1e-9);
  expect(Math.min(...ring.map((p) => p[1]))).toBeGreaterThanOrEqual(-41.1);
  expect(Math.max(...ring.map((p) => p[1]))).toBeLessThanOrEqual(-36.0);
  expect(closeRing(ring)).toHaveLength(ring.length + 1);
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

test.each(["light", "dark"] as const)("buildReferenceLayers (%s): outlines, city and labels; each outline only once loaded", (theme) => {
  const ring = parseProvinceRing(province)!;
  const cord = parseRing(cordilleraJson)!;
  const ids = (p: typeof ring | null, c: typeof ring | null) =>
    buildReferenceLayers({ theme, province: p, cordillera: c }).map((l) => l.id);
  expect(ids(null, null)).toEqual(["ref-city", "ref-labels"]);
  expect(ids(null, cord)).toEqual(["ref-cordillera-halo", "ref-cordillera", "ref-city", "ref-labels"]);
  expect(ids(ring, cord)).toEqual([
    "ref-province-halo",
    "ref-province",
    "ref-cordillera-halo",
    "ref-cordillera",
    "ref-city",
    "ref-labels",
  ]);
});

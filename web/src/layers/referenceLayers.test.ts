import { readFileSync } from "node:fs";
import { CORDILLERA_POLYGON, buildReferenceLayers, closeRing, parseProvinceRing } from "./referenceLayers";

const province = JSON.parse(readFileSync("public/geo/neuquen-province.geojson", "utf8"));

test("cordillera polygon mirrors the backend catalog (lon, lat)", () => {
  const py = readFileSync("../backend/src/clima_nqn/stages/ar/catalog.py", "utf8");
  const body = /CORDILLERA_POLYGON[^=]*=\s*\[([^\]]*)\]/.exec(py)![1]!;
  const pts = [...body.matchAll(/\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)/g)].map((m) => [Number(m[1]), Number(m[2])]);
  expect(pts).toEqual(CORDILLERA_POLYGON);
  expect(closeRing(CORDILLERA_POLYGON)).toHaveLength(5);
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

test.each(["light", "dark"] as const)("buildReferenceLayers (%s): outlines, city and labels; no province until loaded", (theme) => {
  const ring = parseProvinceRing(province)!;
  const ids = (p: typeof ring | null) => buildReferenceLayers({ theme, province: p }).map((l) => l.id);
  expect(ids(null)).toEqual(["ref-cordillera-halo", "ref-cordillera", "ref-city", "ref-labels"]);
  expect(ids(ring)).toEqual([
    "ref-province-halo",
    "ref-province",
    "ref-cordillera-halo",
    "ref-cordillera",
    "ref-city",
    "ref-labels",
  ]);
});

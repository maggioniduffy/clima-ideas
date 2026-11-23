import { BASEMAP_LAYER_ID, basemapAvailable, basemapUrl, buildBasemapLayer } from "./basemapLayer";

test("tile URL uses the keyed raster endpoint, positron / dark-matter and @2x", () => {
  expect(basemapUrl("light", "k1")).toBe("https://basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}@2x.png?key=k1");
  expect(basemapUrl("dark", "a b")).toBe("https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}@2x.png?key=a%20b");
});

test("the basemap layer is a non-pickable tile layer with a stable id", () => {
  const layer = buildBasemapLayer("dark", true, "k");
  expect(layer.id).toBe(BASEMAP_LAYER_ID);
  expect(layer.props.pickable).toBe(false);
  expect(layer.props.data).toBe(basemapUrl("dark", "k"));
  expect(layer.props.visible).toBe(true);
  expect(buildBasemapLayer("light", false, "k").props.visible).toBe(false);
});

test("without a key no basemap is drawn (CARTO would only return API KEY REQUIRED tiles)", () => {
  expect(basemapAvailable("")).toBe(false);
  expect(buildBasemapLayer("light", true, "").props.visible).toBe(false);
});

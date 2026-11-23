import { BASEMAP_LAYER_ID, basemapUrls, buildBasemapLayer } from "./basemapLayer";

test("tile URL uses light_all / dark_all, @2x and subdomains a-d", () => {
  expect(basemapUrls("light")).toEqual(
    ["a", "b", "c", "d"].map((s) => `https://${s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png`),
  );
  expect(basemapUrls("dark").every((u) => u.includes("/dark_all/"))).toBe(true);
});

test("the basemap layer is a non-pickable tile layer with a stable id", () => {
  const layer = buildBasemapLayer("dark");
  expect(layer.id).toBe(BASEMAP_LAYER_ID);
  expect(layer.props.pickable).toBe(false);
  expect(layer.props.data).toEqual(basemapUrls("dark"));
  expect(buildBasemapLayer("light", false).props.visible).toBe(false);
});

import { buildFloodStationsLayer, stationRadius, STATION_RADIUS_MAX_PX, STATION_RADIUS_MIN_PX } from "./floodStations";

test("radius grows with value inside the fixed pixel range", () => {
  expect(stationRadius(0, 100)).toBe(STATION_RADIUS_MIN_PX);
  expect(stationRadius(100, 100)).toBe(STATION_RADIUS_MAX_PX);
  expect(stationRadius(500, 100)).toBe(STATION_RADIUS_MAX_PX);
  const mid = stationRadius(25, 100);
  expect(mid).toBeGreaterThan(STATION_RADIUS_MIN_PX);
  expect(mid).toBeLessThan(STATION_RADIUS_MAX_PX);
  expect(stationRadius(5, 0)).toBe(STATION_RADIUS_MIN_PX);
});

test("layer colors: accent when selected, hollow fill when regulated", () => {
  const data = [
    { id: "a", lon: -69, lat: -38, value: 100, regulated: false },
    { id: "b", lon: -69, lat: -39, value: 10, regulated: true },
  ];
  const layer = buildFloodStationsLayer(data, "a", "light", () => undefined);
  expect(layer.id).toBe("points-flood-stations");
  const fill = layer.props.getFillColor as unknown as (d: (typeof data)[0]) => number[];
  expect(fill(data[0]!)).toEqual([0xf5, 0xcf, 0x4b, 255]);
  expect(fill(data[1]!)[3]).toBeLessThan(100);
  expect(fill(data[1]!).slice(0, 3)).toEqual([0x1c, 0x1c, 0x1c]); // light --ctrl
  const radius = layer.props.getRadius as unknown as (d: (typeof data)[0]) => number;
  expect(radius(data[0]!)).toBeGreaterThan(radius(data[1]!));
});

it("draws stations without depth test so the 3D relief does not hide them", () => {
  const layer = buildFloodStationsLayer([], null, "light", () => undefined);
  expect(layer.props.parameters).toMatchObject({ depthCompare: "always" });
});

it("selected station uses the per-theme accent", () => {
  const data = [{ id: "a", lon: -69, lat: -38, value: 100, regulated: false }];
  const layer = buildFloodStationsLayer(data, "a", "dark", () => undefined);
  const fill = layer.props.getFillColor as unknown as (d: (typeof data)[0]) => number[];
  expect(fill(data[0]!)).toEqual([0xf5, 0xcf, 0x4b, 255]);
});

it("station dots use --ctrl, selected ones --accent with a --casing outline, in both themes", () => {
  const data = [
    { id: "a", lon: -69, lat: -38, value: 100, regulated: false },
    { id: "b", lon: -69, lat: -39, value: 10, regulated: false },
  ];
  const cases = [
    ["light", [0x1c, 0x1c, 0x1c, 255], [0xf5, 0xcf, 0x4b, 255], [0x1c, 0x1c, 0x1c, 255]],
    ["dark", [0xf1, 0xef, 0xe8, 255], [0xf5, 0xcf, 0x4b, 255], [0x10, 0x11, 0x14, 255]],
  ] as const;
  for (const [theme, ctrl, accent, casing] of cases) {
    const layer = buildFloodStationsLayer(data, "a", theme, () => undefined);
    const fill = layer.props.getFillColor as unknown as (d: (typeof data)[0]) => number[];
    const line = layer.props.getLineColor as unknown as (d: (typeof data)[0]) => number[];
    expect(fill(data[1]!)).toEqual(ctrl);
    expect(fill(data[0]!)).toEqual(accent);
    expect(line(data[0]!)).toEqual(casing);
  }
});

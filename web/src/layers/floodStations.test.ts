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
  expect(fill(data[0]!)).toEqual([0x8e, 0xb8, 0xe5, 255]);
  expect(fill(data[1]!)[3]).toBeLessThan(100);
  expect(fill(data[1]!).slice(0, 3)).toEqual([0x3e, 0x50, 0x5b]);
  const radius = layer.props.getRadius as unknown as (d: (typeof data)[0]) => number;
  expect(radius(data[0]!)).toBeGreaterThan(radius(data[1]!));
});

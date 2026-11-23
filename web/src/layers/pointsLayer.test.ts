import type { PointFeature } from "../api/client";
import { buildPointsLayer } from "./pointsLayer";

const pts = [
  { id: "a", lon: -69, lat: -38 },
  { id: "b", lon: -69, lat: -39 },
] as unknown as PointFeature[];
type Fn = (d: PointFeature) => number[];

test("points use --ctrl; the selected one --accent with a --casing outline, per theme", () => {
  const cases = [
    ["light", [0x1c, 0x1c, 0x1c], [0xf5, 0xcf, 0x4b], [0x1c, 0x1c, 0x1c]],
    ["dark", [0xf1, 0xef, 0xe8], [0xf5, 0xcf, 0x4b], [0x10, 0x11, 0x14]],
  ] as const;
  for (const [theme, ctrl, accent, casing] of cases) {
    const layer = buildPointsLayer("x", pts, "a", theme, () => undefined);
    const fill = layer.props.getFillColor as unknown as Fn;
    const line = layer.props.getLineColor as unknown as Fn;
    expect(fill(pts[1]!)).toEqual(ctrl);
    expect(fill(pts[0]!)).toEqual(accent);
    expect(line(pts[0]!)).toEqual(casing);
  }
});

test("points layer keeps its id, pickability and rebuilds on theme change", () => {
  const layer = buildPointsLayer("x", pts, null, "light", () => undefined);
  expect(layer.id).toBe("points-x");
  expect(layer.props.pickable).toBe(true);
  expect(layer.props.updateTriggers).toMatchObject({ getFillColor: [null, "light"] });
});

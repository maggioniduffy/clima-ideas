import { buildIvtRasterLayer } from "./ivtRasterLayer";

const cells = [{ row: 0, col: 0, polygon: [] }, { row: 0, col: 1, polygon: [] }] as never;
const base = { layerId: "x", cells, frames: new Float32Array(2), grid: {} as never, frame: 0, onHover: () => undefined, onPick: () => undefined };

test("picked cell outline is --accent per theme; others stay transparent", () => {
  for (const [theme, rgb] of [["light", [0x8e, 0xb8, 0xe5]], ["dark", [0xfd, 0xda, 0x0d]]] as const) {
    const layer = buildIvtRasterLayer({ ...base, theme, picked: { row: 0, col: 0 } } as never);
    const line = layer.props.getLineColor as unknown as (c: { row: number; col: number }) => number[];
    expect(line({ row: 0, col: 0 })).toEqual([...rgb, 255]);
    expect(line({ row: 0, col: 1 })).toEqual([0, 0, 0, 0]);
  }
});

test("count layer draws only the cells that were reached, colored by their count", async () => {
  const { buildCountLayer, buildPeakLayer } = await import("./ivtRasterLayer");
  const { countColor } = await import("./arEvents");
  const grid = { ny: 1, nx: 3 } as never;
  const cs = [0, 1, 2].map((col) => ({ row: 0, col, polygon: [] })) as never;
  const layer = buildCountLayer({ layerId: "x", grid, cells: cs, counts: Uint16Array.from([0, 3, 1]), max: 3, theme: "dark" });
  expect(layer.id).toBe("ar-count-x");
  const data = layer.props.data as { col: number }[];
  expect(data.map((c) => c.col)).toEqual([1, 2]);
  const fill = layer.props.getFillColor as unknown as (c: { row: number; col: number }) => number[];
  expect(fill({ row: 0, col: 1 })).toEqual(countColor(3, 3, "dark"));
  expect(layer.props.pickable).toBe(false);
  const peak = buildPeakLayer({ layerId: "x", lon: -70, lat: -39, theme: "light" });
  expect(peak.id).toBe("ar-peak-x");
  expect(peak.props.data).toEqual([{ position: [-70, -39] }]);
});

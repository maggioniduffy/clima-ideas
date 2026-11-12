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

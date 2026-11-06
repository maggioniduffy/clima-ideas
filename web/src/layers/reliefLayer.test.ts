import { PointCloudLayer } from "@deck.gl/layers";
import { buildReliefLayer, parseRelief, RELIEF_EXAGGERATION, reliefColor } from "./reliefLayer";
import { tokens } from "../theme/tokens";

const buffer = (vals: number[]) => new Float32Array(vals).buffer;

test("parseRelief reads interleaved lon/lat/elev and exaggerates z", () => {
  const r = parseRelief(buffer([-70, -38, 100, -69, -37, 4000]));
  expect(r.length).toBe(2);
  expect(Array.from(r.positions)).toEqual([-70, -38, 100 * RELIEF_EXAGGERATION, -69, -37, 4000 * RELIEF_EXAGGERATION]);
  expect(r.colors.length).toBe(2 * 4);
});

test("parseRelief colors span the ramp from the lowest to the highest elevation", () => {
  const r = parseRelief(buffer([-70, -38, 100, -69, -37, 4000]));
  expect(Array.from(r.colors.slice(0, 4))).toEqual([...reliefColor(0), 255]);
  expect(Array.from(r.colors.slice(4, 8))).toEqual([...reliefColor(1), 255]);
  expect(reliefColor(0)).toEqual([0xa4, 0xaf, 0x69]);
  expect(reliefColor(1)).toEqual([0x8e, 0xb8, 0xe5]);
  expect(reliefColor(1)).not.toEqual([255, 255, 255]);
});

test("parseRelief rejects a buffer that is not a multiple of the stride", () => {
  expect(() => parseRelief(new ArrayBuffer(10))).toThrow();
});

test("buildReliefLayer returns a PointCloudLayer with binary attributes", () => {
  const layer = buildReliefLayer("relief", parseRelief(buffer([-70, -38, 100])));
  expect(layer).toBeInstanceOf(PointCloudLayer);
  expect(layer.id).toBe("relief-relief");
  expect(tokens.brand.secondary).toBe("#A4AF69");
});

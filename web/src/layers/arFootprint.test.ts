import { AR_IVT_THRESHOLD, coreLevel, countReaching, footprintOf, parseFootprints } from "./arFootprint";

const meta = { file: "frames/footprints.bin", events: ["A", "B", "C"], shape: [3, 1, 3] as [number, number, number] };
// A: 100 300 600; B: 250 200 NaN; C: 900 250 249
const values = new Float32Array([100, 300, 600, 250, 200, NaN, 900, 250, 249]);

test("parseFootprints decodes the buffer and rejects a size that does not match the shape", () => {
  const fp = parseFootprints(values.buffer, meta);
  expect(fp.order).toEqual(["A", "B", "C"]);
  expect(fp.ny).toBe(1);
  expect(fp.nx).toBe(3);
  expect(() => parseFootprints(new ArrayBuffer(8), meta)).toThrow(/footprints/);
});

test("footprintOf slices one event by its position in the index order", () => {
  const fp = parseFootprints(values.buffer, meta);
  expect([...footprintOf(fp, "B")!.slice(0, 2)]).toEqual([250, 200]);
  expect(footprintOf(fp, "C")!).toHaveLength(3);
  expect(footprintOf(fp, "Z")).toBeNull();
});

test("countReaching counts, per cell, the chosen events whose footprint is at least the threshold", () => {
  const fp = parseFootprints(values.buffer, meta);
  expect(AR_IVT_THRESHOLD).toBe(250);
  expect([...countReaching(fp, ["A", "B", "C"], 250)]).toEqual([2, 2, 1]); // >= : 250 counts, 249 and NaN do not
  expect([...countReaching(fp, ["A"], 250)]).toEqual([0, 1, 1]);
  expect([...countReaching(fp, ["A", "B", "C"])]).toEqual([2, 2, 1]); // default threshold
  expect([...countReaching(fp, [], 250)]).toEqual([0, 0, 0]);
  expect([...countReaching(fp, ["A", "nope"], 250)]).toEqual([0, 1, 1]); // unknown ids are skipped
});

test("coreLevel is the highest existing isoline level the footprint reaches", () => {
  expect(coreLevel(new Float32Array([100, 249]))).toBeNull();
  expect(coreLevel(new Float32Array([100, 250]))).toBe(250);
  expect(coreLevel(new Float32Array([NaN, 520, 100]))).toBe(500);
  expect(coreLevel(new Float32Array([750, NaN]))).toBe(750);
  expect(coreLevel(new Float32Array([5000]))).toBe(1000);
});

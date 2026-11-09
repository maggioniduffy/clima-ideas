import { IVT_CONTOUR_LEVELS, buildIvtContourLayers, contourPaths } from "./ivtContours";
import { ivtColor } from "./arEvents";

// 21 x 21 grid, 0.5 degree spacing, centered on (-70, -38): value = 1000 - 100 * radius in grid cells (a radial bump)
const N = 21;
const grid = {
  ny: N,
  nx: N,
  lat_min: -43,
  lat_max: -33,
  lon_min: -75,
  lon_max: -65,
};
const bump = new Float32Array(N * N);
for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) bump[r * N + c] = 1000 - 100 * Math.hypot(r - 10, c - 10);
const D = 0.5;

test("a radial bump yields a closed ring at the expected radius, mapped to lon/lat (row 0 = south)", () => {
  const paths = contourPaths(bump, grid, 0, 250); // radius where value = 250 is 7.5 cells
  expect(paths).toHaveLength(1);
  const ring = paths[0]!;
  expect(ring[0]).toEqual(ring[ring.length - 1]); // closed
  for (const [lon, lat] of ring) {
    const radiusCells = Math.hypot((lon - -70) / D, (lat - -38) / D);
    expect(Math.abs(radiusCells - 7.5)).toBeLessThan(0.5);
  }
  const lons = ring.map((p) => p[0]);
  const lats = ring.map((p) => p[1]);
  expect(Math.min(...lons)).toBeCloseTo(-70 - 7.5 * D, 0);
  expect(Math.max(...lats)).toBeCloseTo(-38 + 7.5 * D, 0);
});

test("levels above the maximum produce no paths; each frame offset is read", () => {
  expect(contourPaths(bump, grid, 0, 1001)).toEqual([]);
  const two = new Float32Array([...new Float32Array(N * N), ...bump]);
  expect(contourPaths(two, grid, 0, 250)).toEqual([]);
  expect(contourPaths(two, grid, 1, 250)).toHaveLength(1);
});

test("NaN cells are treated as below every level", () => {
  const holes = Float32Array.from(bump);
  holes[10 * N + 10] = NaN;
  expect(() => contourPaths(holes, grid, 0, 750)).not.toThrow();
  for (const p of contourPaths(holes, grid, 0, 750)) for (const pt of p) expect(pt.every(Number.isFinite)).toBe(true);
});

test("contour layers: halo + line, ids start with ivt-contours-, colored by the IVT ramp per level", () => {
  const layers = buildIvtContourLayers({
    layerId: "ar",
    grid,
    frames: bump,
    frame: 0,
    eventId: "e",
    theme: "light",
  });
  expect(layers.map((l) => l.id)).toEqual(["ivt-contours-halo-ar", "ivt-contours-ar"]);
  const data = layers[1]!.props.data as { level: number; path: unknown[] }[];
  expect(data.map((d) => d.level)).toEqual([250, 500, 750]); // 1000 is never reached by the bump (max 1000 at 1 node)
  expect(IVT_CONTOUR_LEVELS).toEqual([250, 500, 750, 1000]);
  const getColor = layers[1]!.props.getColor as unknown as (d: { level: number }) => number[];
  expect(getColor({ level: 500 })).toEqual(ivtColor(500, "light"));
});

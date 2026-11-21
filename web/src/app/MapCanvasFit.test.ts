import type { MapViewState } from "@deck.gl/core";
import { fitView, FIT_MAX_ZOOM, resolveFocus } from "./MapCanvasFit";

const size = { width: 800, height: 600 };
const view: MapViewState = { longitude: -69.5, latitude: -38.5, zoom: 6, pitch: 40, bearing: 0 };

test("fitView centres the box, keeps pitch and bearing", () => {
  const v = fitView(view, [-70, -39, -69, -38], size)!;
  expect(v.longitude).toBeCloseTo(-69.5, 3);
  expect(v.latitude).toBeCloseTo(-38.5, 1);
  expect(v.pitch).toBe(40);
  expect(v.zoom).toBeGreaterThan(5);
});

test("fitView caps the zoom for tiny boxes and rejects empty sizes or bad bounds", () => {
  expect(fitView(view, [-69.5, -38.5, -69.4999, -38.4999], size)!.zoom).toBe(FIT_MAX_ZOOM);
  expect(fitView(view, [-70, -39, -69, -38], { width: 0, height: 0 })).toBeNull();
  expect(fitView(view, [NaN, 0, 1, 1], size)).toBeNull();
});

test("a tiny viewport does not break padding", () => {
  expect(fitView(view, [-70, -39, -69, -38], { width: 60, height: 60 })).not.toBeNull();
});

test("ifNeeded: moves when the box is far outside or much smaller than the view, stays when comfortably in view", () => {
  const box: [number, number, number, number] = [-69.52, -38.52, -69.48, -38.48];
  expect(resolveFocus(view, { bounds: box }, size)).not.toBeNull(); // list selection always moves
  expect(resolveFocus(view, { bounds: box, ifNeeded: true }, size)).not.toBeNull(); // regional zoom: too small
  const fitted = fitView(view, box, size)!;
  expect(resolveFocus(fitted, { bounds: box, ifNeeded: true }, size)).toBeNull(); // already framed
  expect(resolveFocus({ ...fitted, zoom: fitted.zoom - 1 }, { bounds: box, ifNeeded: true }, size)).toBeNull(); // nearby
  expect(resolveFocus({ ...fitted, longitude: fitted.longitude + 5 }, { bounds: box, ifNeeded: true }, size)).not.toBeNull();
});

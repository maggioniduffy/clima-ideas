import { WebMercatorViewport, type MapViewState } from "@deck.gl/core";
import { clampView, coverZoom, COVER_BOX, MAX_ZOOM } from "./mapCamera";

const view: MapViewState = { longitude: -69.5, latitude: -38.5, zoom: 6, pitch: 0, bearing: 0 };

/** Box edges projected in a card of `size` must all lie outside (or on) the card. */
function boxCoversCard(v: MapViewState, size: { width: number; height: number }) {
  const vp = new WebMercatorViewport({ ...v, pitch: 0, bearing: 0, ...size });
  const [w, s, e, n] = COVER_BOX;
  const [x0, y1] = vp.project([w, s]);
  const [x1, y0] = vp.project([e, n]);
  const tol = 0.5;
  return x0! <= tol && y0! <= tol && x1! >= size.width - tol && y1! >= size.height - tol;
}

test("coverZoom: the box covers the card on both axes and grows with the card", () => {
  const small = coverZoom({ width: 400, height: 300 });
  const big = coverZoom({ width: 1200, height: 800 });
  expect(big).toBeGreaterThan(small);
  const v = { ...view, zoom: small, longitude: -70, latitude: -38.5 };
  expect(boxCoversCard(v, { width: 400, height: 300 })).toBe(true);
  // a bit lower no longer covers
  expect(boxCoversCard({ ...v, zoom: small - 0.05 }, { width: 400, height: 300 })).toBe(false);
});

test("clampView raises the zoom to the cover zoom and caps it at 12", () => {
  const size = { width: 800, height: 600 };
  expect(clampView({ ...view, zoom: 1 }, size).zoom).toBeCloseTo(coverZoom(size), 6);
  expect(clampView({ ...view, zoom: 16 }, size).zoom).toBe(MAX_ZOOM);
  expect(MAX_ZOOM).toBe(12);
});

test("clampView keeps every box edge outside the card at any zoom and center", () => {
  const sizes = [
    { width: 800, height: 600 },
    { width: 390, height: 400 },
    { width: 1400, height: 500 },
  ];
  for (const size of sizes)
    for (const zoom of [0, 5, 6.5, 9, 12])
      for (const [longitude, latitude] of [[-80, -30], [-60, -50], [-74, -43], [-66, -34], [-70, -38.5]] as const) {
        const out = clampView({ ...view, zoom, longitude, latitude }, size);
        expect(boxCoversCard(out, size)).toBe(true);
      }
});

test("clampView leaves a valid view alone and keeps pitch and bearing", () => {
  const size = { width: 800, height: 600 };
  const v = { ...view, zoom: 8, pitch: 40, bearing: 15 };
  const out = clampView(v, size);
  expect(out).toEqual(v);
});

test("clampView passes the view through while the card has no size or the view is not finite", () => {
  expect(clampView(view, { width: 0, height: 0 })).toBe(view);
  const bad = { ...view, zoom: NaN };
  expect(clampView(bad, { width: 800, height: 600 })).toBe(bad);
});

test("clampView preserves transition props", () => {
  const out = clampView({ ...view, zoom: 1, transitionDuration: 800 } as MapViewState, { width: 800, height: 600 });
  expect((out as { transitionDuration?: number }).transitionDuration).toBe(800);
});

import type { Layer } from "@deck.gl/core";
import { PathLayer } from "@deck.gl/layers";
import type { FrameGrid } from "../api/client";
import { es } from "../i18n/es";
import type { Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";
import type { ReplayData } from "./convectionIdf";
import type { MapMarker } from "../app/MapCanvas";

type LonLat = [number, number];

/** Grid step in degrees (IMERG is 0.1°): taken from the frames grid so it is never hard-coded. */
export const gridStepDeg = (g: FrameGrid): number => (g.lat_max - g.lat_min) / Math.max(g.ny - 1, 1);

/** Closed outline of the IMERG cell centred on `cell`, `step` degrees wide. */
export function cellRing(cell: { lat: number; lon: number }, step: number): LonLat[] {
  const h = step / 2;
  const [w, e, s, n] = [cell.lon - h, cell.lon + h, cell.lat - h, cell.lat + h];
  return [
    [w, s],
    [e, s],
    [e, n],
    [w, n],
    [w, s],
  ];
}

const hex = (h: string, alpha = 255): [number, number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
  alpha,
];

/** Outline of the IMERG cell used for the station comparison: a theme-colored line over a background-colored halo. */
export function buildCellLayers(replay: ReplayData, step: number, theme: Theme): Layer[] {
  const t = tokens[theme];
  const ring = cellRing(replay.cell, step);
  const path = (id: string, color: [number, number, number, number], width: number) =>
    new PathLayer<LonLat[]>({
      id,
      data: [ring],
      getPath: (d) => d,
      getColor: color,
      getWidth: width,
      widthUnits: "pixels",
      jointRounded: true,
      parameters: { depthCompare: "always" },
      updateTriggers: { getColor: [theme] },
    });
  return [path("convection-cell-halo", hex(t.bg, 220), 5), path("convection-cell", hex(t.text, 255), 2)];
}

const coord = (v: number) => v.toFixed(3).replace(".", ",");

/** Map markers (HTML, so they are labelled and hoverable): the station and the IMERG cell, with their source in the tooltip. */
export function convectionMarkers(replay: ReplayData, step: number): MapMarker[] {
  const st = replay.compare.station;
  return [
    {
      id: "convection-station",
      kind: "station",
      lon: st.lon,
      lat: st.lat,
      label: es.convection.markerStation(st.name),
      tooltip: es.convection.markerStationTip(st.name, st.source, coord(st.lat), coord(st.lon)),
      placement: "up",
    },
    {
      id: "convection-cell",
      kind: "cell",
      lon: replay.cell.lon,
      lat: replay.cell.lat,
      label: es.convection.markerCell,
      tooltip: es.convection.markerCellTip(
        replay.source,
        step.toFixed(1).replace(".", ","),
        coord(replay.cell.lat),
        coord(replay.cell.lon),
      ),
      placement: "down",
    },
  ];
}

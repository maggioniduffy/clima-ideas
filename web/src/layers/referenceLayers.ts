import { useEffect, useMemo, useState } from "react";
import type { Layer } from "@deck.gl/core";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { es } from "../i18n/es";
import { useTheme, type Theme } from "../theme/themeStore";
import { tokens } from "../theme/tokens";

export type LonLat = [number, number];

/**
 * Cordillera polygon used by the AR catalog to pick event cells (lon, lat).
 * Mirrors `CORDILLERA_POLYGON` in backend/src/clima_nqn/stages/ar/catalog.py (referenceLayers.test.ts checks it);
 * an approximation of the Neuquén cordillera, sin verificar.
 */
export const CORDILLERA_POLYGON: LonLat[] = [
  [-71.95, -36.0],
  [-70.0, -36.0],
  [-70.0, -41.1],
  [-71.95, -41.1],
];

/** Neuquén capital (city marker). */
export const NEUQUEN_CITY = { lon: -68.06, lat: -38.95 };

/** Province outline: Natural Earth 1:10m admin-1 (public domain), see public/geo/README.md. */
export const PROVINCE_URL = "/geo/neuquen-province.geojson";
export const PROVINCE_SOURCE = "Natural Earth";

export const closeRing = (ring: LonLat[]): LonLat[] => [...ring, ring[0]!];

/** Outer ring of the first polygon feature of a GeoJSON FeatureCollection; null when the shape is unexpected. */
export function parseProvinceRing(json: unknown): LonLat[] | null {
  const geometry = (json as { features?: { geometry?: { type?: string; coordinates?: unknown } }[] } | null)?.features?.[0]
    ?.geometry;
  if (geometry?.type !== "Polygon" || !Array.isArray(geometry.coordinates)) return null;
  const ring = geometry.coordinates[0] as unknown;
  if (!Array.isArray(ring) || ring.length < 4) return null;
  return ring.every((p) => Array.isArray(p) && typeof p[0] === "number" && typeof p[1] === "number")
    ? (ring as LonLat[])
    : null;
}

const hex = (h: string, alpha = 255): [number, number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
  alpha,
];

// Drawn on top of the raster without depth test (all layers are flat at z = 0).
const FLAT = { depthCompare: "always" } as const;

interface Props {
  theme: Theme;
  /** Province outer ring, once loaded (the other references do not depend on it). */
  province: LonLat[] | null;
}

/**
 * Thin geographic references over the IVT raster, theme-colored: province outline, cordillera polygon and Neuquén
 * city marker with labels. A bg-colored halo under each line keeps it readable over any ramp color.
 */
export function buildReferenceLayers({ theme, province }: Props): Layer[] {
  const t = tokens[theme];
  const halo = hex(t.bg, 200);
  const line = hex(t.text, 235);
  const ref = hex(t.text, 200);
  const path = (id: string, ring: LonLat[], color: [number, number, number, number], width: number) =>
    new PathLayer<LonLat[]>({
      id,
      data: [ring],
      getPath: (d) => d,
      getColor: color,
      getWidth: width,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      parameters: FLAT,
      updateTriggers: { getColor: [theme] },
    });
  const cordillera = closeRing(CORDILLERA_POLYGON);
  const labels = [
    { text: es.map.cordillera, position: [CORDILLERA_POLYGON[0]![0], CORDILLERA_POLYGON[0]![1]], anchor: "start" as const, size: 11 },
    { text: es.map.city, position: [NEUQUEN_CITY.lon, NEUQUEN_CITY.lat], anchor: "start" as const, size: 12 },
  ];
  return [
    ...(province
      ? [path("ref-province-halo", province, halo, 4), path("ref-province", province, line, 1.75)]
      : []),
    path("ref-cordillera-halo", cordillera, halo, 3),
    path("ref-cordillera", cordillera, ref, 1.25),
    new ScatterplotLayer<{ lon: number; lat: number }>({
      id: "ref-city",
      data: [NEUQUEN_CITY],
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: line,
      getLineColor: halo,
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: 2,
      radiusUnits: "pixels",
      getRadius: 4,
      parameters: FLAT,
      updateTriggers: { getFillColor: [theme], getLineColor: [theme] },
    }),
    new TextLayer<(typeof labels)[number]>({
      id: "ref-labels",
      data: labels,
      getPosition: (d) => d.position as LonLat,
      getText: (d) => d.text,
      getSize: (d) => d.size,
      getColor: line,
      getTextAnchor: (d) => d.anchor,
      getAlignmentBaseline: "bottom",
      getPixelOffset: [6, -4],
      fontFamily: "ui-monospace, Menlo, Consolas, monospace",
      characterSet: "auto",
      background: true,
      backgroundPadding: [3, 1],
      getBackgroundColor: halo,
      parameters: FLAT,
      updateTriggers: { getColor: [theme], getBackgroundColor: [theme] },
    }),
  ];
}

/** Reference layers while `active`; the province outline loads once and is skipped if it cannot be fetched. */
export function useReferenceLayers(active: boolean): Layer[] {
  const theme = useTheme();
  const [province, setProvince] = useState<LonLat[] | null>(null);
  useEffect(() => {
    if (!active || province) return;
    let cancelled = false;
    fetch(PROVINCE_URL)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => !cancelled && setProvince(parseProvinceRing(j)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [active, province]);
  return useMemo(() => (active ? buildReferenceLayers({ theme, province }) : []), [active, theme, province]);
}

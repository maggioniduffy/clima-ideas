import type { ArEvent } from "../api/client";
import { es } from "../i18n/es";
import { formatUtc, parseTime } from "../layers/arEvents";

const num = (v: number | null, digits = 0) => (v == null ? es.events.noData : v.toFixed(digits));
const withUnit = (v: number | null, unit: string, digits = 0) => (v == null ? es.events.noData : `${num(v, digits)} ${unit}`);

export const formatDate = (iso: string) => iso.slice(0, 10);

export const formatPhase = (phase: string | null) =>
  phase == null ? es.events.noData : (es.events.phase as Record<string, string>)[phase] ?? phase;

/** "38,5 °S 70,5 °O" (hemisferio sur y oeste, valores negativos en el dato). */
export const formatLatLon = (lat: number | null, lon: number | null) =>
  lat == null || lon == null
    ? es.events.noData
    : `${Math.abs(lat).toFixed(2)} °${es.events.south}, ${Math.abs(lon).toFixed(2)} °${es.events.west}`;

export interface EventFields {
  start: string;
  end: string;
  duration: string;
  ivtMax: string;
  ivtMaxAt: string;
  deg0lMax: string;
  deg0lMean: string;
  rain: string;
  enso: string;
}

/** Display strings for the inspector; missing values read "sin dato". */
export function eventFields(e: ArEvent): EventFields {
  return {
    start: formatUtc(parseTime(e.start)),
    end: formatUtc(parseTime(e.end)),
    duration: `${num(e.duration_h)} ${es.events.units.hour}`,
    ivtMax: withUnit(e.ivt_max, es.events.units.ivt),
    ivtMaxAt:
      e.ivt_max_time == null ? es.events.noData : `${formatUtc(parseTime(e.ivt_max_time))}, ${formatLatLon(e.ivt_max_lat, e.ivt_max_lon)}`,
    deg0lMax: withUnit(e.deg0l_max, es.events.units.meters),
    deg0lMean: withUnit(e.deg0l_mean, es.events.units.meters),
    rain: withUnit(e.tp_sum_mm, es.events.units.mm, 1),
    enso: formatPhase(e.enso_phase),
  };
}

export const ivtText = (v: number | null) => withUnit(v, es.events.units.ivt);

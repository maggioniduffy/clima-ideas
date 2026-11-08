import type { ArEvent } from "../api/client";
import { es } from "../i18n/es";
import { eventFields, formatLatLon, formatPhase } from "./eventFormat";

const base: ArEvent = {
  event_id: "AR-2000-001",
  start: "2000-03-10T06:00:00Z",
  end: "2000-03-10T12:00:00Z",
  duration_h: 6,
  n_steps: 1,
  prob_max: 0.8,
  area_frac_max: 0.5,
  ivt_max: 612.4,
  ivt_max_time: "2000-03-10T09:00:00Z",
  ivt_max_lat: -38.5,
  ivt_max_lon: -70.5,
  deg0l_max: 3120.2,
  deg0l_mean: 2890.7,
  tp_sum_mm: 41.26,
  enso_phase: "nina",
};

test("eventFields formats every inspector field", () => {
  expect(eventFields(base)).toEqual({
    start: "2000-03-10 06:00 UTC",
    end: "2000-03-10 12:00 UTC",
    duration: "6 h",
    ivtMax: "612 kg m-1 s-1",
    ivtMaxAt: "2000-03-10 09:00 UTC, 38.50 °S, 70.50 °O",
    deg0lMax: "3120 m",
    deg0lMean: "2891 m",
    rain: "41.3 mm",
    enso: "La Niña",
  });
});

test("missing values read sin dato, never invented", () => {
  const f = eventFields({
    ...base,
    ivt_max: null,
    ivt_max_time: null,
    deg0l_max: null,
    deg0l_mean: null,
    tp_sum_mm: null,
    enso_phase: null,
  });
  for (const v of [f.ivtMax, f.ivtMaxAt, f.deg0lMax, f.deg0lMean, f.rain, f.enso]) expect(v).toBe(es.events.noData);
});

test("phase and coordinates helpers", () => {
  expect(formatPhase("nino")).toBe("El Niño");
  expect(formatPhase("otra")).toBe("otra");
  expect(formatLatLon(null, -70)).toBe(es.events.noData);
});

import { es } from "../i18n/es";
import { NO_DATA } from "../layers/hindcast";

const finite = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);

/** Probability as a percentage with a thin decimal rule (`0,5 %`, `37 %`). */
export const pct = (v: number | null | undefined): string => {
  if (!finite(v)) return NO_DATA;
  const x = v * 100;
  return `${x.toLocaleString("es-AR", { minimumFractionDigits: x < 10 ? 1 : 0, maximumFractionDigits: x < 10 ? 1 : 0 })} %`;
};
export const interval = (lo: number | null | undefined, hi: number | null | undefined, f: (v: number | null) => string) =>
  lo == null || hi == null ? NO_DATA : es.forecast.range(f(lo), f(hi));
export const fmt2s = (v: number | null | undefined) =>
  !finite(v) ? NO_DATA : v.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** Physical value: no trailing zeros, fewer decimals for larger numbers. */
export const phys = (v: number | null | undefined): string =>
  !finite(v) ? NO_DATA : v.toLocaleString("es-AR", { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2 });
/** `value [lo a hi]`. */
export const withCi = (v: number | null | undefined, ci: readonly (number | null)[] | null | undefined, f: (v: number | null) => string = fmt2s) =>
  `${f(v ?? null)} [${interval(ci?.[0], ci?.[1], f)}]`;

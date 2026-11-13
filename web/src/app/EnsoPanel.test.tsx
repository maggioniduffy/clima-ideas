import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import type { EnsoExtremes, EnsoRow, EnsoSeasonYear, EnsoStats } from "../api/client";
import { es } from "../i18n/es";
import { EnsoPanel } from "./EnsoPanel";

const grp = (n: number, mean: number | null, sd: number | null) => ({ n, mean, sd });
const row = (season: string, metric: EnsoRow["metric"], over: Partial<EnsoRow> = {}): EnsoRow => ({
  season,
  metric,
  phase_years: { nino: 14, neutral: 18, nina: 14 },
  groups: { nino: grp(14, 527, 80), neutral: grp(18, 500, 70), nina: grp(14, 435, 60) },
  diff_nino_nina: 92,
  p: 0.0312,
  p_bh: 0.3,
  p_3group: 0.2,
  p_3group_bh: 0.4,
  f_3group: 1.1,
  sustained: true,
  sustained_bh: false,
  ...over,
});

const sy = (season: string, year: number, phase: string, over: Partial<EnsoSeasonYear> = {}): EnsoSeasonYear => ({
  season, year, n_events: 1, ar_days: 2, ivt_mean: 500, ivt_max: 600, ar_precip_mm: 5, total_precip_mm: 100,
  ar_share: 0.05, oni_mean: 0, phase, ...over,
}); // fmt: skip

const seasonYears: EnsoSeasonYear[] = [
  sy("DJF", 1982, "nino", { ar_days: 3 }),
  sy("DJF", 1983, "nino", { ar_days: 1, ivt_mean: null }),
  sy("DJF", 1990, "neutral", { ar_days: 0 }),
  sy("DJF", 1999, "nina", { ar_days: 2 }),
  sy("DJF", 2000, "nina", { ar_days: 4 }),
  sy("SON", 1982, "nino", { ar_days: 1 }),
  sy("SON", 1999, "nina", { ar_days: 2 }),
];

const stats = (rows: EnsoRow[], withYears = true): EnsoStats => ({
  meta: { period: "1980-01-01/2025-12-30", season_years_period: "1980-2025", source: "ERA5 + ONI" },
  results: { rows, n_perm: 10000, seed: 0, alpha: 0.05 },
  ...(withYears ? { season_years: seasonYears } : {}),
});

const rows = [
  row("DJF", "ivt_mean"),
  row("DJF", "ar_share", {
    groups: { nino: grp(15, 0.022, 0.028), neutral: grp(14, null, null), nina: grp(16, 0.05, 0.075) },
    diff_nino_nina: -0.028,
    p: null,
    p_bh: null,
  }),
  row("SON", "ivt_mean", { phase_years: { nino: 14, neutral: 18, nina: 14 } }),
];
const rows16 = (over: Partial<EnsoRow> = {}) =>
  ["DJF", "MAM", "JJA", "SON"].flatMap((season) =>
    (["n_events", "ar_days", "ivt_mean", "ar_share"] as const).map((metric) =>
      row(season, metric, { phase_years: { nino: 9, neutral: 18, nina: 16 }, ...over }),
    ),
  );
const props = { source: "Fuente de la capa", period: "2000/2000", onClose: vi.fn() };

test("renders the first season table with scaled values, decimal commas and no-data cells", () => {
  render(<EnsoPanel {...props} status="ready" stats={stats(rows)} />);
  expect(screen.getByTestId("enso-tab-DJF")).toHaveAttribute("aria-selected", "true");
  const ivt = screen.getByTestId("enso-row-ivt_mean");
  expect(ivt).toHaveTextContent("527 ± 80 (n=14)");
  expect(ivt).toHaveTextContent("0,0312");
  expect(ivt).toHaveTextContent("0,3000");
  expect(ivt).toHaveTextContent(es.enso.no);
  const share = screen.getByTestId("enso-row-ar_share");
  expect(share).toHaveTextContent("2,2 ± 2,8 (n=15)"); // fraction x 100
  expect(share).toHaveTextContent(`${es.events.noData} (n=14)`);
  expect(share).toHaveTextContent("-2,8");
  expect(share).toHaveTextContent(es.events.noData); // p = null
  expect(screen.getByTestId("enso-years")).toHaveTextContent("El Niño 14 · Neutro 18 · La Niña 14");
});

test("tabs switch the season", () => {
  render(<EnsoPanel {...props} status="ready" stats={stats(rows)} />);
  expect(screen.queryByTestId("enso-row-ar_share")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("enso-tab-SON"));
  expect(screen.getByTestId("enso-tab-SON")).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByTestId("enso-row-ar_share")).toBeNull();
  expect(screen.getByTestId("enso-row-ivt_mean")).toBeInTheDocument();
});

test("footer states source, period, permutations and the caveats derived from the data", () => {
  const { rerender } = render(<EnsoPanel {...props} status="ready" stats={stats(rows)} />);
  expect(screen.getByTestId("enso-source")).toHaveTextContent("Fuente: ERA5 + ONI. Período: 1980–2025.");
  expect(screen.getByText(/10\.000 permutaciones/)).toBeInTheDocument();
  const caveats = screen.getByTestId("enso-caveats");
  expect(caveats).toHaveTextContent(es.enso.caveatFew);
  expect(caveats).toHaveTextContent(es.enso.caveatNone);
  expect(caveats).toHaveTextContent(es.enso.caveatPolygon);
  rerender(<EnsoPanel {...props} status="ready" stats={stats([row("DJF", "ivt_mean", { sustained_bh: true })])} />);
  expect(screen.getByTestId("enso-caveats")).toHaveTextContent(es.enso.caveatSome(1));
  expect(screen.getByTestId("enso-caveats")).not.toHaveTextContent(es.enso.caveatNone);
});

test("falls back to the layer source and period when the report has none", () => {
  const s = stats(rows);
  s.meta = {};
  render(<EnsoPanel {...props} status="ready" stats={s} />);
  expect(screen.getByTestId("enso-source")).toHaveTextContent("Fuente: Fuente de la capa. Período: 2000/2000.");
});

test("loading and error states; Esc and the close button call onClose", () => {
  const onClose = vi.fn();
  const { rerender } = render(<EnsoPanel {...props} onClose={onClose} status="loading" stats={null} />);
  expect(screen.getByText(es.enso.loading)).toBeInTheDocument();
  rerender(<EnsoPanel {...props} onClose={onClose} status="error" stats={null} />);
  expect(screen.getByText(es.enso.error)).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByTestId("enso-close"));
  expect(onClose).toHaveBeenCalledTimes(2);
});

const verdictNone =
  "No se detecta diferencia entre años Niño y Niña (16 comparaciones, 1980–2025, entre 9 y 16 años por fase). Con tan pocos años, no detectar no prueba que no exista.";

test("title and verdict for no sustained difference, computed from the data", () => {
  render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} />);
  expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("¿Cambia ENSO los ríos atmosféricos en Neuquén?");
  expect(screen.getByTestId("enso-verdict").textContent).toBe(verdictNone);
});

test("verdict when some comparisons are sustained", () => {
  const r = rows16();
  r[0] = { ...r[0], sustained_bh: true };
  r[5] = { ...r[5], sustained_bh: true };
  render(<EnsoPanel {...props} status="ready" stats={stats(r)} />);
  expect(screen.getByTestId("enso-verdict").textContent).toBe(
    "Se detecta diferencia entre años Niño y Niña en 2 de 16 comparaciones (1980–2025, entre 9 y 16 años por fase). Con tan pocos años, no detectar no prueba que no exista.",
  );
});

test("the chart has one dot per non-null season-year of the selected season; metric and season switch the dots", () => {
  render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} />);
  const chart = screen.getByTestId("enso-chart");
  expect(within(chart).getAllByTestId("enso-dot")).toHaveLength(5); // DJF, ar_days by default
  expect(screen.getByTestId("enso-metric-ar_days")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByTestId("enso-metric-ivt_mean"));
  expect(screen.getByTestId("enso-metric-ivt_mean")).toHaveAttribute("aria-pressed", "true");
  expect(within(chart).getAllByTestId("enso-dot")).toHaveLength(4); // one null skipped
  fireEvent.click(screen.getByTestId("enso-tab-SON"));
  expect(within(chart).getAllByTestId("enso-dot")).toHaveLength(2);
});

test("dots name their year and value; ar_share is shown in percent", () => {
  render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} />);
  expect(screen.getAllByTestId("enso-dot")[0]).toHaveAttribute("aria-label", "1982: 3,0");
  fireEvent.click(screen.getByTestId("enso-metric-ar_share"));
  expect(screen.getAllByTestId("enso-dot")[0]).toHaveAttribute("aria-label", "1982: 5,0");
});

test("the detail table sits in a details element, closed by default", () => {
  render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} />);
  const detail = screen.getByTestId("enso-detail");
  expect(detail.tagName).toBe("DETAILS");
  expect(detail).not.toHaveAttribute("open");
  expect(detail).toHaveTextContent("ver detalle");
  expect(detail).toContainElement(screen.getByTestId("enso-table"));
});

const variant = (over: Record<string, unknown> = {}) => ({
  label: "p99 polígono",
  quantile: 0.99,
  region: "polygon" as const,
  threshold_mm: 38.2,
  n_extreme_days_total: 40,
  rows: [
    {
      season: "DJF",
      phase_years: { nino: 7, neutral: 10, nina: 7 },
      groups: {
        nino: { n: 7, years_with_extreme: 5, total_days: 9, mean_days: 1.29 },
        neutral: { n: 10, years_with_extreme: 4, total_days: 6, mean_days: 0.6 },
        nina: { n: 7, years_with_extreme: 3, total_days: 4, mean_days: 0.57 },
      },
      diff_nino_nina: 0.7, p: 0.3, p_bh: 0.3412, p_3group: 0.4, p_3group_bh: 0.5,
      spearman_rho: 0.1, p_oni: 0.5, p_oni_bh: 0.6, sustained_bh: false,
    },
  ],
  season_years: [],
  ...over,
}); // fmt: skip
const extremes = (robust: Record<string, boolean>, v = variant()): EnsoExtremes => ({
  meta: { period: "1980-01-01/2025-12-30", season_years_period: "1980-2025", source: "ERA5 + MSWEP", n_perm: 10000 },
  variants: { main: v },
  robust,
});

test("F1.9 block is absent without data", () => {
  render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} />);
  expect(screen.queryByTestId("enso-extremes")).toBeNull();
});

test("F1.9 block: heading with threshold, count sentence, verdict and sensitivity line per season", () => {
  render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} extremes={extremes({ DJF: true, SON: false })} />);
  const block = screen.getByTestId("enso-extremes");
  expect(block).toHaveTextContent("Días de lluvia extrema (≥ p99, 38,2 mm/día)");
  expect(block).toHaveTextContent("5 de 7 veranos Niño y 3 de 7 veranos Niña tuvieron al menos un día extremo.");
  expect(block).toHaveTextContent("No se detecta diferencia entre años Niño y Niña (p BH = 0,3412).");
  expect(block).toHaveTextContent("Tampoco se detecta con p95 ni con el rectángulo anterior.");
  expect(block).not.toHaveTextContent("de cada 10");
  expect(screen.getByTestId("enso-extremes-source")).toHaveTextContent("Fuente: ERA5 + MSWEP. Período: 1980–2025.");
});

test("F1.9 block: non-robust and sustained branches; a season without a row shows nothing for it", () => {
  const v = variant();
  v.rows[0] = { ...v.rows[0], sustained_bh: true };
  const { rerender } = render(
    <EnsoPanel {...props} status="ready" stats={stats(rows16())} extremes={extremes({ DJF: false }, v)} />,
  );
  expect(screen.getByTestId("enso-extremes")).toHaveTextContent("Se detecta diferencia entre años Niño y Niña (p BH = 0,3412).");
  expect(screen.getByTestId("enso-extremes")).toHaveTextContent("Cambia con p95 o con el rectángulo anterior: no es robusto.");
  rerender(<EnsoPanel {...props} status="ready" stats={stats(rows16())} extremes={extremes({ DJF: false }, v)} />);
  fireEvent.click(screen.getByTestId("enso-tab-SON"));
  expect(screen.queryByTestId("enso-extremes")).toBeNull();
});

const sustainedVariant = (over: Record<string, unknown> = {}) => {
  const v = variant();
  v.rows[0] = { ...v.rows[0], sustained_bh: true, ...over };
  return v;
};
const withVariants = (main: ReturnType<typeof variant>, p95: ReturnType<typeof variant>, rect: ReturnType<typeof variant>, robust: boolean): EnsoExtremes => ({
  ...extremes({ DJF: robust }, main),
  variants: { main, p95, rectangle: rect },
});

test("F1.9 sensitivity line is computed from the three variants", () => {
  const sus = sustainedVariant();
  const none = variant();
  const view = (e: EnsoExtremes) => render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} extremes={e} />);
  let r = view(withVariants(none, none, none, true));
  expect(screen.getByTestId("enso-extremes-robust")).toHaveTextContent("Tampoco se detecta con p95 ni con el rectángulo anterior.");
  r.unmount();
  r = view(withVariants(sus, sus, sus, true));
  expect(screen.getByTestId("enso-extremes-robust")).toHaveTextContent("Se mantiene con p95 y con el rectángulo anterior.");
  r.unmount();
  r = view(withVariants(sus, sus, sus, false));
  expect(screen.getByTestId("enso-extremes-robust")).toHaveTextContent("Cambia con p95 o con el rectángulo anterior: no es robusto.");
  r.unmount();
  view(withVariants(sus, none, sus, true));
  expect(screen.getByTestId("enso-extremes-robust")).toHaveTextContent("Cambia con p95 o con el rectángulo anterior: no es robusto.");
});

test("F1.9 ONI line appears only when the main ONI relation is not kept by another variant", () => {
  const main = variant();
  main.rows[0] = { ...main.rows[0], spearman_rho: 0.456, p_oni_bh: 0.01 };
  const weak = variant();
  weak.rows[0] = { ...weak.rows[0], p_oni_bh: 0.2 };
  const strong = variant();
  strong.rows[0] = { ...strong.rows[0], p_oni_bh: 0.02 };
  const r = render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} extremes={withVariants(main, weak, strong, true)} />);
  expect(screen.getByTestId("enso-extremes-oni")).toHaveTextContent(
    "La relación con el ONI (ρ 0,46) solo aparece con el umbral principal: no es robusta.",
  );
  r.unmount();
  render(<EnsoPanel {...props} status="ready" stats={stats(rows16())} extremes={withVariants(main, strong, strong, true)} />);
  expect(screen.queryByTestId("enso-extremes-oni")).toBeNull();
});

import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import type { EnsoRow, EnsoStats } from "../api/client";
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

const stats = (rows: EnsoRow[]): EnsoStats => ({
  meta: { period: "1980-01-01/2025-12-30", season_years_period: "1980-2025", source: "ERA5 + ONI" },
  results: { rows, n_perm: 10000, seed: 0, alpha: 0.05 },
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
  expect(screen.getByTestId("enso-source")).toHaveTextContent("Fuente: ERA5 + ONI. Período: 1980-2025.");
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

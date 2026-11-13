import { useEffect, useState } from "react";
import type { EnsoExtremes, EnsoMetric, EnsoPhase, EnsoStats } from "../api/client";
import { es } from "../i18n/es";
import { buildStrip, type StripSize } from "./ensoChart";
import { ENSO_METRIC_FORMAT, formatDecimal, formatEnsoGroup, formatEnsoValue, formatPValue } from "./eventFormat";

const PHASES: EnsoPhase[] = ["nino", "neutral", "nina"];
const METRICS: EnsoMetric[] = ["n_events", "ar_days", "ivt_mean", "ar_share"];
const SIZE: StripSize = { width: 360, height: 220, margin: { top: 12, right: 12, bottom: 30, left: 44 } };

interface Props {
  status: "loading" | "ready" | "error";
  stats: EnsoStats | null;
  /** F1.9 report (extreme-rain days by phase); the block is shown only when present. */
  extremes?: EnsoExtremes | null;
  /** Layer source and period (manifest), shown with the numbers. */
  source: string;
  period: string;
  onClose: () => void;
}

/** "1980-2025" (any trailing note dropped) with an en dash; other texts pass through. */
const dashPeriod = (p: string) => {
  const m = p.match(/(\d{4})-(\d{4})/);
  return m ? `${m[1]}–${m[2]}` : p;
};

/** Content of the detail card: verdict, one-dot-per-year chart, the F1.8 table behind "ver detalle" and F1.9. */
export function EnsoPanel({ status, stats, extremes = null, source, period, onClose }: Props) {
  const rows = stats?.results.rows ?? [];
  const seasons = [...new Set(rows.map((r) => r.season))];
  const [picked, setPicked] = useState<string | null>(null);
  const [metric, setMetric] = useState<EnsoMetric>("ar_days");
  const season = picked && seasons.includes(picked) ? picked : (seasons[0] ?? null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const seasonRows = rows.filter((r) => r.season === season);
  const years = seasonRows[0]?.phase_years;
  const nBh = rows.filter((r) => r.sustained_bh).length;
  const yearsText = years
    ? `${es.enso.years}: ${PHASES.map((p) => `${es.enso[p]} ${years[p]}`).join(" · ")} (${es.enso.yearsUnit})`
    : "";
  const ensoPeriod = dashPeriod(stats?.meta.season_years_period ?? stats?.meta.period ?? period);
  const sourceText = `${es.enso.source}: ${stats?.meta.source ?? source}. ${es.enso.period}: ${ensoPeriod}.`;

  const perPhase = rows.flatMap((r) => [r.phase_years.nino, r.phase_years.nina]);
  const minYears = perPhase.length ? Math.min(...perPhase) : 0;
  const maxYears = perPhase.length ? Math.max(...perPhase) : 0;
  const range = minYears === maxYears ? es.enso.yearsRangeSame(minYears) : es.enso.yearsRange(minYears, maxYears);
  const verdict =
    (nBh === 0
      ? es.enso.verdictNone(rows.length, ensoPeriod, range)
      : es.enso.verdictSome(nBh, rows.length, ensoPeriod, range)) +
    " " +
    es.enso.verdictCaution;

  const scale = ENSO_METRIC_FORMAT[metric].scale;
  const strip = buildStrip(
    (stats?.season_years ?? [])
      .filter((d) => d.season === season)
      .map((d) => ({ year: d.year, phase: d.phase, value: d[metric] == null ? null : d[metric] * scale })),
    SIZE,
  );
  const chartLabel = [es.enso.chartLabel, es.enso.metrics[metric], season].join(", ");
  const meanNote = [es.enso.mean, "―"].join(": ");

  const ext = extremes?.variants.main;
  const extRow = ext?.rows.find((r) => r.season === season);
  const extVariantRows = Object.values(extremes?.variants ?? {}).map((v) => v?.rows.find((r) => r.season === season));
  const oniFragile =
    (extRow?.p_oni_bh ?? 1) < 0.05 && extVariantRows.some((r) => r && (r.p_oni_bh == null || r.p_oni_bh >= 0.05));
  const sensitivity = !extVariantRows.some((r) => r?.sustained_bh)
    ? es.enso.extremes.neverSustained
    : extVariantRows.every((r) => r?.sustained_bh) && extremes?.robust[season ?? ""]
      ? es.enso.extremes.robust
      : es.enso.extremes.notRobust;
  const extSourceText = extremes
    ? `${es.enso.source}: ${extremes.meta.source ?? source}. ${es.enso.period}: ${dashPeriod(
        extremes.meta.season_years_period ?? extremes.meta.period ?? period,
      )}.`
    : "";
  const extNoun = (season && es.enso.extremes.seasonNoun[season]) || "";

  return (
    <section className="enso-panel" id="enso-panel" data-testid="enso-panel" aria-label={es.enso.title}>
      <header className="enso-head">
        <h2>{es.enso.title}</h2>
        <button type="button" data-testid="enso-close" onClick={onClose}>
          {es.enso.close}
        </button>
      </header>
      {status === "loading" && <p className="empty">{es.enso.loading}</p>}
      {status === "error" && <p className="empty">{es.enso.error}</p>}
      {status === "ready" && stats && season && (
        <>
          <p className="enso-verdict" data-testid="enso-verdict">
            {verdict}
          </p>
          <div className="enso-tabs" role="tablist" aria-label={es.enso.seasons}>
            {seasons.map((s) => (
              <button
                key={s}
                type="button"
                role="tab"
                data-testid={`enso-tab-${s}`}
                aria-selected={s === season}
                onClick={() => setPicked(s)}
              >
                {s}
              </button>
            ))}
          </div>
          <div className="enso-metrics" role="group" aria-label={es.enso.metricsLabel}>
            {METRICS.map((m) => (
              <button
                key={m}
                type="button"
                data-testid={`enso-metric-${m}`}
                aria-pressed={m === metric}
                onClick={() => setMetric(m)}
              >
                {es.enso.metrics[m]}
              </button>
            ))}
          </div>
          {years && (
            <p className="enso-years" data-testid="enso-years">
              {yearsText}
            </p>
          )}
          <svg
            className="enso-chart"
            data-testid="enso-chart"
            viewBox={`0 0 ${SIZE.width} ${SIZE.height}`}
            role="img"
            aria-label={chartLabel}
          >
            {strip.ticks.map((t) => (
              <g key={t.value}>
                <line className="enso-grid" x1={SIZE.margin.left} x2={SIZE.width - SIZE.margin.right} y1={t.y} y2={t.y} />
                <text className="enso-tick" x={SIZE.margin.left - 6} y={t.y} textAnchor="end" dominantBaseline="middle">
                  {formatDecimal(t.value, t.value % 1 ? 1 : 0)}
                </text>
              </g>
            ))}
            {strip.columns.map((c) => (
              <text key={c.phase} className="enso-axis" x={c.cx} y={SIZE.height - 8} textAnchor="middle">
                {es.enso[c.phase]}
              </text>
            ))}
            {strip.means.map((m) => (
              <line key={m.phase} className="enso-mean" x1={m.x1} x2={m.x2} y1={m.y} y2={m.y} />
            ))}
            {strip.dots.map((d) => {
              const label = es.enso.dotTitle(d.year, formatDecimal(d.value, ENSO_METRIC_FORMAT[metric].digits));
              return (
                <circle
                  key={d.year}
                  className={`enso-dot enso-dot-${d.phase}`}
                  data-testid="enso-dot"
                  cx={d.x}
                  cy={d.y}
                  r={5}
                  aria-label={label}
                >
                  <title>{label}</title>
                </circle>
              );
            })}
          </svg>
          <p className="enso-note">{meanNote}</p>
          {ext && extRow && (
            <section className="enso-extremes" data-testid="enso-extremes">
              <h3>{es.enso.extremes.heading(formatDecimal(ext.threshold_mm, 1))}</h3>
              <p>
                {es.enso.extremes.counts(
                  extRow.groups.nino.years_with_extreme,
                  extRow.groups.nino.n,
                  extRow.groups.nina.years_with_extreme,
                  extRow.groups.nina.n,
                  extNoun,
                )}
              </p>
              <p data-testid="enso-extremes-verdict">
                {extRow.sustained_bh
                  ? es.enso.extremes.some(formatPValue(extRow.p_bh))
                  : es.enso.extremes.none(formatPValue(extRow.p_bh))}
              </p>
              <p data-testid="enso-extremes-robust">{sensitivity}</p>
              {oniFragile && extRow && (
                <p data-testid="enso-extremes-oni">{es.enso.extremes.oniFragile(formatDecimal(extRow.spearman_rho, 2))}</p>
              )}
              <p className="enso-note" data-testid="enso-extremes-source">
                {extSourceText}
              </p>
            </section>
          )}
          <details className="enso-detail" data-testid="enso-detail">
            <summary>{es.enso.detail}</summary>
            <div className="enso-scroll">
              <table className="enso-table" data-testid="enso-table">
                <thead>
                  <tr>
                    <th scope="col">{es.enso.metric}</th>
                    {PHASES.map((p) => (
                      <th key={p} scope="col">
                        {es.enso[p]} <span className="enso-sub">{es.enso.meanSd}</span>
                      </th>
                    ))}
                    <th scope="col">{es.enso.diff}</th>
                    <th scope="col">{es.enso.p}</th>
                    <th scope="col">{es.enso.pBh}</th>
                    <th scope="col">{es.enso.sustained}</th>
                  </tr>
                </thead>
                <tbody>
                  {seasonRows.map((r) => (
                    <tr key={r.metric} data-testid={`enso-row-${r.metric}`}>
                      <th scope="row">{es.enso.metrics[r.metric as EnsoMetric] ?? r.metric}</th>
                      {PHASES.map((p) => (
                        <td key={p}>{formatEnsoGroup(r.groups[p], r.metric)}</td>
                      ))}
                      <td>{formatEnsoValue(r.diff_nino_nina, r.metric)}</td>
                      <td>{formatPValue(r.p)}</td>
                      <td>{formatPValue(r.p_bh)}</td>
                      <td>{r.sustained_bh ? es.enso.yes : es.enso.no}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="enso-caveats" data-testid="enso-caveats">
              <li>{es.enso.caveatFew}</li>
              <li>{nBh === 0 ? es.enso.caveatNone : es.enso.caveatSome(nBh)}</li>
              <li>{es.enso.caveatPolygon}</li>
              <li>{es.enso.caveatRetro}</li>
            </ul>
          </details>
          <footer className="enso-foot">
            <p data-testid="enso-source">{sourceText}</p>
            <p>{es.enso.test(stats.results.n_perm)}</p>
          </footer>
        </>
      )}
    </section>
  );
}

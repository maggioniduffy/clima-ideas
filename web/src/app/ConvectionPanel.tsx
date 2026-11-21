import { useState } from "react";
import { es } from "../i18n/es";
import {
  curveFor,
  metricHi,
  metricLo,
  metricValue,
  type IdfData,
  type IdfMetric,
  type IdfRow,
} from "../layers/convectionIdf";
import type { ConvectionState } from "../layers/useConvectionIdf";
import {
  bandPath,
  CHART_MARGIN,
  linePath,
  logScale,
  tickAnchor,
  type Pt,
} from "./floodCharts";
import { durationLabel, logDomain, logTicks, spreadLabels } from "./idfChart";
import { useWidth } from "./useWidth";

const num1 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });
const fmtMm = (v: number) => num1.format(v);
const M = { ...CHART_MARGIN, r: 56 };
const DEFAULT_T = 10;

const chartHeight = (w: number) => Math.round(Math.min(220, Math.max(132, w * 0.34)));

function IdfChart({ idf, w, metric, t, showScenarios }: { idf: IdfData; w: number; metric: IdfMetric; t: number; showScenarios: boolean }) {
  const H = chartHeight(w);
  const main = idf.scenarios.find((s) => s.id === "main") ?? idf.scenarios[0]!;
  const scenarios = showScenarios ? idf.scenarios.filter((s) => s !== main) : [];
  const durations = idf.durations_h;
  const curves = idf.return_periods.map((rt) => ({ t: rt, rows: curveFor(main.gev, rt), gumbel: curveFor(main.gumbel ?? [], rt) }));
  const band = curveFor(main.gev, t);
  const vals = [
    ...curves.flatMap((c) => [...c.rows, ...c.gumbel].map((r) => metricValue(r, metric))),
    ...band.flatMap((r) => [metricLo(r, metric), metricHi(r, metric)]),
    ...scenarios.flatMap((s) => curveFor(s.gev, t).map((r) => metricValue(r, metric))),
  ].filter((v): v is number => v != null && v > 0);
  const [yLo, yHi] = logDomain(Math.min(...vals), Math.max(...vals));
  const x = logScale(durations[0]!, durations[durations.length - 1]!, M.l, w - M.r);
  const y = logScale(yLo, yHi, H - M.b, M.t);
  const pts = (rows: IdfRow[]): (Pt | null)[] =>
    rows.map((r) => {
      const v = metricValue(r, metric);
      return v == null ? null : { x: x(r.d), y: y(v) };
    });
  const bandRows = band.filter((r) => (metricLo(r, metric) ?? 0) > 0 && (metricHi(r, metric) ?? 0) > 0);
  const yTicks = logTicks(yLo, yHi);
  // duration labels that would overlap the previous one are skipped (the curves still have a point there)
  const shownDurations: number[] = [];
  for (const d of durations) {
    const prev = shownDurations[shownDurations.length - 1];
    if (prev == null || x(d) - x(prev) >= 40) shownDurations.push(d);
  }
  // end-of-curve labels pushed apart so they never overlap (12 px font)
  const labelY = new Map<number, number>();
  const ends = curves
    .map((c) => ({ t: c.t, y: c.rows.length ? y(metricValue(c.rows[c.rows.length - 1]!, metric) ?? yLo) : NaN }))
    .filter((e) => !Number.isNaN(e.y))
    .sort((a, b) => a.y - b.y);
  // labels keep >= 14 px apart and stay inside the plot, above the x tick labels (which start ~6 px under the axis; the text box is ~14 px tall)
  const spread = spreadLabels(ends.map((e) => e.y), 14, M.t + 2, H - M.b - 6);
  ends.forEach((e, i) => labelY.set(e.t, spread[i]!));
  return (
    <svg viewBox={`0 0 ${w} ${H}`} className="flood-chart" role="img" aria-label={es.convection.idfLabel} data-testid="idf-chart" data-curves={curves.length}>
      {yTicks.map((v) => (
        <g key={v}>
          <line x1={M.l} x2={w - M.r} y1={y(v)} y2={y(v)} className="flood-grid" />
          <text x={M.l - 6} y={y(v) + 4} textAnchor="end" className="flood-tick">
            {String(v).replace(".", ",")}
          </text>
        </g>
      ))}
      {shownDurations.map((d) => (
        <text key={d} x={x(d)} y={H - M.b + 15} textAnchor={tickAnchor(x(d), w, durationLabel(d))} className="flood-tick">
          {durationLabel(d)}
        </text>
      ))}
      <text x={(M.l + w - M.r) / 2} y={H - 3} textAnchor="middle" className="flood-axis">
        {es.convection.axisDuration}
      </text>
      <text x={4} y={12} className="flood-axis">
        {metric === "intensity" ? es.convection.axisIntensity : es.convection.axisDepth}
      </text>
      {bandRows.length > 1 && (
        <path
          d={bandPath(
            bandRows.map((r): Pt => ({ x: x(r.d), y: y(metricHi(r, metric)!) })),
            bandRows.map((r): Pt => ({ x: x(r.d), y: y(metricLo(r, metric)!) })),
          )}
          className="flood-band"
          data-testid="idf-band"
          data-t={t}
        />
      )}
      {curves.map((c) => {
        const extrap = c.rows.some((r) => r.extrapolated);
        const last = c.rows[c.rows.length - 1];
        const lastV = last ? metricValue(last, metric) : null;
        return (
          <g key={c.t}>
            {c.gumbel.length > 1 && (
              <path d={linePath(pts(c.gumbel))} className="idf-gumbel" data-testid={`idf-gumbel-${c.t}`} />
            )}
            <path
              d={linePath(pts(c.rows))}
              className={`idf-curve${c.t === t ? " idf-curve-selected" : ""}${extrap ? " idf-curve-extrap" : ""}`}
              data-testid={`idf-curve-${c.t}`}
              data-extrapolated={extrap}
            />
            {lastV != null && (
              <text x={w - M.r + 5} y={(labelY.get(c.t) ?? y(lastV)) + 4} className="flood-tick" data-testid={`idf-label-${c.t}`}>
                {es.convection.t(c.t, extrap)}
              </text>
            )}
          </g>
        );
      })}
      {scenarios.map((s) => (
        <path key={s.id} d={linePath(pts(curveFor(s.gev, t)))} className="idf-scenario" data-testid={`idf-scenario-${s.id}`} />
      ))}
    </svg>
  );
}

export interface ConvectionPanelProps {
  state: ConvectionState;
  /** Layer manifest values: source and period of the data shown. */
  source: string;
  period: string;
}

/**
 * Detail-card content of the `convection-idf` layer: the IDF chart with its source rows. The storm replay lives in the
 * timeline strip (ConvectionReplay); the long explanatory notes sit in a closed "Ver notas" disclosure.
 */
export function ConvectionPanel({ state, source, period }: ConvectionPanelProps) {
  const [metric, setMetric] = useState<IdfMetric>("intensity");
  const [t, setT] = useState(DEFAULT_T);
  const [showScenarios, setShowScenarios] = useState(false);
  const [idfRef, idfW] = useWidth();
  const { status, idf, replay } = state;
  if (status === "loading" || status === "idle") return <p className="empty">{es.convection.loading}</p>;
  if (status === "error" || !idf || !replay) return <p className="empty">{es.convection.error}</p>;
  const sc = idf.scenarios.filter((s) => s.id !== "main");
  const cmp = replay.compare;
  const legend = `${[
    es.convection.legendGev,
    es.convection.legendGumbel,
    es.convection.legendBand(Math.round(idf.ci_level * 100)),
    showScenarios && es.convection.legendScenario(sc.map((s) => s.label).join(" y ")),
  ]
    .filter(Boolean)
    .join(". ")}.`;
  const scenariosNote = `${es.convection.scenariosTitle}.`;
  const cellNote = `${es.convection.cell(idf.cell.lat.toFixed(2).replace(".", ","), idf.cell.lon.toFixed(2).replace(".", ","))}.`;
  const stationNote = `${es.convection.stationSource(cmp.station.source)}. ${cmp.station.note}.`;
  return (
    <div className="conv-panel" data-testid="convection-panel">
      <p className="conv-label" data-testid="idf-label">
        {idf.label}
      </p>
      <div className="conv-col" ref={idfRef} role="group" aria-labelledby="idf-title">
        <h4 id="idf-title" className="sr-only">
          {es.convection.idfTitle}
        </h4>
        <div className="conv-head">
          {sc.length > 0 && (
            <label className="conv-check" title={es.convection.scenariosTitle}>
              <input type="checkbox" data-testid="idf-scenarios" checked={showScenarios} onChange={(e) => setShowScenarios(e.target.checked)} />
              {es.convection.scenarios}
            </label>
          )}
          <div className="conv-seg" role="group" aria-label={es.convection.metricLabel}>
            {(["intensity", "depth"] as const).map((m) => (
              <button key={m} type="button" data-testid={`idf-metric-${m}`} aria-pressed={metric === m} onClick={() => setMetric(m)}>
                {es.convection[m]}
              </button>
            ))}
          </div>
        </div>
        <div className="conv-seg" role="group" aria-label={es.convection.returnLabel}>
          {idf.return_periods.map((rt) => {
            const extrap = rt > idf.extrapolation_above_t;
            return (
              <button
                key={rt}
                type="button"
                data-testid={`idf-t-${rt}`}
                aria-pressed={t === rt}
                aria-label={es.convection.tTitle(rt)}
                onClick={() => setT(rt)}
              >
                {es.convection.t(rt, extrap)}
              </button>
            );
          })}
        </div>
        <figure className="flood-figure">
          <IdfChart idf={idf} w={idfW} metric={metric} t={t} showScenarios={showScenarios} />
        </figure>
      </div>
      <p className="conv-note" data-testid="idf-source">
        {[
          source,
          es.convection.periodLabel(idf.period),
          period,
        ].join(es.events.sep)}
      </p>
      <p className="flood-warn" data-testid="conv-not-alert">
        {es.convection.notAlert}
      </p>
      <details className="conv-notes" data-testid="conv-notes">
        <summary>{es.convection.notesSummary}</summary>
        <p className="conv-note" data-testid="idf-legend">
          {legend}
        </p>
        <p className="conv-note" data-testid="idf-scenarios-note">
          {scenariosNote}
        </p>
        <p className="conv-note" data-testid="idf-cell">
          {cellNote}
        </p>
        <p className="conv-note" data-testid="idf-extrapolation">
          {es.convection.extrapolation(idf.extrapolation_above_t, idf.n_years)}
        </p>
        <p className="conv-note" data-testid="conv-bias-caveat">
          {es.convection.biasCaveat(fmtMm(cmp.imerg_mm), fmtMm(cmp.station.value_mm))}
        </p>
        <p className="conv-note">{es.convection.replayCaption}</p>
        <p className="conv-note" data-testid="compare-station-note">
          {stationNote}
        </p>
      </details>
    </div>
  );
}

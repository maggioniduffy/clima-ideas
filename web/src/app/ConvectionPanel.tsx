import { useState } from "react";
import { es } from "../i18n/es";
import { formatUtc } from "../layers/arEvents";
import {
  curveFor,
  cumulativeAt,
  metricHi,
  metricLo,
  metricValue,
  type IdfData,
  type IdfMetric,
  type IdfRow,
  type ReplayData,
} from "../layers/convectionIdf";
import type { ConvectionState } from "../layers/useConvectionIdf";
import {
  bandPath,
  CHART_MARGIN,
  linePath,
  linearScale,
  linearTicks,
  logScale,
  niceMax,
  tickAnchor,
  type Pt,
} from "./floodCharts";
import { durationLabel, logDomain, logTicks, utcTickLabel } from "./idfChart";
import { useWidth } from "./useWidth";

const num1 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });
const num2 = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtMm = (v: number) => num1.format(v);
const M = { ...CHART_MARGIN, r: 56 };
const DEFAULT_T = 10;

const chartHeight = (w: number) => Math.round(Math.min(260, Math.max(190, w * 0.5)));

const ICONS = { play: "M4 2.5 V13.5 L13 8 Z", pause: "M4 3h3v10H4zM9 3h3v10H9z", prev: "M12 3 V13 L5 8 Z M3 3 V13", next: "M4 3 V13 L11 8 Z M13 3 V13" };
function Icon({ d, stroke = false }: { d: string; stroke?: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path d={d} fill="currentColor" stroke={stroke ? "currentColor" : undefined} strokeWidth={stroke ? 1.6 : undefined} />
    </svg>
  );
}

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
  const bandRows = band.filter((r) => metricLo(r, metric) != null && metricHi(r, metric) != null);
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
  ends.forEach((e, i) => labelY.set(e.t, i === 0 ? e.y : Math.max(e.y, labelY.get(ends[i - 1]!.t)! + 13)));
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

function CompareChart({ replay, w, cursorMs }: { replay: ReplayData; w: number; cursorMs: number | null }) {
  const H = Math.round(Math.min(200, Math.max(130, w * 0.4)));
  const { cumulative: c, compare } = replay;
  const t0 = Date.parse(c.start);
  const stepMs = c.step_minutes * 60_000;
  const t1 = t0 + (c.mm.length - 1) * stepMs;
  const endMs = Date.parse(compare.end);
  const station = compare.station.value_mm;
  const yMax = niceMax(Math.max(station, ...c.mm));
  const x = linearScale(t0, t1, M.l, w - 18);
  const y = linearScale(0, yMax, H - M.b, M.t);
  const line = linePath(c.mm.map((v, k) => ({ x: x(t0 + k * stepMs), y: y(v) })));
  const dayTicks: number[] = [];
  for (let t = t0; t <= t1; t += 24 * 3_600_000) dayTicks.push(t);
  const cursorOn = cursorMs != null && cursorMs >= t0 && cursorMs <= t1;
  const cursorV = cursorMs != null ? cumulativeAt(c, cursorMs) : null;
  return (
    <svg viewBox={`0 0 ${w} ${H}`} className="flood-chart" role="img" aria-label={es.convection.compareLabel} data-testid="compare-chart">
      {linearTicks(yMax, 4).map((v) => (
        <g key={v}>
          <line x1={M.l} x2={w - 18} y1={y(v)} y2={y(v)} className="flood-grid" />
          <text x={M.l - 6} y={y(v) + 4} textAnchor="end" className="flood-tick">
            {fmtMm(v)}
          </text>
        </g>
      ))}
      {dayTicks.map((t) => (
        <text key={t} x={x(t)} y={H - M.b + 15} textAnchor={tickAnchor(x(t), w, utcTickLabel(t))} className="flood-tick">
          {utcTickLabel(t)}
        </text>
      ))}
      <text x={(M.l + w - 18) / 2} y={H - 3} textAnchor="middle" className="flood-axis">
        {es.convection.axisTime}
      </text>
      <text x={4} y={12} className="flood-axis">
        {es.convection.axisAccum}
      </text>
      <line x1={x(endMs)} x2={x(endMs)} y1={M.t} y2={H - M.b} className="idf-window-end" />
      <path d={line} className="flood-curve" data-testid="compare-imerg-line" />
      <circle cx={x(endMs)} cy={y(compare.imerg_mm)} r={4} className="flood-dot" data-testid="compare-imerg-point" />
      <circle cx={x(endMs)} cy={y(station)} r={5} className="flood-dot flood-dot-top" data-testid="compare-station-point" />
      {cursorOn && (
        <g data-testid="compare-cursor">
          <line x1={x(cursorMs)} x2={x(cursorMs)} y1={M.t} y2={H - M.b} className="idf-cursor" />
          {cursorV != null && <circle cx={x(cursorMs)} cy={y(cursorV)} r={3} className="idf-cursor-dot" />}
        </g>
      )}
    </svg>
  );
}

function Controls({ s }: { s: ConvectionState }) {
  return (
    <div className="replay-controls rain-controls" data-testid="rain-controls" data-frame={s.frame} data-playing={s.playing}>
      <button type="button" className="replay-step" data-testid="rain-back" aria-label={es.convection.stepBack} onClick={() => s.step(-1)}>
        <Icon d={ICONS.prev} stroke />
      </button>
      <button
        type="button"
        className="replay-play"
        data-testid="rain-play"
        aria-label={s.playing ? es.convection.pause : es.convection.play}
        aria-pressed={s.playing}
        onClick={s.toggle}
      >
        <Icon d={s.playing ? ICONS.pause : ICONS.play} />
      </button>
      <button type="button" className="replay-step" data-testid="rain-forward" aria-label={es.convection.stepForward} onClick={() => s.step(1)}>
        <Icon d={ICONS.next} stroke />
      </button>
      <input
        type="range"
        data-testid="rain-slider"
        aria-label={es.convection.frame}
        min={0}
        max={Math.max(s.nFrames - 1, 0)}
        value={s.frame}
        onChange={(e) => s.seek(Number(e.target.value))}
      />
      <span className="num replay-time" data-testid="rain-time">
        {s.cursorMs != null && formatUtc(s.cursorMs)}
      </span>
    </div>
  );
}

export interface ConvectionPanelProps {
  state: ConvectionState;
  /** Layer manifest values: source and period of the data shown. */
  source: string;
  period: string;
}

/** Detail-card content of the `convection-idf` layer: IDF chart, replay controls and the cumulative-vs-station chart. */
export function ConvectionPanel({ state, source, period }: ConvectionPanelProps) {
  const [metric, setMetric] = useState<IdfMetric>("intensity");
  const [t, setT] = useState(DEFAULT_T);
  const [showScenarios, setShowScenarios] = useState(false);
  const [idfRef, idfW] = useWidth();
  const [cmpRef, cmpW] = useWidth();
  const { status, idf, replay } = state;
  if (status === "loading" || status === "idle") return <p className="empty">{es.convection.loading}</p>;
  if (status === "error" || !idf || !replay) return <p className="empty">{es.convection.error}</p>;
  const sc = idf.scenarios.filter((s) => s.id !== "main");
  const cmp = replay.compare;
  const cur = cumulativeAt(replay.cumulative, state.cursorMs ?? NaN);
  const stationMm = cmp.station.value_mm;
  const legend = `${[
    es.convection.legendGev,
    es.convection.legendGumbel,
    es.convection.legendBand(Math.round(idf.ci_level * 100)),
    showScenarios && es.convection.legendScenario(sc.map((s) => s.label).join(" y ")),
  ]
    .filter(Boolean)
    .join(". ")}.`;
  const stationNote = `${es.convection.stationSource(cmp.station.source)}. ${cmp.station.note}.`;
  return (
    <div className="conv-panel" data-testid="convection-panel">
      <p className="conv-label" data-testid="idf-label">
        {idf.label}
      </p>
      <div className="conv-grid">
        <div className="conv-col" ref={idfRef} role="group" aria-labelledby="idf-title">
          <h4 id="idf-title">{es.convection.idfTitle}</h4>
          <div className="conv-seg" role="group" aria-label={es.convection.metricLabel}>
            {(["intensity", "depth"] as const).map((m) => (
              <button key={m} type="button" data-testid={`idf-metric-${m}`} aria-pressed={metric === m} onClick={() => setMetric(m)}>
                {es.convection[m]}
              </button>
            ))}
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
          {sc.length > 0 && (
            <label className="conv-check">
              <input type="checkbox" data-testid="idf-scenarios" checked={showScenarios} onChange={(e) => setShowScenarios(e.target.checked)} />
              {es.convection.scenarios}
            </label>
          )}
          <figure className="flood-figure">
            <IdfChart idf={idf} w={idfW} metric={metric} t={t} showScenarios={showScenarios} />
            <figcaption data-testid="idf-legend">
              {legend}
            </figcaption>
            <figcaption data-testid="idf-extrapolation">
              {es.convection.extrapolation(idf.extrapolation_above_t, idf.n_years)}
            </figcaption>
          </figure>
        </div>
        <div className="conv-col" ref={cmpRef} role="group" aria-labelledby="replay-title">
          <h4 id="replay-title">{es.convection.replayTitle}</h4>
          <Controls s={state} />
          <h4>{es.convection.compareTitle}</h4>
          <figure className="flood-figure">
            <CompareChart replay={replay} w={cmpW} cursorMs={state.cursorMs} />
          </figure>
          <dl className="kv conv-readout" data-testid="compare-readout">
            <dt>{es.convection.imerg(cmp.window)}</dt>
            <dd className="num" data-testid="compare-imerg">
              {fmtMm(cmp.imerg_mm)} {es.convection.mm}
            </dd>
            <dt>{es.convection.station(cmp.station.name)}</dt>
            <dd className="num" data-testid="compare-station">
              {fmtMm(stationMm)} {es.convection.mm}
            </dd>
            <dt>{es.convection.ratio}</dt>
            <dd className="num" data-testid="compare-ratio">
              {num2.format(cmp.imerg_mm / stationMm)}
            </dd>
            <dt>{es.convection.current}</dt>
            <dd className="num" data-testid="compare-current">
              {cur == null ? es.convection.beforeWindow : `${fmtMm(cur)} ${es.convection.mm}`}
            </dd>
          </dl>
          <p className="conv-note" data-testid="compare-source">
            {stationNote}
          </p>
        </div>
      </div>
      <p className="conv-note" data-testid="idf-source">
        {[
          source,
          es.convection.periodLabel(idf.period),
          period,
          es.convection.cell(idf.cell.lat.toFixed(2).replace(".", ","), idf.cell.lon.toFixed(2).replace(".", ",")),
        ].join(es.events.sep)}
      </p>
      <p className="flood-warn" data-testid="conv-bias-caveat">
        {es.convection.biasCaveat(fmtMm(cmp.imerg_mm), fmtMm(stationMm))}
      </p>
      <p className="conv-note">{es.convection.replayCaption}</p>
      <p className="flood-warn" data-testid="conv-not-alert">
        {es.convection.notAlert}
      </p>
    </div>
  );
}

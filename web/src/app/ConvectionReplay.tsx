import { useEffect, useState } from "react";
import { es } from "../i18n/es";
import { formatUtc } from "../layers/arEvents";
import { cumulativeAt, type ReplayData } from "../layers/convectionIdf";
import type { ConvectionState } from "../layers/useConvectionIdf";
import { CHART_MARGIN, linePath, linearScale, linearTicks, niceMax, tickAnchor } from "./floodCharts";
import { utcTickLabel } from "./idfChart";

const num1 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });
const num2 = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtMm = (v: number) => num1.format(v);
/** Compact margins: the strip is short, so the time axis title moves to the top right. */
const M = { ...CHART_MARGIN, t: 20, b: 22 };

/** Size of the element's content box, following the strip as it is resized. */
function useSize() {
  const [el, ref] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 320, h: 100 });
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const read = () => setSize({ w: Math.max(200, Math.round(el.clientWidth)), h: Math.max(80, Math.round(el.clientHeight)) });
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [ref, size] as const;
}

const ICONS = { play: "M4 2.5 V13.5 L13 8 Z", pause: "M4 3h3v10H4zM9 3h3v10H9z", prev: "M12 3 V13 L5 8 Z M3 3 V13", next: "M4 3 V13 L11 8 Z M13 3 V13" };
function Icon({ d, stroke = false }: { d: string; stroke?: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path d={d} fill="currentColor" stroke={stroke ? "currentColor" : undefined} strokeWidth={stroke ? 1.6 : undefined} />
    </svg>
  );
}

function CompareChart({ replay, w, h, cursorMs }: { replay: ReplayData; w: number; h: number; cursorMs: number | null }) {
  const H = h;
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
        <text key={t} x={x(t)} y={H - M.b + 14} textAnchor={tickAnchor(x(t), w, utcTickLabel(t))} className="flood-tick">
          {utcTickLabel(t)}
        </text>
      ))}
      <text x={w - 18} y={12} textAnchor="end" className="flood-axis">
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


export interface ConvectionReplayProps {
  state: ConvectionState;
}

/**
 * April 2014 storm replay for the bottom timeline strip: controls and readout on the left, the cumulative chart
 * (IMERG cell against the station) filling the rest. Driven by the same state as the map's rain frames.
 */
export function ConvectionReplay({ state }: ConvectionReplayProps) {
  const [ref, { w, h }] = useSize();
  const { replay } = state;
  if (state.status !== "ready" || !replay) return null;
  const cmp = replay.compare;
  const stationMm = cmp.station.value_mm;
  const cur = cumulativeAt(replay.cumulative, state.cursorMs ?? NaN);
  return (
    <section className="conv-replay" data-testid="convection-replay" aria-labelledby="replay-title">
      <div className="conv-replay-side">
        <h4 id="replay-title">{es.convection.replayTitle}</h4>
        <Controls s={state} />
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
      </div>
      <figure className="conv-replay-chart">
        <div className="conv-replay-head">
          <h4>{es.convection.compareTitle}</h4>
          <span className="conv-note" data-testid="compare-source">
            {es.convection.stationSource(cmp.station.source)}
          </span>
        </div>
        <div className="conv-replay-plot" ref={ref}>
          <CompareChart replay={replay} w={w} h={h} cursorMs={state.cursorMs} />
        </div>
      </figure>
    </section>
  );
}

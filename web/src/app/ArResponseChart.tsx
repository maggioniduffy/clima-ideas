import { useState } from "react";
import type { ArEvent, ArResponses, ArStationResponse } from "../api/client";
import { es } from "../i18n/es";
import { CHART_MARGIN, dayOffset, formatDateEs, responseChartGeometry, tickAnchor } from "./floodCharts";
import { eventFields } from "./eventFormat";
import { useWidth } from "./useWidth";

/** More stations than this and the section shows one chart with a station selector instead of all of them. */
export const MAX_STACKED_STATIONS = 3;

const CHART_H = 130;
const M = CHART_MARGIN;
const qFmt = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });
const ratioFmt = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const fmtQ = (q: number) => qFmt.format(q);
const fmtTick = (v: number) => new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(v));

function StationChart({ r, event, responses, width }: { r: ArStationResponse; event: ArEvent; responses: ArResponses; width: number }) {
  const station = responses.stations.find((s) => s.id === r.station_id);
  const name = station?.name ?? r.station_id;
  const g = responseChartGeometry({
    daily: r.daily,
    eventStart: event.start,
    eventEnd: event.end,
    windowDaysAfter: responses.window_days_after,
    width,
    height: CHART_H,
  });
  const peakIdx = dayOffset(r.daily.start, r.peak_date);
  const peakV = r.daily.q[peakIdx] ?? null;
  return (
    <div className="ar-resp-station" data-testid={`ar-response-${r.station_id}`}>
      <h4 className="ar-resp-name">
        {name}
        {station?.river && <span className="flood-river">{station.river}</span>}
      </h4>
      {station?.regulated && (
        <p className="flood-warn" data-testid={`ar-response-regulated-${r.station_id}`}>
          {es.events.responses.regulated}
        </p>
      )}
      <svg
        viewBox={`0 0 ${width} ${CHART_H}`}
        className="flood-chart"
        role="img"
        aria-label={es.events.responses.chartLabel(name)}
        data-testid={`ar-response-chart-${r.station_id}`}
      >
        {g.yTicks.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={width - M.r} y1={g.y(v)} y2={g.y(v)} className="flood-grid" />
            <text x={M.l - 6} y={g.y(v) + 4} textAnchor="end" className="flood-tick">
              {fmtTick(v)}
            </text>
          </g>
        ))}
        <text x={4} y={12} className="flood-axis">
          {es.events.responses.axisQ}
        </text>
        <rect
          x={g.shade.x0}
          y={M.t}
          width={Math.max(g.shade.x1 - g.shade.x0, 1)}
          height={CHART_H - M.b - M.t}
          className="ar-shade"
          data-testid={`ar-response-shade-${r.station_id}`}
        />
        <line
          x1={g.windowEndX}
          x2={g.windowEndX}
          y1={M.t}
          y2={CHART_H - M.b}
          className="ar-window-end"
          data-testid={`ar-response-window-end-${r.station_id}`}
        />
        {g.xTicks.map((t) => (
          <text
            key={t.label}
            x={t.x}
            y={CHART_H - M.b + 15}
            textAnchor={tickAnchor(t.x, width, t.label)}
            className="flood-tick"
          >
            {t.label}
          </text>
        ))}
        <path d={g.path} className="ar-resp-line" />
        {peakV != null && <circle cx={g.x(peakIdx)} cy={g.y(peakV)} r={3} className="flood-dot flood-dot-top" />}
      </svg>
      <dl className="kv ar-resp-values" data-testid={`ar-response-values-${r.station_id}`}>
        <dt>{es.events.responses.before}</dt>
        <dd className="num">{r.q_before == null ? es.events.noData : `${fmtQ(r.q_before)} ${es.flood.unit}`}</dd>
        <dt>{es.events.responses.peak}</dt>
        <dd className="num">{fmtQ(r.q_peak)} {es.flood.unit}</dd>
        <dd className="num kv-wide">{es.events.responses.peakOn(formatDateEs(r.peak_date), r.lag_days)}</dd>
        {r.ratio != null && (
          <>
            <dt>{es.events.responses.ratio}</dt>
            <dd className="num">{ratioFmt.format(r.ratio)}</dd>
          </>
        )}
      </dl>
    </div>
  );
}

/**
 * Daily caudal at the stations around a selected AR event ("coincide con", no causal claim): the event window is
 * shaded, the end of the response window dashed, regulated stations labelled, the event's freezing level and the
 * file's caveat, source and period alongside. Renders nothing when the event has no flow data.
 */
export function ArResponseChart({ responses, event }: { responses: ArResponses; event: ArEvent }) {
  const list = responses.events[event.event_id] ?? [];
  const [pick, setPick] = useState<string | null>(null);
  const [ref, w] = useWidth();
  if (list.length === 0) return null;
  const nameOf = (id: string) => responses.stations.find((s) => s.id === id)?.name ?? id;
  const selector = list.length > MAX_STACKED_STATIONS;
  const shown = selector ? [list.find((r) => r.station_id === pick) ?? list[0]!] : list;
  const f = eventFields(event);
  return (
    <div className="ar-response" data-testid="ar-response" ref={ref}>
      <h3>{es.events.responses.title}</h3>
      <dl className="kv" data-testid="ar-response-deg0l">
        <dt>{es.events.deg0lMax}</dt>
        <dd className="num">{f.deg0lMax}</dd>
      </dl>
      {selector && (
        <select
          className="ar-sort"
          data-testid="ar-response-station-select"
          aria-label={es.events.responses.station}
          value={shown[0]!.station_id}
          onChange={(e) => setPick(e.target.value)}
        >
          {list.map((r) => (
            <option key={r.station_id} value={r.station_id}>
              {nameOf(r.station_id)}
            </option>
          ))}
        </select>
      )}
      {shown.map((r) => (
        <StationChart key={r.station_id} r={r} event={event} responses={responses} width={w} />
      ))}
      <p className="empty">{es.events.responses.legend(responses.window_days_after)}</p>
      <p className="empty" data-testid="ar-response-note">{responses.note}</p>
      <p className="empty" data-testid="ar-response-source">
        {es.events.responses.source(responses.source, responses.period)}
      </p>
    </div>
  );
}

import { useState } from "react";
import { FLOOD_LAYER_ID, useFloodEvents, type FloodEvent } from "../layers/useFloodStation";
import {
  CHART_MARGIN,
  dayOffset,
  forecastBandPath,
  forecastPoints,
  eventYMax,
  formatDateEs,
  isoAddDays,
  issueLabel,
  linePath,
  linearScale,
  linearTicks,
  persistencePoints,
  tickAnchor,
} from "./floodCharts";

/** Spanish copy of the flood card (kept here: the card is self-contained). */
export const eventText = {
  title: "Ficha de crecida",
  loading: "Cargando pronósticos retrospectivos…",
  error: "No se pudieron cargar los pronósticos retrospectivos",
  eventsLabel: "Crecida pasada",
  issueLabel: "Día de emisión",
  chartLabel: "Pronóstico retrospectivo del LSTM frente al caudal observado",
  axisQ: "Caudal (m³/s)",
  observed: "Observado",
  median: "Mediana del conjunto LSTM",
  band: "Banda 90 %",
  persistence: "Persistencia",
  peak: "Pico",
  unit: "m³/s",
};

const SEP = " · ";
const M = CHART_MARGIN;
const numFmt = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });
const fmtQ = (q: number) => numFmt.format(Math.round(q));
const yearsOf = (period: string) => period.split("/").map((d) => d.slice(0, 4)).join("–");
const ddmm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

function EventChart({ event, issueIndex, w }: { event: FloodEvent; issueIndex: number; w: number }) {
  const W = w;
  const H = Math.round(Math.min(300, Math.max(180, w * 0.7)));
  const { start, q } = event.obs;
  const last = q.length - 1;
  const issue = event.issues[issueIndex]!;
  const yMax = eventYMax(event);
  const x = linearScale(0, last, M.l, W - M.r);
  const y = linearScale(0, yMax, H - M.b, M.t);
  const peakDay = dayOffset(start, event.peak_date);
  const issueDay = dayOffset(start, issue.issue_date);
  const pts = forecastPoints(start, issue);
  const observed = linePath(q.map((v, i) => (v == null ? null : { x: x(i), y: y(v) })));
  const median = linePath([
    ...(issue.persistence != null ? [{ x: x(issueDay), y: y(issue.persistence) }] : []),
    ...pts.map((p) => (p.median == null ? null : { x: x(p.day), y: y(p.median) })),
  ]);
  const persistence = linePath(persistencePoints(start, issue).map((p) => ({ x: x(p.x), y: y(p.y) })));
  const band = forecastBandPath(pts, x, y);
  const ticks = Array.from({ length: Math.floor(last / 7) + 1 }, (_, i) => i * 7);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="flood-chart" role="img" aria-label={eventText.chartLabel} data-testid="event-chart">
      {linearTicks(yMax, 4).map((v) => (
        <g key={v}>
          <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} className="flood-grid" />
          <text x={M.l - 6} y={y(v) + 4} textAnchor="end" className="flood-tick">
            {fmtQ(v)}
          </text>
        </g>
      ))}
      {ticks.map((d) => (
        <text key={d} x={x(d)} y={H - M.b + 15} textAnchor={tickAnchor(x(d), W, ddmm(isoAddDays(start, d)))} className="flood-tick">
          {ddmm(isoAddDays(start, d))}
        </text>
      ))}
      <text x={4} y={12} className="flood-axis">
        {eventText.axisQ}
      </text>
      <line x1={x(peakDay)} x2={x(peakDay)} y1={M.t} y2={H - M.b} stroke="var(--accent)" strokeWidth={2} data-testid="event-peak-mark" />
      <line
        x1={x(issueDay)}
        x2={x(issueDay)}
        y1={M.t}
        y2={H - M.b}
        stroke="var(--text-muted)"
        strokeWidth={1}
        strokeDasharray="1 3"
        data-testid="event-issue-mark"
      />
      {band && <path d={band} fill="var(--water)" fillOpacity={0.28} stroke="none" data-testid="event-band" />}
      <path d={observed} fill="none" stroke="var(--text)" strokeWidth={1.5} strokeLinejoin="round" data-testid="event-observed" />
      {persistence && (
        <path
          d={persistence}
          fill="none"
          stroke="var(--text-muted)"
          strokeWidth={1.25}
          strokeDasharray="4 3"
          data-testid="event-persistence"
        />
      )}
      <path d={median} fill="none" stroke="var(--water)" strokeWidth={2} strokeLinejoin="round" data-testid="event-median" />
    </svg>
  );
}

function Legend() {
  const item = (label: string, swatch: JSX.Element) => (
    <li style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <svg width="18" height="8" aria-hidden="true">
        {swatch}
      </svg>
      <span>{label}</span>
    </li>
  );
  return (
    <ul
      data-testid="event-legend"
      style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexWrap: "wrap", gap: "4px 12px", fontSize: 13, color: "var(--text-muted)" }}
    >
      {item(eventText.observed, <line x1="0" x2="18" y1="4" y2="4" stroke="var(--text)" strokeWidth="1.5" />)}
      {item(eventText.median, <line x1="0" x2="18" y1="4" y2="4" stroke="var(--water)" strokeWidth="2" />)}
      {item(eventText.band, <rect x="0" y="0" width="18" height="8" fill="var(--water)" fillOpacity="0.28" />)}
      {item(
        eventText.persistence,
        <line x1="0" x2="18" y1="4" y2="4" stroke="var(--text-muted)" strokeWidth="1.25" strokeDasharray="4 3" />,
      )}
      {item(eventText.peak, <line x1="0" x2="18" y1="4" y2="4" stroke="var(--accent)" strokeWidth="2" />)}
    </ul>
  );
}

/** Flood card (F2.6): LSTM hindcast of a past flood against the observed flow, one issue day at a time. */
export function FloodEventCard({ stationId, width }: { stationId: string; width: number }) {
  const { status, data } = useFloodEvents(FLOOD_LAYER_ID, stationId, true);
  const [eventIdx, setEventIdx] = useState<number | null>(null);
  const [issueIdx, setIssueIdx] = useState<number | null>(null);
  if (status === "loading") return <p className="empty">{eventText.loading}</p>;
  if (status === "error") return <p className="empty">{eventText.error}</p>;
  if (!data || data.events.length === 0) return null;
  const { meta } = data;
  const ei = Math.min(eventIdx ?? data.events.length - 1, data.events.length - 1);
  const event = data.events[ei]!;
  if (event.issues.length === 0) return null;
  const ii = Math.min(issueIdx ?? event.issues.length - 1, event.issues.length - 1);
  const issue = event.issues[ii]!;
  const area = meta.area_km2 != null ? `${numFmt.format(meta.area_km2)} km²` : null;
  const modelLine = [
    `LSTM (${meta.seeds.length} semillas, prueba ${meta.test_years[0]}–${meta.test_years[1]})`,
    meta.forcing,
    meta.pretrain && `preentrenado con ${meta.pretrain}`,
    area && `área ${area}${meta.area_note ? ` (${meta.area_note})` : ""}`,
  ].filter(Boolean);
  return (
    <section data-testid="flood-event-card" aria-label={eventText.title}>
      <h4>{eventText.title}</h4>
      <div className="enso-tabs" role="tablist" aria-label={eventText.eventsLabel} data-testid="event-picker">
        {data.events.map((e, i) => (
          <button
            key={e.peak_date}
            type="button"
            role="tab"
            aria-selected={i === ei}
            data-testid={`event-${e.peak_date}`}
            onClick={() => {
              setEventIdx(i);
              setIssueIdx(null);
            }}
          >
            {[formatDateEs(e.peak_date), `${fmtQ(e.peak_q)} ${eventText.unit}`].join(SEP)}
          </button>
        ))}
      </div>
      <label style={{ display: "block", fontSize: 13 }}>
        <span data-testid="event-issue-label">{issueLabel(issue.days_before_peak)}</span>
        <input
          type="range"
          data-testid="event-issue-slider"
          style={{ display: "block", width: "100%", margin: 0, minHeight: 44, accentColor: "var(--ctrl)" }}
          min={0}
          max={event.issues.length - 1}
          step={1}
          value={ii}
          aria-label={eventText.issueLabel}
          aria-valuetext={issueLabel(issue.days_before_peak)}
          onChange={(e) => setIssueIdx(Number(e.target.value))}
        />
      </label>
      <figure className="flood-figure">
        <EventChart event={event} issueIndex={ii} w={width} />
        <Legend />
        <figcaption>{[meta.source, yearsOf(meta.period)].join(" · ")}</figcaption>
        <figcaption>{modelLine.join(" · ")}</figcaption>
      </figure>
      <p className="flood-warn" data-testid="event-caveat">
        {meta.caveat}
      </p>
    </section>
  );
}

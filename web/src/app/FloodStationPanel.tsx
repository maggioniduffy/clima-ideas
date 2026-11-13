import type { FloodMaximum, FloodStationDetail } from "../api/client";
import { es } from "../i18n/es";
import type { FloodStationState } from "../layers/useFloodStation";
import { FloodEventCard } from "./FloodEventCard";
import { useWidth } from "./useWidth";
import {
  bandPath,
  CHART_MARGIN,
  dayOffset,
  downsampleMax,
  formatDateEs,
  linePath,
  linearScale,
  linearTicks,
  logScale,
  niceMax,
  RETURN_TICKS,
  tickAnchor,
  yearTicks,
  type Pt,
} from "./floodCharts";

const M = CHART_MARGIN;
const flowFmt = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });
const fmtQ = (q: number) => flowFmt.format(Math.round(q));
const yearsOf = (period: string) => period.split("/").map((d) => d.slice(0, 4)).join("–");

/** Chart size for a container width: text stays at its native size, the plot area grows with the panel. */
const chartSize = (w: number) => {
  const h = Math.round(Math.min(300, Math.max(170, w * 0.62)));
  return { W: w, H: h, HS: Math.round(h * 0.8) };
};

const topSet = (d: FloodStationDetail) => new Set(d.top_floods.map((m) => m.hydro_year));

/** T for the top list: GEV when the station has a fit, empirical otherwise. */
const periodOf = (m: FloodMaximum, d: FloodStationDetail) => (d.has_gev ? m.t_gev : m.t_empirical);

function tText(t: number | null): string {
  if (t == null) return "";
  if (t > 10_000) return es.flood.yearsOver;
  return es.flood.years(flowFmt.format(Math.round(t)));
}

function ReturnPeriodChart({ d, w }: { d: FloodStationDetail; w: number }) {
  const { W, H } = chartSize(w);
  const curve = d.curve ?? [];
  const tMax = RETURN_TICKS[RETURN_TICKS.length - 1];
  const tMin = curve.length ? curve[0]!.t : 1.1;
  const vals = [
    ...curve.map((c) => c.hi ?? c.q),
    ...d.annual_maxima.map((m) => m.q),
  ];
  const yMax = niceMax(Math.max(0, ...vals));
  const x = logScale(tMin, tMax, M.l, W - M.r);
  const y = linearScale(0, yMax, H - M.b, M.t);
  const inBand = curve.filter((c) => c.lo != null && c.hi != null);
  const top = topSet(d);
  const dots = d.annual_maxima.filter((m) => m.t_empirical != null && m.t_empirical >= tMin);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="flood-chart"
      role="img"
      aria-label={es.flood.chartLabel}
      data-testid="return-period-chart"
    >
      {linearTicks(yMax, 4).map((v) => (
        <g key={v}>
          <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} className="flood-grid" />
          <text x={M.l - 6} y={y(v) + 4} textAnchor="end" className="flood-tick">
            {fmtQ(v)}
          </text>
        </g>
      ))}
      {RETURN_TICKS.map((t) => (
        <text
          key={t}
          x={x(t)}
          y={H - M.b + 15}
          textAnchor={tickAnchor(x(t), W, String(t))}
          className="flood-tick"
        >
          {t}
        </text>
      ))}
      <text x={(M.l + W - M.r) / 2} y={H - 3} textAnchor="middle" className="flood-axis">
        {es.flood.axisT}
      </text>
      <text x={4} y={12} className="flood-axis">
        {es.flood.axisQ}
      </text>
      {inBand.length > 1 && (
        <path
          d={bandPath(
            inBand.map((c): Pt => ({ x: x(c.t), y: y(c.hi!) })),
            inBand.map((c): Pt => ({ x: x(c.t), y: y(c.lo!) })),
          )}
          className="flood-band"
          data-testid="return-period-band"
        />
      )}
      {curve.length > 1 && (
        <path
          d={linePath(curve.map((c) => ({ x: x(c.t), y: y(c.q) })))}
          className="flood-curve"
          data-testid="return-period-curve"
        />
      )}
      {dots.map((m) => (
        <circle
          key={m.hydro_year}
          cx={x(m.t_empirical!)}
          cy={y(m.q)}
          r={top.has(m.hydro_year) ? 3 : 2}
          className={top.has(m.hydro_year) ? "flood-dot flood-dot-top" : "flood-dot"}
        />
      ))}
    </svg>
  );
}

function SeriesChart({ d, w }: { d: FloodStationDetail; w: number }) {
  const { W, HS } = chartSize(w);
  const { start, q } = d.daily;
  const last = q.length - 1;
  const end = d.period.split("/")[1]!;
  const buckets = downsampleMax(q);
  const yMax = niceMax(Math.max(0, ...q.map((v) => v ?? 0)));
  const x = linearScale(0, Math.max(last, 1), M.l, W - M.r);
  const y = linearScale(0, yMax, HS - M.b, M.t);
  const path = linePath(buckets.map((b) => (b.value == null ? null : { x: x(b.index), y: y(b.value) })));
  const top = topSet(d);
  return (
    <svg
      viewBox={`0 0 ${W} ${HS}`}
      className="flood-chart"
      role="img"
      aria-label={es.flood.seriesLabel}
      data-testid="flow-series-chart"
    >
      {linearTicks(yMax, 2).map((v) => (
        <g key={v}>
          <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} className="flood-grid" />
          <text x={M.l - 6} y={y(v) + 4} textAnchor="end" className="flood-tick">
            {fmtQ(v)}
          </text>
        </g>
      ))}
      {yearTicks(start, end).map((k) => (
        <text
          key={k.year}
          x={x(dayOffset(start, k.iso))}
          y={HS - M.b + 15}
          textAnchor={tickAnchor(x(dayOffset(start, k.iso)), W, String(k.year))}
          className="flood-tick"
        >
          {k.year}
        </text>
      ))}
      <path d={path} className="flood-series" />
      {d.annual_maxima.map((m) => (
        <circle
          key={m.hydro_year}
          cx={x(dayOffset(start, m.date))}
          cy={y(m.q)}
          r={top.has(m.hydro_year) ? 3 : 2}
          className={top.has(m.hydro_year) ? "flood-dot flood-dot-top" : "flood-dot"}
        />
      ))}
    </svg>
  );
}

export function FloodStationPanel({
  state,
  onOpenArEvent,
}: {
  state: FloodStationState;
  /** Opens an AR event in the ar-events layer; without it the tags are not shown. */
  onOpenArEvent?: (id: string) => void;
}) {
  const { status, detail: d } = state;
  const [ref, w] = useWidth();
  if (status === "loading") return <p className="empty">{es.flood.loading}</p>;
  if (status === "error") return <p className="empty">{es.flood.error}</p>;
  if (!d) return null;
  return (
    <div className="flood-panel" data-testid="flood-station-panel" ref={ref}>
      <h3 className="event-id">
        {d.name}
        <span className="flood-river">{d.river}</span>
      </h3>
      <h4>{es.flood.returnTitle}</h4>
      <figure className="flood-figure">
        <ReturnPeriodChart d={d} w={w} />
        <figcaption>
          {[d.source, yearsOf(d.period), d.has_gev && es.flood.ci].filter(Boolean).join(es.events.sep)}
        </figcaption>
        {d.gev?.irregular && (
          <p className="flood-warn" data-testid="flood-irregular">
            {es.flood.irregular}
          </p>
        )}
        {!d.has_gev && (
          <p className="flood-warn" data-testid="flood-no-gev">
            {es.flood.noGev}
          </p>
        )}
      </figure>
      <h4>{es.flood.seriesTitle}</h4>
      <figure className="flood-figure">
        <SeriesChart d={d} w={w} />
      </figure>
      <h4>{es.flood.topTitle}</h4>
      <ol className="flood-top" data-testid="top-floods">
        {d.top_floods.map((m) => (
          <li key={m.hydro_year}>
            <span>{formatDateEs(m.date)}</span>
            <span>
              {fmtQ(m.q)} {es.flood.unit}
            </span>
            <span>{tText(periodOf(m, d))}</span>
            {onOpenArEvent &&
              (m.ar_events ?? []).map((id) => (
                <button
                  key={id}
                  type="button"
                  className="flood-ar-tag"
                  data-testid={`flood-ar-tag-${id}`}
                  aria-label={es.flood.coincidesLabel(id)}
                  onClick={() => onOpenArEvent(id)}
                >
                  {es.flood.coincides(id)}
                </button>
              ))}
          </li>
        ))}
      </ol>
      {(d as FloodStationDetail & { has_events?: boolean }).has_events && <FloodEventCard key={d.id} stationId={d.id} width={w} />}
    </div>
  );
}

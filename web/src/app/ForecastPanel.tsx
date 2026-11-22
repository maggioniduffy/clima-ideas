import { useState } from "react";
import { es } from "../i18n/es";
import type { Outlook, OutlookLead, OutlookRegion } from "../layers/forecast";
import { fmt0, fmt2, NO_DATA } from "../layers/hindcast";
import type { ForecastState } from "../layers/useForecastOutlook";
import { formatDateEs } from "./floodCharts";

export interface ForecastPanelProps {
  state: ForecastState;
  /** Layer manifest values. */
  source: string;
  period: string;
  license?: string;
  /** Optional `outlook_status` of the manifest. */
  outlookStatus?: string;
}

const pct = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return NO_DATA;
  const x = v * 100;
  return `${x.toLocaleString("es-AR", { minimumFractionDigits: x < 10 ? 1 : 0, maximumFractionDigits: x < 10 ? 1 : 0 })} %`;
};
const interval = (lo: number | null | undefined, hi: number | null | undefined, f: (v: number | null) => string) =>
  lo == null || hi == null ? NO_DATA : es.forecast.range(f(lo), f(hi));
const slug = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
const fmt2s = (v: number | null) => (v == null ? NO_DATA : v.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

function Notices({ o }: { o: Outlook }) {
  return (
    <section className="fc-notices flood-warn" data-testid="forecast-notices" aria-label={es.forecast.noticesLabel}>
      <p data-testid="forecast-official">{o.notices.official}</p>
      <p>
        <span>{es.forecast.officialLinks}{es.forecast.colon}</span>
        {o.official_links.map((l, i) => (
          <span key={l.url}>
            {i > 0 && es.events.sep}
            <a href={l.url} target="_blank" rel="noopener noreferrer" data-testid={`forecast-link-${slug(l.label)}`}>
              {l.label}
            </a>
          </span>
        ))}
        {es.hindcast.stop}
      </p>
      <p data-testid="forecast-audience">{o.notices.audience}</p>
    </section>
  );
}

function HistoryCell({ l }: { l: OutlookLead }) {
  const h = l.history;
  if (!h) return <>{NO_DATA}</>;
  if (h.insufficient) return <>{es.forecast.insufficient(fmt0(h.n))}</>;
  const t = es.forecast.historyLine;
  const parts = [
    `${t.n} ${fmt0(h.n)}`,
    `${t.events} ${fmt0(h.n_events)}`,
    `${t.skill} ${h.skill == null ? NO_DATA : `${fmt2(h.skill)} [${interval(h.ci?.[0], h.ci?.[1], fmt2s)}]`}`,
    `${t.pod} ${pct(h.pod)}`,
    `${t.far} ${pct(h.far)}`,
  ];
  return <>{parts.join(es.forecast.sep)}</>;
}

// Above the probability cap (F5.8, plan/06-forecast.md) no value is shown, interval ends included.
const capped = (cap: number | null) => (v: number | null) =>
  v != null && cap != null && v > cap ? es.forecast.above(pct(cap)) : pct(v);

function LeadRow({ l }: { l: OutlookLead }) {
  const hc = l.hindcast;
  return (
    <tr data-testid={`forecast-row-${l.lead}`} data-lead={l.lead}>
      <th scope="row" className="fc-left">
        <span className="num">{es.forecast.leadCell(l.lead)}</span>
        <span className="num fc-sub">{formatDateEs(l.valid_date)}</span>
      </th>
      <td className="num" data-testid={`forecast-p-${l.lead}`}>
        {l.above_cap ? es.forecast.above(pct(l.prob_cap)) : pct(l.p_shown)}
      </td>
      <td className="num" data-testid={`forecast-interval-${l.lead}`}>{interval(l.p_low, l.p_high, capped(l.prob_cap))}</td>
      <td className="num">
        {pct(l.clim_p)}
        <span className="fc-sub">{interval(l.clim_low, l.clim_high, pct)}</span>
      </td>
      <td className="fc-left" data-testid={`forecast-estado-${l.lead}`}>
        {l.estado}
      </td>
      <td className="fc-left" data-testid={`forecast-hindcast-${l.lead}`}>
        {hc ? (
          <>
            <span className="num">
              {es.forecast.bssCi(fmt2s(hc.bss_clim), interval(hc.ci?.[0], hc.ci?.[1], fmt2s))}
            </span>
            {hc.verdict && <span className="fc-sub">{hc.verdict}</span>}
          </>
        ) : (
          NO_DATA
        )}
      </td>
      <td className="fc-left num" data-testid={`forecast-history-${l.lead}`}>
        <HistoryCell l={l} />
      </td>
    </tr>
  );
}

function RegionTable({ r, level }: { r: OutlookRegion; level: number }) {
  return (
    <div className="hind-table-wrap" data-testid="forecast-table-wrap" tabIndex={0} role="region" aria-label={es.forecast.tableLabel(r.label)}>
      <table className="debris-table hind-table fc-table" data-testid="forecast-table">
        <caption className="sr-only">{es.forecast.tableLabel(r.label)}</caption>
        <thead>
          <tr>
            <th scope="col" className="fc-left">{es.forecast.head.lead}</th>
            <th scope="col">{es.forecast.head.prob}</th>
            <th scope="col">{es.forecast.head.interval(Math.round(level * 100))}</th>
            <th scope="col">{es.forecast.head.clim}</th>
            <th scope="col" className="fc-left">{es.forecast.head.estado}</th>
            <th scope="col" className="fc-left">{es.forecast.head.hindcast}</th>
            <th scope="col" className="fc-left">{es.forecast.head.history}</th>
          </tr>
        </thead>
        <tbody>
          {r.leads.map((l) => (
            <LeadRow key={l.lead} l={l} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Loaded({ o, source, period, license, outlookStatus }: { o: Outlook; source: string; period: string; license?: string; outlookStatus?: string }) {
  const [regionId, setRegionId] = useState(o.regions[0]?.id ?? "");
  const r = o.regions.find((x) => x.id === regionId) ?? o.regions[0];
  const level = r?.leads[0]?.interval_level ?? 0.9;
  return (
    <div className="conv-panel hind-panel fc-panel" data-testid="forecast-panel" data-region={r?.id} data-status={outlookStatus}>
      <Notices o={o} />
      <h3 className="fc-title" data-testid="forecast-variable">
        {o.variable_label}
      </h3>
      <dl className="kv" data-testid="forecast-header">
        <dt>{es.forecast.issued}</dt>
        <dd className="num" data-testid="forecast-issued">{formatDateEs(o.issue_date)}</dd>
        <dt>{es.forecast.gefsInit}</dt>
        <dd className="num" data-testid="forecast-gefs">{formatDateEs(o.gefs_init_date)}</dd>
        <dt>{es.forecast.model}</dt>
        <dd data-testid="forecast-model">{o.model.name} {o.model.version}</dd>
        <dt>{es.forecast.training}</dt>
        <dd className="num" data-testid="forecast-training">{o.model.training_period}</dd>
        <dt>{es.forecast.baseline}</dt>
        <dd data-testid="forecast-baseline">{o.model.baseline}</dd>
        <dt className="kv-wide">{es.forecast.inputs}</dt>
        <dd className="kv-wide fc-inputs" data-testid="forecast-inputs">
          <ul>
            {o.inputs.map((i) => (
              <li key={i.name}>{es.forecast.inputLine(i.name, es.forecast.latency(i.latency_hours))}</li>
            ))}
          </ul>
        </dd>
      </dl>
      <p className="conv-note" data-testid="forecast-source">
        {es.forecast.sourceLine(source, period, license ?? NO_DATA)}
      </p>
      {o.regions.length > 1 && (
        <div className="conv-seg" role="group" aria-label={es.forecast.regionLabel}>
          {o.regions.map((x) => (
            <button key={x.id} type="button" data-testid={`forecast-region-${x.id}`} aria-pressed={r?.id === x.id} onClick={() => setRegionId(x.id)}>
              {x.label}
            </button>
          ))}
        </div>
      )}
      {r ? (
        <section className="hind-section" aria-labelledby="forecast-region-title">
          <h4 id="forecast-region-title">
            {r.label}
            {r.threshold_mm != null && <span className="fc-sub"> {es.forecast.threshold(r.threshold_mm)}</span>}
          </h4>
          <RegionTable r={r} level={level} />
        </section>
      ) : (
        <p className="empty">{es.forecast.noData}</p>
      )}
      <section className="hind-section" aria-labelledby="forecast-states-title">
        <h4 id="forecast-states-title">{es.forecast.statesTitle}</h4>
        <dl className="kv fc-states" data-testid="forecast-states">
          {Object.entries(o.notices.states).map(([k, v]) => (
            <div key={k} data-testid={`forecast-state-${slug(k)}`}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </section>
      <p className="conv-note" data-testid="forecast-cap-rule">
        {o.cap_rule}
      </p>
      <p className="conv-note" data-testid="forecast-history-note">
        {o.history_note}
      </p>
    </div>
  );
}

/**
 * Detail-card content of the `forecast-outlook` layer (F6.6): per-region table by lead with the probability next to the
 * climatological one, its interval, the state as plain text, hindcast skill and prospective history. Always shows the
 * official-warning notice and links at the top. No levels, no colour by probability or state, no advice.
 */
export function ForecastPanel({ state, source, period, license, outlookStatus }: ForecastPanelProps) {
  const { status, outlook } = state;
  if (status === "loading" || status === "idle") return <p className="empty">{es.forecast.loading}</p>;
  if (status === "error" || !outlook) return <p className="empty">{es.forecast.error}</p>;
  return <Loaded o={outlook} source={source} period={period} license={license} outlookStatus={outlookStatus} />;
}

import { useState } from "react";
import { es } from "../i18n/es";
import {
  fmt0,
  fmt1,
  fmt2,
  fmtInterval2,
  fmtPct,
  fmtSigned1,
  NO_DATA,
  type AnalogEvent,
  type GateRow,
  type HindcastCases,
  type HindcastEvent,
  type HindcastSkill,
  type ModelSkill,
  type AnalogsData,
  type PodFar,
} from "../layers/hindcast";
import type { HindcastState } from "../layers/useHindcast";
import { CHART_MARGIN, formatDateEs } from "./floodCharts";
import {
  bandBetween,
  forecastDomain,
  linePath,
  makeScales,
  seriesPoints,
  skillByLead,
  skillDomain,
} from "./hindcastCharts";
import { OFFICIAL_LINKS } from "./officialLinks";
import { useWidth } from "./useWidth";

const M = { ...CHART_MARGIN, r: 14 };
const chartHeight = (w: number) => Math.round(Math.min(200, Math.max(140, w * 0.36)));
const REGION_ORDER = ["cordillera_norte", "cordillera_sur", "confluencia"] as const;

export { OFFICIAL_LINKS };

function ForecastChart({ ev, leads, lead, w, members }: { ev: HindcastEvent; leads: number[]; lead: number; w: number; members: number }) {
  const H = chartHeight(w);
  const dom = forecastDomain(ev);
  const s = makeScales(leads, dom, w, H, M);
  const mean = seriesPoints(leads, ev.mean, s);
  const obsY = s.y(ev.obs_mm);
  const li = leads.indexOf(lead);
  const at = li >= 0 ? mean[li] : null;
  return (
    <svg viewBox={`0 0 ${w} ${H}`} className="flood-chart" role="img" aria-label={es.hindcast.forecastChart} data-testid="hindcast-forecast-chart">
      {dom.ticks.map((v) => (
        <g key={v}>
          <line x1={M.l} x2={w - M.r} y1={s.y(v)} y2={s.y(v)} className="flood-grid" />
          <text x={M.l - 6} y={s.y(v) + 4} textAnchor="end" className="flood-tick">
            {fmt0(v)}
          </text>
        </g>
      ))}
      {leads.map((l) => (
        <text key={l} x={s.x(l)} y={H - M.b + 15} textAnchor="middle" className="flood-tick">
          {l}
        </text>
      ))}
      <text x={(M.l + w - M.r) / 2} y={H - 3} textAnchor="middle" className="flood-axis">
        {es.hindcast.axisLead}
      </text>
      <text x={4} y={12} className="flood-axis">
        {es.hindcast.axisMm}
      </text>
      {members > 1 && <path d={bandBetween(leads, ev.min, ev.max, s)} className="flood-band" data-testid="hindcast-forecast-band" />}
      <line x1={M.l} x2={w - M.r} y1={obsY} y2={obsY} className="hind-obs" data-testid="hindcast-obs-line" data-value={ev.obs_mm} />
      <path d={linePath(mean)} className="hind-line" data-testid="hindcast-forecast-line" />
      {at && (
        <g data-testid="hindcast-forecast-marker" data-lead={lead}>
          <line x1={at.x} x2={at.x} y1={M.t} y2={H - M.b} className="hind-cursor" />
          <circle cx={at.x} cy={at.y} r={5} className="hind-dot" />
        </g>
      )}
    </svg>
  );
}

function SkillChart({ skill, leads, lead, w }: { skill: ModelSkill; leads: number[]; lead: number; w: number }) {
  const H = chartHeight(w);
  const dom = skillDomain(skill.crpss);
  const s = makeScales(leads, dom, w, H, M);
  const value = skillByLead(skill.crpss, leads, "value");
  const pts = seriesPoints(leads, value, s);
  const li = leads.indexOf(lead);
  const at = li >= 0 ? pts[li] : null;
  return (
    <svg viewBox={`0 0 ${w} ${H}`} className="flood-chart" role="img" aria-label={es.hindcast.skillChart} data-testid="hindcast-skill-chart">
      {dom.ticks.map((v) => (
        <g key={v}>
          <line x1={M.l} x2={w - M.r} y1={s.y(v)} y2={s.y(v)} className={v === 0 ? "hind-zero" : "flood-grid"} />
          <text x={M.l - 6} y={s.y(v) + 4} textAnchor="end" className="flood-tick">
            {fmt1(v)}
          </text>
        </g>
      ))}
      {leads.map((l) => (
        <text key={l} x={s.x(l)} y={H - M.b + 15} textAnchor="middle" className="flood-tick">
          {l}
        </text>
      ))}
      <text x={(M.l + w - M.r) / 2} y={H - 3} textAnchor="middle" className="flood-axis">
        {es.hindcast.axisLead}
      </text>
      <text x={4} y={12} className="flood-axis">
        {es.hindcast.axisCrpss}
      </text>
      <path d={bandBetween(leads, skillByLead(skill.crpss, leads, "lo"), skillByLead(skill.crpss, leads, "hi"), s)} className="flood-band" data-testid="hindcast-skill-band" />
      <path d={linePath(pts)} className="hind-line" data-testid="hindcast-skill-line" />
      {at && (
        <g data-testid="hindcast-skill-marker" data-lead={lead}>
          <line x1={at.x} x2={at.x} y1={M.t} y2={H - M.b} className="hind-cursor" />
          <circle cx={at.x} cy={at.y} r={5} className="hind-dot" />
        </g>
      )}
    </svg>
  );
}

const podFar = (p: PodFar | undefined): string => (p ? `${fmtPct(p.pod)} / ${fmtPct(p.far)}` : NO_DATA);

function GateTable({ skill, lead }: { skill: HindcastSkill; lead: number }) {
  const gate = skill.gate;
  const rows = REGION_ORDER.map((r) => ({ region: r, row: gate.regions[r]?.find((x) => x.lead === lead) as GateRow | undefined }));
  return (
    <div className="hind-table-wrap">
      <table className="debris-table hind-table" data-testid="hindcast-gate-table" data-lead={lead} aria-label={es.hindcast.gateLabel(lead)}>
        <caption className="sr-only">{es.hindcast.gateLabel(lead)}</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="sr-only">{es.hindcast.gateTitle}</span>
            </th>
            {rows.map(({ region }) => (
              <th key={region} scope="col">
                {es.hindcast.gateRegions[region]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(
            [
              ["bssClim", (r: GateRow) => fmtInterval2(r.bss_log_clim)],
              ["bssMarkov", (r: GateRow) => fmtInterval2(r.bss_log_markov)],
              ["podFar05", (r: GateRow) => podFar(r.pod_far["p>=0.5"])],
              ["podFar2", (r: GateRow) => podFar(r.pod_far["p>=2base"])],
              ["cap", (r: GateRow) => fmtPct(r.prob_cap)],
              ["events", (r: GateRow) => `${fmt0(r.n_events)} / ${fmt0(r.n_events_pooled)}`],
              ["status", (r: GateRow) => r.status],
            ] as const
          ).map(([key, fmt]) => (
            <tr key={key}>
              <th scope="row">{es.hindcast.gateRows[key]}</th>
              {rows.map(({ region, row }) => (
                <td key={region} className={key === "status" ? "hind-status" : "num"} data-testid={`hindcast-gate-${key}-${region}`}>
                  {row ? fmt(row) : NO_DATA}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const rainTriplet = (day: AnalogEvent["analogs"][number], src: "era5" | "imerg", regions: readonly string[]) =>
  regions.map((r) => fmt1(day.rain?.[r]?.[src])).join(" / ");

function AnalogsSection({ analogs, event }: { analogs: AnalogsData; event: HindcastEvent }) {
  const ev = analogs.events.find((e) => e.event_id === event.event_id);
  if (!ev || ev.analogs.length === 0) return null;
  const regions = analogs.regions && analogs.regions.length > 0 ? analogs.regions : REGION_ORDER;
  const shown = ev.analogs.slice(0, 10);
  const a = ev.analog_summary?.ar_fraction;
  const b = ev.baseline?.ar_fraction;
  const k = shown.length;
  const note =
    a != null && b != null
      ? es.hindcast.analogsNote(k, `${fmt0(a * k)} de ${k}`, `${fmt0(b * k)} de ${k}`)
      : null;
  return (
    <section className="hind-section" data-testid="hindcast-analogs" aria-labelledby="hindcast-analogs-title">
      <h4 id="hindcast-analogs-title">{es.hindcast.analogsTitle}</h4>
      {note && (
        <p className="conv-note" data-testid="hindcast-analogs-note">
          {note}
        </p>
      )}
      <div className="hind-table-wrap">
        <table className="debris-table hind-table" data-testid="hindcast-analogs-table">
          <thead>
            <tr>
              <th scope="col">{es.hindcast.analogsHead.date}</th>
              <th scope="col">{es.hindcast.analogsHead.dist}</th>
              <th scope="col">{es.hindcast.analogsHead.ar}</th>
              <th scope="col">{es.hindcast.analogsHead.ivt}</th>
              <th scope="col">{es.hindcast.analogsHead.era5}</th>
              <th scope="col">{es.hindcast.analogsHead.imerg}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((d, i) => (
              <tr key={`${d.date}-${i}`} data-testid={`hindcast-analog-${i}`}>
                <th scope="row" className="num">
                  {formatDateEs(d.date)}
                </th>
                <td className="num">{fmt2(d.distance)}</td>
                <td data-testid={`hindcast-analog-ar-${i}`}>{d.ar_event_id ? `${es.hindcast.yes} (${d.ar_event_id})` : es.hindcast.no}</td>
                <td className="num">{fmt0(d.ivt_max)}</td>
                <td className="num">{rainTriplet(d, "era5", regions)}</td>
                <td className="num">{rainTriplet(d, "imerg", regions)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="conv-note">{es.hindcast.analogsRainNote}</p>
    </section>
  );
}

export interface HindcastPanelProps {
  state: HindcastState;
  /** Layer manifest values: source, period and license of the data shown. */
  source: string;
  period: string;
  license?: string;
}

function Loaded({ cases, skill, analogs, source, period, license }: { cases: HindcastCases; skill: HindcastSkill; analogs: AnalogsData | null; source: string; period: string; license?: string }) {
  const modelIds = Object.keys(cases.models);
  const [model, setModel] = useState(modelIds[0]!);
  const [eventId, setEventId] = useState<string | null>(null);
  const [lead, setLead] = useState(cases.leads[0] ?? 1);
  const [fcRef, fcW] = useWidth();
  const mc = cases.models[model] ?? cases.models[modelIds[0]!]!;
  const ev = mc.events.find((e) => e.event_id === eventId) ?? mc.events[0];
  const ms = skill.models[model];
  const li = cases.leads.indexOf(lead);
  const mean = ev?.mean[li] ?? null;
  const lo = ev?.min[li] ?? null;
  const hi = ev?.max[li] ?? null;
  const crpss = ms?.crpss.find((p) => p.lead === lead);
  const bias = ms?.bias.find((p) => p.lead === lead);
  const n = ms?.n.find((p) => p.lead === lead)?.n;
  const aifs = skill.aifs_vs_ifs;
  return (
    <div className="conv-panel hind-panel" data-testid="hindcast-panel" data-model={model} data-event={ev?.event_id} data-lead={lead}>
      <p className="hind-tag" data-testid="hindcast-retro">
        <strong>{es.hindcast.tag}</strong>{es.hindcast.stop} {es.hindcast.intro}
      </p>
      <p className="flood-warn" data-testid="hindcast-not-alert">
        {es.hindcast.notAlert} {es.hindcast.officialLead}{" "}
        {OFFICIAL_LINKS.map((l, i) => (
          <span key={l.id}>
            {i > 0 && es.events.sep}
            <a href={l.href} target="_blank" rel="noopener noreferrer" data-testid={`hindcast-link-${l.id}`}>
              {es.hindcast.links[l.id]}
            </a>
          </span>
        ))}
        {es.hindcast.stop}
      </p>
      <p className="conv-note" data-testid="hindcast-source">
        {[source, es.hindcast.periodLabel(period)].join(es.events.sep)}
      </p>
      <div className="conv-col" ref={fcRef}>
        <div className="conv-seg" role="group" aria-label={es.hindcast.modelLabel}>
          {modelIds.map((id) => (
            <button key={id} type="button" data-testid={`hindcast-model-${id}`} aria-pressed={model === id} onClick={() => setModel(id)}>
              {cases.models[id]!.label}
            </button>
          ))}
        </div>
        <label className="hind-field">
          <span>
            {es.hindcast.eventLabel} <span className="num">{es.hindcast.eventsCount(mc.events.length)}</span>
          </span>
          <select data-testid="hindcast-event" className="hind-select" value={ev?.event_id ?? ""} onChange={(e) => setEventId(e.target.value)}>
            {mc.events.map((e) => (
              <option key={e.event_id} value={e.event_id}>
                {es.hindcast.eventOption(formatDateEs(e.date), e.event_id)}
              </option>
            ))}
          </select>
        </label>
        <div className="conv-seg" role="group" aria-label={es.hindcast.leadLabel}>
          {cases.leads.map((l) => (
            <button key={l} type="button" data-testid={`hindcast-lead-${l}`} aria-pressed={lead === l} aria-label={es.hindcast.leadTitle(l)} onClick={() => setLead(l)}>
              {l}
            </button>
          ))}
        </div>
        {ev && (
          <section className="hind-section" aria-labelledby="hindcast-forecast-title">
            <h4 id="hindcast-forecast-title">{es.hindcast.forecastTitle}</h4>
            <dl className="kv" data-testid="hindcast-readout">
              <dt>{es.hindcast.readValid}</dt>
              <dd className="num" data-testid="hindcast-valid">
                {formatDateEs(ev.date)}
              </dd>
              <dt>{es.hindcast.readFc}</dt>
              <dd className="num" data-testid="hindcast-fc-mean">
                {mean == null ? es.hindcast.noForecast : `${fmt1(mean)} ${es.hindcast.mm}`}
              </dd>
              <dt>{es.hindcast.readRange}</dt>
              <dd className="num" data-testid="hindcast-fc-range">
                {mean == null ? NO_DATA : mc.n_members > 1 ? `${fmt1(lo)} a ${fmt1(hi)} ${es.hindcast.mm}` : es.hindcast.singleMember}
              </dd>
              <dt>{es.hindcast.readObs}</dt>
              <dd className="num" data-testid="hindcast-obs">
                {fmt1(ev.obs_mm)} {es.hindcast.mm}
              </dd>
              <dt>{es.hindcast.readDiff}</dt>
              <dd className="num" data-testid="hindcast-diff">
                {mean == null ? NO_DATA : `${fmtSigned1(mean - ev.obs_mm)} ${es.hindcast.mm}`}
              </dd>
            </dl>
            <figure className="flood-figure">
              <ForecastChart ev={ev} leads={cases.leads} lead={lead} w={fcW} members={mc.n_members} />
              <figcaption>{es.hindcast.forecastLegend}</figcaption>
            </figure>
          </section>
        )}
        {ms && (
          <section className="hind-section" aria-labelledby="hindcast-skill-title">
            <h4 id="hindcast-skill-title">{es.hindcast.skillTitle}</h4>
            <dl className="kv" data-testid="hindcast-skill-readout">
              <dt>{es.hindcast.readCrpss}</dt>
              <dd className="num" data-testid="hindcast-skill-crpss">
                {fmtInterval2(crpss)}
              </dd>
              <dt>{es.hindcast.readBias}</dt>
              <dd className="num" data-testid="hindcast-skill-bias">
                {bias ? `${fmtSigned1(bias.value)} (${fmtSigned1(bias.lo)} a ${fmtSigned1(bias.hi)}) ${es.hindcast.mm}` : NO_DATA}
              </dd>
              <dt>{es.hindcast.readN}</dt>
              <dd className="num" data-testid="hindcast-skill-n">
                {fmt0(n)}
              </dd>
            </dl>
            <figure className="flood-figure">
              <SkillChart skill={ms} leads={cases.leads} lead={lead} w={fcW} />
              <figcaption>{es.hindcast.skillLegend}</figcaption>
            </figure>
          </section>
        )}
      </div>
      <section className="hind-section" aria-labelledby="hindcast-gate-title">
        <h4 id="hindcast-gate-title">{es.hindcast.gateTitle}</h4>
        <p className="conv-note" data-testid="hindcast-gate-note">
          {es.hindcast.gateNote(skill.gate.fc_source, skill.gate.fc_period, Math.round(skill.gate.quantile * 100))}
        </p>
        <GateTable skill={skill} lead={lead} />
      </section>
      {analogs && ev && <AnalogsSection analogs={analogs} event={ev} />}
      {aifs.rows.length > 0 && (
        <details className="conv-notes" data-testid="hindcast-aifs">
          <summary>{es.hindcast.aifsSummary}</summary>
          <p className="conv-note">{es.hindcast.aifsNote(aifs.n_event, formatDateEs(aifs.first), formatDateEs(aifs.last))}</p>
          <div className="hind-table-wrap">
            <table className="debris-table hind-table" data-testid="hindcast-aifs-table">
              <thead>
                <tr>
                  <th scope="col">{es.hindcast.aifsHead.lead}</th>
                  <th scope="col">{es.hindcast.aifsHead.n}</th>
                  <th scope="col">{es.hindcast.aifsHead.ifs}</th>
                  <th scope="col">{es.hindcast.aifsHead.aifs}</th>
                  <th scope="col">{es.hindcast.aifsHead.diff}</th>
                  <th scope="col">{es.hindcast.aifsHead.verdict}</th>
                </tr>
              </thead>
              <tbody>
                {aifs.rows.map((r) => (
                  <tr key={r.lead}>
                    <th scope="row" className="num">
                      {r.lead}
                    </th>
                    <td className="num">{fmt0(r.n)}</td>
                    <td className="num">{fmt1(r.mae_ifs)}</td>
                    <td className="num">{fmt1(r.mae_aifs)}</td>
                    <td className="num">{es.hindcast.diffCell(fmtSigned1(r.diff), fmtSigned1(r.lo), fmtSigned1(r.hi))}</td>
                    <td>{r.verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <p className="conv-note" data-testid="hindcast-license">
        {es.hindcast.licenseLine(license ?? cases.license, cases.obs_source)}
      </p>
    </div>
  );
}

/**
 * Detail-card content of the `hindcast-verification` layer (F5.6): pick a model, an F1.3 event and a lead to see the
 * forecast against ERA5, the model's skill curve, the evidence gate and the ERA5 analogs of the event (when published).
 * Retrospective only: no levels, thresholds or advice; the statuses of the gate are plain text.
 */
export function HindcastPanel({ state, source, period, license }: HindcastPanelProps) {
  const { status, cases, skill, analogs } = state;
  if (status === "loading" || status === "idle") return <p className="empty">{es.hindcast.loading}</p>;
  if (status === "error" || !cases || !skill || Object.keys(cases.models).length === 0) return <p className="empty">{es.hindcast.error}</p>;
  return <Loaded cases={cases} skill={skill} analogs={analogs} source={source} period={period} license={license} />;
}

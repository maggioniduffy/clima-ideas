import { Fragment, useState } from "react";
import { es } from "../i18n/es";
import type { Seasonal, SeasonalLead, SeasonalModel, SeasonalTarget } from "../layers/forecast";
import { NO_DATA } from "../layers/hindcast";
import { formatDateEs } from "./floodCharts";
import { fmt2s, interval, pct, phys } from "./forecastFormat";

const t = es.forecast.seasonal;

/** `2026-12` -> `dic 2026`. */
export const monthLabel = (ym: string): string => {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  const name = m ? t.months[Number(m[2]) - 1] : undefined;
  return m && name ? `${name} ${m[1]}` : ym;
};

const tercileText = (m: SeasonalModel) => {
  const p = m.p_terciles;
  if (!p) return NO_DATA;
  return `${pct(p.inferior)} / ${pct(p.medio)} / ${pct(p.superior)}`;
};

function ModelCells({ m, lead }: { m: SeasonalModel; lead: SeasonalLead }) {
  const id = `${lead.lead_months}-${m.name}`;
  if (!m.emitted) {
    return (
      <>
        <th scope="row" className="fc-left" data-testid={`seasonal-model-${id}`}>{m.label}</th>
        <td className="fc-left fc-sub-cell" colSpan={2} data-testid={`seasonal-reason-${id}`}>
          {t.notEmitted(m.reason ?? NO_DATA)}
        </td>
      </>
    );
  }
  const iv = m.p_superior_interval;
  return (
    <>
      <th scope="row" className="fc-left" data-testid={`seasonal-model-${id}`}>{m.label}</th>
      <td className="num fc-nowrap" data-testid={`seasonal-p-${id}`}>{tercileText(m)}</td>
      <td className="num fc-nowrap" data-testid={`seasonal-interval-${id}`}>
        {iv && iv[0] != null && iv[1] != null && iv[1] > iv[0] ? es.forecast.range(pct(iv[0]), pct(iv[1])) : NO_DATA}
      </td>
    </>
  );
}

function LeadCells({ lead, unit }: { lead: SeasonalLead; unit: string }) {
  const sk = lead.skill;
  const u = es.forecast.seasonal.unitNames[unit] ?? unit;
  return (
    <>
      <th scope="rowgroup" className="fc-left" rowSpan={lead.models.length} data-testid={`seasonal-month-${lead.lead_months}`}>
        <span className="num">{monthLabel(lead.target_month)}</span>
        <span className="num fc-sub">{t.lead(lead.lead_months)}</span>
      </th>
      <td className="fc-left" rowSpan={lead.models.length} data-testid={`seasonal-edges-${lead.lead_months}`}>
        {lead.edges ? t.edges(phys(lead.edges.lower_up_to), phys(lead.edges.upper_from), u) : NO_DATA}
      </td>
      <td className="fc-left" rowSpan={lead.models.length} data-testid={`seasonal-skill-${lead.lead_months}`}>
        {sk ? (
          <>
            <span className="num">{t.skill(fmt2s(sk.rpss_vs_clim), interval(sk.ci95?.[0], sk.ci95?.[1], fmt2s))}</span>
            <span className="fc-sub">{t.beats(sk.beats_climatology)}</span>
          </>
        ) : (
          NO_DATA
        )}
      </td>
    </>
  );
}

function TargetTable({ target }: { target: SeasonalTarget }) {
  const label = t.targets[target.id] ?? target.label;
  const level = Math.round((target.leads[0]?.models.find((m) => m.interval_level)?.interval_level ?? 0.9) * 100);
  return (
    <div className="hind-table-wrap" data-testid="seasonal-table-wrap" tabIndex={0} role="region" aria-label={t.tableLabel(label)}>
      <table className="debris-table hind-table fc-table fc-seasonal-table" data-testid="seasonal-table">
        <caption className="sr-only">{t.tableLabel(label)}</caption>
        <thead>
          <tr>
            <th scope="col" className="fc-left">{t.head.month}</th>
            <th scope="col" className="fc-left">{t.head.edges}</th>
            <th scope="col" className="fc-left">{t.head.skill}</th>
            <th scope="col" className="fc-left">{t.head.model}</th>
            <th scope="col">{t.head.terciles}</th>
            <th scope="col">{t.head.interval(level)}</th>
          </tr>
        </thead>
        {target.leads.map((lead) => (
          <tbody key={lead.lead_months} data-testid={`seasonal-lead-${lead.lead_months}`}>
            {lead.models.map((m, i) => (
              <tr key={m.name} data-model={m.name}>
                {i === 0 && <LeadCells lead={lead} unit={target.unit} />}
                <ModelCells m={m} lead={lead} />
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

/** Seasonal view (F6.2): terciles by target month and model, hindcast skill per lead. Neutral styling only. */
export function SeasonalView({ seasonal }: { seasonal: Seasonal | undefined }) {
  const [targetId, setTargetId] = useState<string | undefined>(undefined);
  if (!seasonal || !seasonal.available) {
    return (
      <section className="hind-section" data-testid="seasonal-unavailable">
        <h4>{t.title}</h4>
        <p className="conv-note" data-testid="seasonal-unavailable-note">{seasonal?.note ?? t.unavailable}</p>
      </section>
    );
  }
  const targets = seasonal.targets ?? [];
  const target = targets.find((x) => x.id === targetId) ?? targets[0];
  return (
    <div className="fc-view" data-testid="seasonal-view">
      <h3 className="fc-title">{seasonal.variable_label ?? t.title}</h3>
      <dl className="kv" data-testid="seasonal-header">
        <dt>{t.estado}</dt>
        <dd data-testid="seasonal-estado">{seasonal.estado ?? NO_DATA}</dd>
        <dt>{t.issued}</dt>
        <dd className="num" data-testid="seasonal-issued">{seasonal.issue_date ? formatDateEs(seasonal.issue_date) : NO_DATA}</dd>
        <dt>{t.model}</dt>
        <dd data-testid="seasonal-model">{seasonal.model_version ?? NO_DATA}</dd>
        <dt>{t.period}</dt>
        <dd className="num" data-testid="seasonal-period">{seasonal.period ?? NO_DATA}</dd>
        <dt className="kv-wide">{t.sources}</dt>
        <dd className="kv-wide" data-testid="seasonal-source">{seasonal.source ?? NO_DATA}</dd>
      </dl>
      {seasonal.notices && seasonal.notices.length > 0 && (
        <section className="fc-notices flood-warn" data-testid="seasonal-notices" aria-label={t.noticesTitle}>
          {seasonal.notices.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </section>
      )}
      {target ? (
        <Fragment>
          <div className="conv-seg" role="group" aria-label={t.targetLabel}>
            {targets.map((x) => (
              <button key={x.id} type="button" data-testid={`seasonal-target-${x.id}`} aria-pressed={target.id === x.id} onClick={() => setTargetId(x.id)}>
                {t.targets[x.id] ?? x.label}
              </button>
            ))}
          </div>
          <section className="hind-section" data-testid="seasonal-target" data-target={target.id} aria-label={t.targets[target.id] ?? target.label}>
            <TargetTable target={target} />
            {target.note && (
              <p className="conv-note" data-testid="seasonal-note">
                {target.note}
              </p>
            )}
          </section>
        </Fragment>
      ) : (
        <p className="empty">{t.noTargets}</p>
      )}
    </div>
  );
}

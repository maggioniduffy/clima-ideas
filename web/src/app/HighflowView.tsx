import { useState } from "react";
import { es } from "../i18n/es";
import type { Bss, BssVs, F67, F67Lead, F69, F69Threshold, Highflow } from "../layers/forecast";
import { fmt0, NO_DATA } from "../layers/hindcast";
import { fmt2s, withCi } from "./forecastFormat";

const t = es.forecast.highflow;

const bssText = (b: Bss | null | undefined) => (b ? withCi(b.bss, b.ci95) : NO_DATA);
const frac = (k: number | null, n: number | null, v: number | null, ci: readonly (number | null)[] | null) =>
  k == null || n == null ? NO_DATA : `${fmt0(k)}/${fmt0(n)} (${withCi(v, ci, (x) => (x == null ? NO_DATA : `${fmt0(x * 100)} %`))})`;
const modelName = (m: string) => t.modelName[m] ?? m.toUpperCase();
const sortedLeads = (o: Record<string, unknown>) => Object.keys(o).sort((a, b) => Number(a) - Number(b));

function Unavailable({ id }: { id: string }) {
  return (
    <p className="conv-note" data-testid={`${id}-unavailable`}>
      {t.unavailable}
    </p>
  );
}

function F67Row({ model, k, e }: { model: string; k: string; e: F67Lead }) {
  const cov = e.coverage_ci95;
  return (
    <tr data-testid={`f67-row-${model}-${k}`}>
      <th scope="row" className="fc-left num">{t.leadDays(Number(k))}</th>
      <td className="num">{fmt0(e.n_floods)}</td>
      <td className="num fc-nowrap" data-testid={`f67-rises-${model}-${k}`}>{frac(e.rises, e.n_floods, e.rises_frac, e.rises_ci95)}</td>
      <td className="num fc-nowrap" data-testid={`f67-coverage-${model}-${k}`}>
        {withCi(e.coverage, cov, (x) => (x == null ? NO_DATA : fmt2s(x)))}
        <span className="fc-sub">{t.nominal(fmt2s(e.coverage_nominal))}</span>
      </td>
      <td className="num fc-nowrap" data-testid={`f67-bss-${model}-${k}`}>{withCi(e.bss_clim, e.bss_clim_ci95)}</td>
      <td className="fc-left" data-testid={`f67-verdict-${model}-${k}`}>{e.verdict}</td>
    </tr>
  );
}

function F67Block({ f67 }: { f67: F67 | undefined }) {
  const [variant, setVariant] = useState<string | undefined>(undefined);
  if (!f67 || !f67.available) return <Unavailable id="f67" />;
  const variants = f67.variants ?? {};
  const keys = Object.keys(variants);
  const vk = variant && variants[variant] ? variant : keys[0];
  const v = vk ? variants[vk] : undefined;
  const yrs = f67.independent_years;
  return (
    <div className="fc-view" data-testid="f67-block">
      {f67.source && <p className="conv-note" data-testid="f67-source">{f67.source}</p>}
      {f67.period && <p className="conv-note num" data-testid="f67-period">{t.period}{es.forecast.colon}{f67.period}</p>}
      {yrs && (
        <p className="conv-note" data-testid="highflow-years">
          {t.years(fmt0(yrs.n), fmt0(yrs.required))}
          {f67.n_floods != null && `${es.forecast.sep}${t.floods(fmt0(f67.n_floods))}`}
        </p>
      )}
      {keys.length > 1 && (
        <div className="conv-seg" role="group" aria-label={t.variantLabel}>
          {keys.map((k) => (
            <button key={k} type="button" data-testid={`highflow-variant-${k}`} aria-pressed={vk === k} onClick={() => setVariant(k)}>
              {t.variants[k] ?? k}
            </button>
          ))}
        </div>
      )}
      {v && (
        <>
          <p className="conv-note" data-testid="highflow-threshold-rule">{v.threshold_rule}</p>
          {Object.entries(v.models).map(([m, leads]) => (
            <div key={m} className="hind-table-wrap" tabIndex={0} role="region" aria-label={t.modelTable(modelName(m), t.variants[vk!] ?? vk!)} data-testid={`f67-wrap-${m}`}>
              <table className="debris-table hind-table fc-table fc-hf-table" data-testid={`f67-table-${m}`}>
                <caption className="fc-cap">{t.modelTable(modelName(m), t.variants[vk!] ?? vk!)}</caption>
                <thead>
                  <tr>
                    <th scope="col" className="fc-left">{t.f67Head.lead}</th>
                    <th scope="col">{t.f67Head.floods}</th>
                    <th scope="col">{t.f67Head.rises}</th>
                    <th scope="col">{t.f67Head.coverage(90)}</th>
                    <th scope="col">{t.f67Head.bss}</th>
                    <th scope="col" className="fc-left">{t.f67Head.verdict}</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedLeads(leads).map((k) => (
                    <F67Row key={k} model={m} k={k} e={leads[k]!} />
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}
      {f67.report_note && <p className="conv-note">{f67.report_note}</p>}
    </div>
  );
}

function Era5Table({ thr, stations }: { thr: F69Threshold; stations: F69["stations"] }) {
  const clim = thr.era5.vs_climatology;
  const pers = thr.era5.vs_persistence;
  const ids = Object.keys(clim.stations);
  const row = (id: string, label: string, c: Bss | null | undefined, p: Bss | null | undefined) => (
    <tr key={id} data-testid={`f69-era5-${id}`}>
      <th scope="row" className="fc-left">{label}</th>
      <td className="num">{fmt0(c?.n)}</td>
      <td className="num">{fmt0(c?.n_exceed)}</td>
      <td className="num fc-nowrap">{bssText(c)}</td>
      <td className="num fc-nowrap">{bssText(p)}</td>
    </tr>
  );
  return (
    <div className="hind-table-wrap" tabIndex={0} role="region" aria-label={t.era5Table} data-testid="f69-era5-wrap">
      <table className="debris-table hind-table fc-table fc-hf-table" data-testid="f69-era5-table">
        <caption className="sr-only">{t.era5Table}</caption>
        <thead>
          <tr>
            <th scope="col" className="fc-left">{t.f69Head.scope}</th>
            <th scope="col">{t.f69Head.n}</th>
            <th scope="col">{t.f69Head.exceed}</th>
            <th scope="col">{t.f69Head.clim}</th>
            <th scope="col">{t.f69Head.pers}</th>
          </tr>
        </thead>
        <tbody>
          {row("pooled", t.pooled, clim.pooled, pers.pooled)}
          {ids.map((id) => {
            const nm = stations?.[id]?.name;
            const thv = thr.threshold_m3s[id];
            return row(id, `${id}${nm ? ` ${nm}` : ""}${thv != null ? `${es.forecast.sep}${t.thresholdValue(id, fmt0(thv))}` : ""}`, clim.stations[id], pers.stations[id]);
          })}
        </tbody>
      </table>
    </div>
  );
}

function GefsTable({ by }: { by: Record<string, BssVs & { n_events: number | null }> }) {
  return (
    <div className="hind-table-wrap" tabIndex={0} role="region" aria-label={t.gefsTable} data-testid="f69-gefs-wrap">
      <table className="debris-table hind-table fc-table fc-hf-table" data-testid="f69-gefs-table">
        <caption className="sr-only">{t.gefsTable}</caption>
        <thead>
          <tr>
            <th scope="col" className="fc-left">{t.f69Head.lead}</th>
            <th scope="col">{t.f69Head.events}</th>
            <th scope="col">{t.f69Head.clim}</th>
            <th scope="col">{t.f69Head.pers}</th>
          </tr>
        </thead>
        <tbody>
          {sortedLeads(by).map((k) => {
            const e = by[k]!;
            return (
              <tr key={k} data-testid={`f69-gefs-${k}`}>
                <th scope="row" className="fc-left num">{t.leadDays(Number(k))}</th>
                <td className="num">{fmt0(e.n_events)}</td>
                <td className="num fc-nowrap">{bssText(e.vs_climatology?.pooled)}</td>
                <td className="num fc-nowrap">{bssText(e.vs_persistence?.pooled)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function F69Block({ f69 }: { f69: F69 | undefined }) {
  const [thrKey, setThrKey] = useState<string | undefined>(undefined);
  if (!f69 || !f69.available) return <Unavailable id="f69" />;
  const thresholds = f69.thresholds ?? {};
  const keys = Object.keys(thresholds);
  const tk = thrKey && thresholds[thrKey] ? thrKey : keys[0];
  const thr = tk ? thresholds[tk] : undefined;
  return (
    <div className="fc-view" data-testid="f69-block">
      {f69.source && <p className="conv-note" data-testid="f69-source">{f69.source}</p>}
      {f69.period && (
        <p className="conv-note num" data-testid="f69-period">
          {t.period}{es.forecast.colon}{f69.period}
          {f69.gefs_period && `${es.forecast.sep}${t.gefsPeriod}${es.forecast.colon}${f69.gefs_period}`}
          {f69.n_events != null && `${es.forecast.sep}${t.eventsAll(fmt0(f69.n_events))}`}
        </p>
      )}
      {keys.length > 1 && (
        <div className="conv-seg" role="group" aria-label={t.thresholdLabel}>
          {keys.map((k) => (
            <button key={k} type="button" data-testid={`highflow-threshold-${k}`} aria-pressed={tk === k} onClick={() => setThrKey(k)}>
              {t.thresholds[k] ?? k}
            </button>
          ))}
        </div>
      )}
      {thr && (
        <>
          <p className="conv-note">{thr.threshold_rule}</p>
          <h5 className="fc-h5">{t.era5Title}</h5>
          <Era5Table thr={thr} stations={f69.stations} />
          <h5 className="fc-h5">{t.gefsTitle}</h5>
          {Object.keys(thr.gefs_by_lead ?? {}).length > 0 ? <GefsTable by={thr.gefs_by_lead} /> : <Unavailable id="f69-gefs" />}
        </>
      )}
    </div>
  );
}

/** High-flow view (F6.7 / F6.9): retrospective test, not a forecast. Each block degrades to "sin datos". */
export function HighflowView({ highflow }: { highflow: Highflow | undefined }) {
  if (!highflow) {
    return (
      <section className="hind-section" data-testid="highflow-unavailable">
        <h4>{t.title}</h4>
        <p className="conv-note">{t.unavailable}</p>
      </section>
    );
  }
  return (
    <div className="fc-view" data-testid="highflow-view">
      <h3 className="fc-title">{t.title}</h3>
      <p className="fc-retro" data-testid="highflow-note">{t.retro}</p>
      <dl className="kv">
        <dt>{t.estado}</dt>
        <dd data-testid="highflow-estado">{highflow.estado ?? "Experimental"}</dd>
      </dl>
      <section className="hind-section" aria-labelledby="f67-title">
        <h4 id="f67-title">{t.f67Title}</h4>
        <F67Block f67={highflow.f67} />
      </section>
      <section className="hind-section" aria-labelledby="f69-title">
        <h4 id="f69-title">{t.f69Title}</h4>
        <F69Block f69={highflow.f69} />
      </section>
    </div>
  );
}

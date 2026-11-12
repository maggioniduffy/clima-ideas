import { useEffect, useState } from "react";
import type { EnsoMetric, EnsoPhase, EnsoStats } from "../api/client";
import { es } from "../i18n/es";
import { formatEnsoGroup, formatEnsoValue, formatPValue } from "./eventFormat";

const PHASES: EnsoPhase[] = ["nino", "neutral", "nina"];

interface Props {
  status: "loading" | "ready" | "error";
  stats: EnsoStats | null;
  /** Layer source and period (manifest), shown with the numbers. */
  source: string;
  period: string;
  onClose: () => void;
}

/** Content of the detail card with the F1.8 table: AR counts, IVT and rain share by ENSO phase, per season. */
export function EnsoPanel({ status, stats, source, period, onClose }: Props) {
  const rows = stats?.results.rows ?? [];
  const seasons = [...new Set(rows.map((r) => r.season))];
  const [picked, setPicked] = useState<string | null>(null);
  const season = picked && seasons.includes(picked) ? picked : (seasons[0] ?? null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const seasonRows = rows.filter((r) => r.season === season);
  const years = seasonRows[0]?.phase_years;
  const nBh = rows.filter((r) => r.sustained_bh).length;
  const yearsText = years
    ? `${es.enso.years}: ${PHASES.map((p) => `${es.enso[p]} ${years[p]}`).join(" · ")} (${es.enso.yearsUnit})`
    : "";
  const ensoPeriod = stats?.meta.season_years_period ?? stats?.meta.period ?? period;
  const sourceText = `${es.enso.source}: ${stats?.meta.source ?? source}. ${es.enso.period}: ${ensoPeriod}.`;

  return (
    <section className="enso-panel" id="enso-panel" data-testid="enso-panel" aria-label={es.enso.title}>
      <header className="enso-head">
        <h2>{es.enso.title}</h2>
        <button type="button" data-testid="enso-close" onClick={onClose}>
          {es.enso.close}
        </button>
      </header>
      {status === "loading" && <p className="empty">{es.enso.loading}</p>}
      {status === "error" && <p className="empty">{es.enso.error}</p>}
      {status === "ready" && stats && season && (
        <>
          <div className="enso-tabs" role="tablist" aria-label={es.enso.seasons}>
            {seasons.map((s) => (
              <button
                key={s}
                type="button"
                role="tab"
                data-testid={`enso-tab-${s}`}
                aria-selected={s === season}
                onClick={() => setPicked(s)}
              >
                {s}
              </button>
            ))}
          </div>
          {years && (
            <p className="enso-years" data-testid="enso-years">
              {yearsText}
            </p>
          )}
          <div className="enso-scroll">
            <table className="enso-table" data-testid="enso-table">
              <thead>
                <tr>
                  <th scope="col">{es.enso.metric}</th>
                  {PHASES.map((p) => (
                    <th key={p} scope="col">
                      {es.enso[p]} <span className="enso-sub">{es.enso.meanSd}</span>
                    </th>
                  ))}
                  <th scope="col">{es.enso.diff}</th>
                  <th scope="col">{es.enso.p}</th>
                  <th scope="col">{es.enso.pBh}</th>
                  <th scope="col">{es.enso.sustained}</th>
                </tr>
              </thead>
              <tbody>
                {seasonRows.map((r) => (
                  <tr key={r.metric} data-testid={`enso-row-${r.metric}`}>
                    <th scope="row">{es.enso.metrics[r.metric as EnsoMetric] ?? r.metric}</th>
                    {PHASES.map((p) => (
                      <td key={p}>{formatEnsoGroup(r.groups[p], r.metric)}</td>
                    ))}
                    <td>{formatEnsoValue(r.diff_nino_nina, r.metric)}</td>
                    <td>{formatPValue(r.p)}</td>
                    <td>{formatPValue(r.p_bh)}</td>
                    <td>{r.sustained_bh ? es.enso.yes : es.enso.no}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <footer className="enso-foot">
            <p data-testid="enso-source">
              {sourceText}
            </p>
            <p>{es.enso.test(stats.results.n_perm)}</p>
            <ul className="enso-caveats" data-testid="enso-caveats">
              <li>{es.enso.caveatFew}</li>
              <li>{nBh === 0 ? es.enso.caveatNone : es.enso.caveatSome(nBh)}</li>
              <li>{es.enso.caveatPolygon}</li>
              <li>{es.enso.caveatRetro}</li>
            </ul>
          </footer>
        </>
      )}
    </section>
  );
}

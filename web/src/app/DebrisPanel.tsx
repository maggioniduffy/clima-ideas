import { es } from "../i18n/es";
import {
  centralScenario,
  criticalDuration,
  fmtDeg,
  fmtKm2,
  fmtMetres,
  fmtQ,
  fmtRatio,
  peakAt,
  peakRange,
  rainDepth,
  type DebrisPeaks,
} from "../layers/debrisCatchments";
import type { DebrisState } from "../layers/useDebrisCatchments";
import { formatLatLon } from "./eventFormat";

export interface DebrisPanelProps {
  state: DebrisState;
  /** Layer manifest values: source and period of the data shown. */
  source: string;
  period: string;
}

const T_NOTE = (peaks: DebrisPeaks) => peaks.return_periods.filter((t) => t > peaks.extrapolation_above_t);

/** Detail-card content of the `debris-catchments` layer: selectors, ranked list, selected catchment and caveats. */
export function DebrisPanel({ state, source, period }: DebrisPanelProps) {
  const { status, peaks, t, cnId, selected, top, geo } = state;
  if (status === "loading" || status === "idle") return <p className="empty">{es.debris.loading}</p>;
  if (status === "error" || !peaks || !geo || !cnId) return <p className="empty">{es.debris.error}</p>;
  const central = centralScenario(peaks);
  const cnNote = [peaks.cn.note, peaks.cn.source].join(" ");
  const methodNote = peaks.method;
  const dem = peaks.catchments_source.periods.join(", ");
  return (
    <div className="debris-panel" data-testid="debris-panel" data-map-shown={state.shownCount}>
      <p className="conv-label" data-testid="debris-label">
        {es.debris.label}
      </p>
      <div className="conv-seg" role="group" aria-label={es.debris.tLabel}>
        {peaks.return_periods.map((rt) => (
          <button
            key={rt}
            type="button"
            data-testid={`debris-t-${rt}`}
            aria-pressed={t === rt}
            aria-label={es.debris.tTitle(rt)}
            onClick={() => state.setT(rt)}
          >
            {es.debris.t(rt, rt > peaks.extrapolation_above_t)}
          </button>
        ))}
      </div>
      <div className="conv-seg" role="group" aria-label={es.debris.cnLabel} data-testid="debris-cn">
        {peaks.cn.scenarios.map((sc) => (
          <button
            key={sc.id}
            type="button"
            data-testid={`debris-cn-${sc.id}`}
            aria-pressed={cnId === sc.id}
            aria-label={es.debris.cnTitle(sc.hsg, sc.cn, sc.central)}
            onClick={() => state.setCnId(sc.id)}
          >
            {es.debris.cn(sc.hsg, sc.cn)}
          </button>
        ))}
      </div>
      <p className="conv-note" data-testid="debris-scenario-label">
        {peaks.cn.label}
      </p>

      <h4 className="debris-h">{es.debris.rankTitle(top.length, state.ranking.length)}</h4>
      {state.planarCount > 0 && (
        <label className="debris-toggle" title={es.debris.planarToggleHint}>
          <input
            type="checkbox"
            data-testid="debris-planar-toggle"
            checked={state.showPlanar}
            onChange={(e) => state.setShowPlanar(e.target.checked)}
          />
          <span>{es.debris.planarToggle(state.planarCount)}</span>
        </label>
      )}
      <ol className="debris-rank" data-testid="debris-ranking">
        {top.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              data-testid={`debris-rank-${r.id}`}
              aria-pressed={state.selectedId === r.id}
              aria-label={es.debris.rankLabel(r.rank, r.props.target, fmtQ(r.peak))}
              onClick={() => state.select(r.id)}
            >
              <span className="debris-rank-name">{es.debris.rankItem(r.rank, r.props.target)}</span>
              <span className="num debris-rank-area">
                {fmtKm2(r.props.area_km2)} {es.debris.km2}
              </span>
              <span className="num debris-rank-q">
                {fmtQ(r.peak)} {es.debris.unit}
              </span>
            </button>
          </li>
        ))}
      </ol>

      {selected ? (
        <section className="debris-detail" data-testid="debris-detail" aria-labelledby="debris-detail-title">
          <h4 id="debris-detail-title" className="debris-h">
            {es.debris.detailTitle(selected.id)}
          </h4>
          {selected.planar_flow && (
            <p className="conv-note debris-warn" data-testid="debris-planar-note" role="note">
              {es.debris.planarNote}
            </p>
          )}
          {selected.overlaps_id != null && (
            <p className="conv-note debris-warn" data-testid="debris-overlap-note" role="note">
              {es.debris.overlapNote(
                selected.overlaps_id,
                geo.features.find((f) => f.properties.id === selected.overlaps_id)?.properties.target ?? "?",
              )}
            </p>
          )}
          <dl className="kv debris-kv">
            <dt>{es.debris.target}</dt>
            <dd data-testid="debris-target">{selected.target}</dd>
            <dt>{es.debris.area}</dt>
            <dd className="num" data-testid="debris-area">
              {fmtKm2(selected.area_km2)} {es.debris.km2}
            </dd>
            <dt>{es.debris.slope}</dt>
            <dd className="num" data-testid="debris-slope">
              {fmtDeg(selected.mean_slope_deg)}
              {es.debris.deg}
            </dd>
            <dt>{es.debris.relief}</dt>
            <dd className="num" data-testid="debris-relief">
              {fmtMetres(selected.relief_m)} {es.debris.metres}
            </dd>
            <dt>{es.debris.flowPath}</dt>
            <dd className="num" data-testid="debris-flowpath">
              {fmtMetres(selected.longest_flow_path_m)} {es.debris.metres}
            </dd>
            {selected.rectangularity != null && selected.elongation != null && (
              <>
                <dt>{es.debris.shape}</dt>
                <dd className="num" data-testid="debris-shape">
                  {es.debris.shapeValue(fmtRatio(selected.rectangularity), fmtRatio(selected.elongation))}
                </dd>
              </>
            )}
            <dt>{es.debris.outlet}</dt>
            <dd className="num">{formatLatLon(selected.outlet_lat, selected.outlet_lon)}</dd>
          </dl>
          <table className="debris-table" data-testid="debris-peaks">
            <caption>{es.debris.peaksTitle}</caption>
            <thead>
              <tr>
                <th scope="col">{es.debris.colT}</th>
                <th scope="col">{es.debris.colCentral(central.hsg, central.cn)}</th>
                <th scope="col">{es.debris.colRange}</th>
                <th scope="col">{es.debris.colDuration}</th>
                <th scope="col">{es.debris.colRain}</th>
              </tr>
            </thead>
            <tbody>
              {peaks.return_periods.map((rt) => {
                const range = peakRange(peaks, selected.id, rt);
                const dur = criticalDuration(peaks, selected.id, central.id, rt);
                return (
                  <tr key={rt} data-testid={`debris-peak-row-${rt}`} data-current={rt === t}>
                    <th scope="row" className="num">
                      {es.debris.t(rt, rt > peaks.extrapolation_above_t)}
                    </th>
                    <td className="num" data-testid={`debris-peak-${rt}`}>
                      {fmtQ(peakAt(peaks, selected.id, central.id, rt) ?? NaN)}
                    </td>
                    <td className="num" data-testid={`debris-range-${rt}`}>
                      {range ? `${fmtQ(range.lo)}–${fmtQ(range.hi)}` : "–"}
                    </td>
                    <td className="num" data-testid={`debris-crit-${rt}`}>
                      {dur == null ? "–" : es.debris.hours(dur)}
                    </td>
                    <td className="num">{dur == null ? "–" : (fmtMetres(rainDepth(peaks, rt, dur) ?? NaN))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {T_NOTE(peaks).length > 0 && (
            <p className="conv-note">{es.debris.extrapolation(T_NOTE(peaks)[0]!)}</p>
          )}
        </section>
      ) : (
        <p className="empty" data-testid="debris-empty">
          {es.debris.noSelection}
        </p>
      )}

      <p className="conv-note" data-testid="debris-source">
        {[
          source,
          es.debris.rainPeriod(peaks.rain.period),
          es.debris.demPeriod(dem || period),
        ].join(es.events.sep)}
      </p>
      <h4 className="debris-h">{es.debris.caveatsTitle}</h4>
      <ul className="debris-caveats" data-testid="debris-caveats">
        {es.debris.caveats.map((c) => (
          <li key={c} className="conv-note">
            {c}
          </li>
        ))}
      </ul>
      <details className="conv-notes" data-testid="debris-notes">
        <summary>{es.debris.notesSummary}</summary>
        <p className="conv-note" data-testid="debris-rain-note">
          {peaks.rain.note}
        </p>
        <p className="conv-note" data-testid="debris-cn-note">
          {cnNote}
        </p>
        <p className="conv-note">{methodNote}</p>
      </details>
    </div>
  );
}
